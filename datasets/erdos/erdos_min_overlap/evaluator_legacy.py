"""
Evaluator for Erdős minimum overlap problem

Minimizing C₅ = max_k ∫ h(x)(1 - h(x+k)) dx
where h is a step function on [0, 2] → [0, 1] with ∫h = 1.

HACK-PROOF DESIGN:
- Programs return (h_values, c5_bound, n_points)
- Evaluator INDEPENDENTLY recomputes C5 from h_values
- Evaluator validates reported C5 matches computed C5 (tolerance: 1e-4)
- If mismatch detected → validation fails
- Programs cannot fake their scores!

This follows the same pattern as autocorrelation_second and matches
the original task.py + verifier.py design from raw_erdos.
"""

import numpy as np

from simpletes.construction import (
    SHARED_CONSTRUCTION_ENV,
    capture_construction_if_requested,
    decode_construction,
)
import json
import time
import os
import signal
import subprocess
import tempfile
import traceback
import sys
import pickle
import psutil
import resource


# ============================================================================
# CONFIGURATION
# ============================================================================

def _env_int(key, default):
    """Get integer from environment variable or use default."""
    return int(os.environ.get(key, default))

def _env_float(key, default):
    """Get float from environment variable or use default."""
    return float(os.environ.get(key, default))

CONCURRENT_PROCESSES = _env_int("EVALUATOR_CONCURRENT_PROCESSES", 64)
OS_BUFFER_PERCENT = _env_float("EVALUATOR_OS_BUFFER_PERCENT", 0.10)
TIMEOUT_SECONDS = _env_int("EVALUATOR_TIMEOUT_SECONDS", 3000)

# Diagnostics (v4). Reference = the warm-start construction the run started from.
#   ERDOS_REFERENCE_C5    float, score of the reference (gap_to_reference_e6)
#   ERDOS_REFERENCE_PATH  JSON construction payload (h, c5, n) or .npy array of h
REFERENCE_C5 = os.environ.get("ERDOS_REFERENCE_C5")
REFERENCE_PATH = os.environ.get("ERDOS_REFERENCE_PATH")
ACTIVE_SHIFT_TOL = 1e-9


# ============================================================================
# EXCEPTIONS
# ============================================================================

class EvaluatorTimeoutError(Exception):
    """Raised when program execution exceeds the time limit."""
    pass


class MemoryLimitExceededError(Exception):
    """Raised when program execution exceeds the memory limit."""
    pass


# ============================================================================
# VALIDATION (from original verifier.py)
# ============================================================================

def verify_c5_solution(h_values: np.ndarray, c5_achieved: float, n_points: int):
    """
    Verify the solution matches ttt_discover's verification logic.

    Args:
        h_values: np.ndarray of step heights
        c5_achieved: The C5 value claimed by the program
        n_points: Number of discretization points

    Returns:
        float: The verified C5 value

    Raises:
        ValueError: If validation fails
    """
    if not isinstance(h_values, np.ndarray):
        try:
            h_values = np.array(h_values, dtype=np.float64)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Cannot convert h_values to numpy array: {e}")

    if len(h_values.shape) != 1:
        raise ValueError(f"h_values must be 1D array, got shape {h_values.shape}")

    if h_values.shape[0] != n_points:
        raise ValueError(f"Expected h shape ({n_points},), got {h_values.shape}")

    if not np.all(np.isfinite(h_values)):
        raise ValueError("h_values contain NaN or inf values")

    # Strict bounds check matching ttt_discover (no tolerance)
    if np.any(h_values < 0) or np.any(h_values > 1):
        raise ValueError(f"h(x) is not in [0, 1]. Range: [{h_values.min()}, {h_values.max()}]")

    # Degenerate-solution guard (added, not in the original verifier): a constant
    # h is feasible and scores C5 = 0.5 (the trivial maximizer of the overlap),
    # so under the reciprocal score it farms a guaranteed 2.0 without solving
    # anything. Reject it here rather than via prompt text, so it lands in the
    # failure-pattern histogram instead of occupying a score slot. ptp < 1e-9
    # only fires on truly flat arrays; real constructions (ptp ~ 1.0) pass.
    if float(np.ptp(h_values)) < 1e-9:
        raise ValueError("degenerate_constant_solution: h is constant (trivial overlap maximizer)")

    n = n_points
    target_sum = n / 2.0
    current_sum = np.sum(h_values)

    # Exact equality check matching ttt_discover
    if current_sum != target_sum:
        h_values = h_values * (target_sum / current_sum)
        if np.any(h_values < 0) or np.any(h_values > 1):
            raise ValueError(f"After normalization, h(x) is not in [0, 1]. Range: [{h_values.min()}, {h_values.max()}]")

    dx = 2.0 / n_points

    j_values = 1.0 - h_values
    correlation = np.correlate(h_values, j_values, mode="full") * dx
    computed_c5 = np.max(correlation)

    if not np.isfinite(computed_c5):
        raise ValueError(f"Computed C5 is not finite: {computed_c5}")

    if not np.isclose(computed_c5, c5_achieved, atol=1e-8):
        raise ValueError(f"C5 mismatch: reported {c5_achieved:.8f}, computed {computed_c5:.8f}")

    return computed_c5, h_values, correlation


def evaluate_erdos_solution(h_values: np.ndarray, c5_bound: float, n_points: int) -> float:
    """
    Evaluate the Erdős solution (matches original verifier.py).
    
    Args:
        h_values: Step function values
        c5_bound: Claimed C5 bound
        n_points: Number of points
    
    Returns:
        float: The verified C5 value
    """
    verify_c5_solution(h_values, c5_bound, n_points)
    return float(c5_bound)


# ============================================================================
# DIAGNOSTICS (descriptive only; never affect validity or score)
# ============================================================================

_REFERENCE_CACHE = {}


def _load_reference_h():
    """Reference step heights from ERDOS_REFERENCE_PATH, or None."""
    if not REFERENCE_PATH or not os.path.exists(REFERENCE_PATH):
        return None
    if REFERENCE_PATH in _REFERENCE_CACHE:
        return _REFERENCE_CACHE[REFERENCE_PATH]
    ref = None
    try:
        if REFERENCE_PATH.endswith(".npy"):
            ref = np.load(REFERENCE_PATH)
        else:
            with open(REFERENCE_PATH, encoding="utf-8") as f:
                val = decode_construction(json.load(f))
            ref = val[0] if isinstance(val, (tuple, list)) and len(val) == 3 else val
        ref = np.asarray(ref, dtype=np.float64).reshape(-1)
        if ref.size == 0 or not np.all(np.isfinite(ref)):
            ref = None
    except Exception:
        ref = None
    _REFERENCE_CACHE[REFERENCE_PATH] = ref
    return ref


def step_l1_distance(a, b):
    """Exact L1 distance on [0, 2] between two uniform-grid step functions.

    a has len(a) cells of width 2/len(a), b has len(b) cells of width 2/len(b).
    Integrated piecewise over the union of both breakpoint sets, on which both
    functions are constant.
    """
    na, nb = len(a), len(b)
    # Breakpoints in units of 1/(na*nb) of [0, 1]: a's are multiples of nb,
    # b's are multiples of na, so the union is exact in integers.
    pts = np.union1d(np.arange(na + 1, dtype=np.int64) * nb, np.arange(nb + 1, dtype=np.int64) * na)
    left, right = pts[:-1], pts[1:]
    ia = np.minimum(left // nb, na - 1)
    ib = np.minimum(left // na, nb - 1)
    widths = (right - left).astype(np.float64) * (2.0 / (na * nb))
    return float(np.sum(np.abs(a[ia] - b[ib]) * widths))


def orbit_l1_to_reference(h, ref):
    """min L1 distance from h to the symmetry orbit of ref.

    C is invariant under reflection f(2-x) and complement 1-f (both keep
    the integral equal to 1), so all four images of ref are equivalent.
    """
    images = (ref, ref[::-1], 1.0 - ref, 1.0 - ref[::-1])
    return min(step_l1_distance(h, g) for g in images)


def diagnostic_metrics(h_scored, correlation, c5_value):
    """Search-dynamics diagnostics reported alongside the score."""
    max_corr = float(np.max(correlation))
    out = {
        "c5_str": f"{c5_value:.10f}",
        "n_points": int(h_scored.shape[0]),
        "n_active_shifts": int(np.sum(correlation >= max_corr - ACTIVE_SHIFT_TOL)),
        "used_warm_start": bool(
            os.environ.get(SHARED_CONSTRUCTION_ENV)
            and os.path.exists(os.environ[SHARED_CONSTRUCTION_ENV])
        ),
    }
    if REFERENCE_C5:
        try:
            out["gap_to_reference_e6"] = round((c5_value - float(REFERENCE_C5)) * 1e6, 4)
        except ValueError:
            pass
    ref = _load_reference_h()
    if ref is not None:
        l1 = orbit_l1_to_reference(h_scored, ref)
        out["l1_to_reference"] = float(f"{l1:.6g}")
        out["returned_reference_unchanged"] = bool(l1 < 1e-12)
    return out


# ============================================================================
# SUBPROCESS EXECUTION
# ============================================================================

def _get_memory_limit_bytes():
    """Calculate per-process memory limit based on system resources."""
    total_mem = psutil.virtual_memory().total
    safe_mem = total_mem * (1.0 - OS_BUFFER_PERCENT)
    return int(safe_mem / CONCURRENT_PROCESSES)


def run_with_timeout(program_path, timeout_seconds=None):
    """
    Run the user program in a subprocess with timeout and memory limits.
    
    Args:
        program_path: Path to the program file
        timeout_seconds: Maximum execution time
    
    Returns:
        dict: {"solution": (h_values, c5_bound, n_points)}
    
    Raises:
        EvaluatorTimeoutError: If execution times out
        MemoryLimitExceededError: If memory limit exceeded
        RuntimeError: For other execution errors
    """
    if timeout_seconds is None:
        timeout_seconds = TIMEOUT_SECONDS
    
    limit_bytes = _get_memory_limit_bytes()
    limit_mb = limit_bytes / (1024 * 1024)
    
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as temp_file:
        script = f'''
import resource

def limit_memory():
    try:
        soft, hard = {limit_bytes}, {limit_bytes}
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
        resource.setrlimit(resource.RLIMIT_DATA, (soft, hard))
    except ValueError:
        pass

limit_memory()

import sys, os, pickle, traceback, numpy as np, importlib.util

sys.path.insert(0, os.path.dirname('{program_path}'))

def _load(path):
    spec = importlib.util.spec_from_file_location("user_prog", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    mod = _load('{program_path}')
    out = mod.run_code() if hasattr(mod, 'run_code') and callable(getattr(mod, 'run_code')) else None
    if out is None:
        raise RuntimeError('Program must define run_code().')
    
    # Expect output format: (h_values, c5_bound, n_points)
    if isinstance(out, (tuple, list)) and len(out) == 3:
        h_values = np.asarray(out[0], dtype=float)
        c5_bound = float(out[1])
        n_points = int(out[2])
        solution = (h_values, c5_bound, n_points)
    else:
        raise RuntimeError(f'Invalid output format. Expected (h_values, c5_bound, n_points), got {{type(out)}} with len={{len(out) if hasattr(out, "__len__") else "N/A"}}')
    
    with open('{temp_file.name}.results', 'wb') as f:
        pickle.dump({{"solution": solution}}, f)

except MemoryError:
    with open('{temp_file.name}.results', 'wb') as f:
        pickle.dump({{"error": "Memory limit exceeded (MemoryError caught)"}}, f)
except Exception as e:
    traceback.print_exc()
    with open('{temp_file.name}.results', 'wb') as f:
        pickle.dump({{"error": f"{{type(e).__name__}}: {{e}}"}}, f)
'''
        temp_file.write(script.encode())
        temp_file_path = temp_file.name
    
    results_path = f"{temp_file_path}.results"
    
    try:
        child_env = os.environ.copy()
        child_env["OMP_NUM_THREADS"] = "4"
        child_env["OPENBLAS_NUM_THREADS"] = "4"
        child_env["MKL_NUM_THREADS"] = "4"
        child_env["NUMEXPR_NUM_THREADS"] = "4"
        child_env["VECLIB_MAXIMUM_THREADS"] = "4"
        child_env["BLIS_NUM_THREADS"] = "4"

        process = subprocess.Popen(
            [sys.executable, temp_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=child_env,
        )
        
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            exit_code = process.returncode
            
            if exit_code in (-9, -11):
                raise MemoryLimitExceededError(
                    f"Process killed by OS (likely OOM). Limit was {limit_mb:.2f}MB"
                )
            
            if os.path.exists(results_path):
                try:
                    with open(results_path, "rb") as f:
                        results = pickle.load(f)
                    if "error" in results:
                        err_msg = results["error"]
                        if "MemoryError" in err_msg:
                            raise MemoryLimitExceededError(err_msg)
                        raise RuntimeError(f"Program execution failed: {err_msg}")
                    return results
                except (pickle.UnpicklingError, EOFError):
                    raise RuntimeError(
                        "Failed to read results file (possibly truncated due to crash)."
                    )
            else:
                if exit_code != 0:
                    err_out = stderr.decode()
                    if "MemoryError" in err_out:
                        raise MemoryLimitExceededError("Memory limit exceeded (stderr)")
                    raise RuntimeError(
                        f"Process exited with code {exit_code}. Stderr: {err_out}"
                    )
                raise RuntimeError("Results file not found but process exited 0.")
        
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            raise EvaluatorTimeoutError(
                f"Process timed out after {timeout_seconds} seconds"
            )
    
    finally:
        for path in (temp_file_path, results_path):
            if os.path.exists(path):
                os.unlink(path)


# ============================================================================
# MAIN EVALUATE FUNCTION
# ============================================================================

def _make_error_result(error_msg, eval_time=0.0):
    """Create a standardized error result dict."""
    return {
        "c5": float('inf'),
        "validity": 0.0,
        "eval_time": float(eval_time),
        "combined_score": 0.0,
        "error": error_msg,
    }


def evaluate(program_path):
    """
    Evaluate the program by running it and computing the C₅ value.
    
    Args:
        program_path: Path to the program file
    
    Returns:
        dict: Evaluation metrics including:
            - c5: The C₅ overlap value (lower is better)
            - validity: 1.0 if valid, 0.0 otherwise
            - eval_time: Execution time in seconds
            - combined_score: 1/(1e-8 + c5) for valid solutions (higher is better)
            - error: (optional) Error message if evaluation failed
    """
    try:
        start_time = time.time()
        
        res = run_with_timeout(program_path, timeout_seconds=TIMEOUT_SECONDS)
        
        eval_time = time.time() - start_time
        
        solution = res.get("solution")
        if not isinstance(solution, (tuple, list)) or len(solution) != 3:
            return _make_error_result("Invalid solution format. Expected (h_values, c5_bound, n_points)", eval_time)
        
        h_values, c5_bound, n_points = solution
        h_values = np.asarray(h_values, dtype=float)
        c5_bound = float(c5_bound)
        n_points = int(n_points)
        
        # Use the original evaluation logic from verifier.py
        try:
            c5_value, h_scored, correlation = verify_c5_solution(h_values, c5_bound, n_points)
            c5_value = float(c5_bound)
        except ValueError as e:
            print(f"Validation failed: {e}")
            return {
                "c5": float('inf'),
                "validity": 0.0,
                "eval_time": float(eval_time),
                "combined_score": 0.0,
                "error": str(e),
            }
        
        # Combined score - matches original task.py line 39: return float(1.0 / (1e-8 + c5_bound))
        capture_construction_if_requested(solution)

        combined_score = 1.0 / (1e-8 + c5_value)
        
        print(f"Evaluation: valid=True, c5={c5_value:.10f}, score={combined_score:.10f}, time={eval_time:.2f}s")
        
        result = {
            "c5": float(c5_value),
            "validity": 1.0,
            "eval_time": float(eval_time),
            "combined_score": float(combined_score),
        }
        try:
            result.update(diagnostic_metrics(h_scored, correlation, c5_value))
        except Exception as e:  # diagnostics must never invalidate a candidate
            result["diagnostics_error"] = f"{type(e).__name__}: {e}"
        return result
    
    except MemoryLimitExceededError as e:
        print(f"Evaluation failed due to memory limit: {e}")
        return _make_error_result(f"Memory limit exceeded: {e}")
    
    except EvaluatorTimeoutError as e:
        print(f"Evaluation failed due to timeout: {e}")
        return _make_error_result(f"Timeout: {e}")
    
    except Exception as e:
        print(f"Evaluation failed: {e}")
        traceback.print_exc()
        return _make_error_result(f"{type(e).__name__}: {e}")