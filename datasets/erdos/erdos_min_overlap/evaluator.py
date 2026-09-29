"""
Evaluator for Erdős minimum overlap problem

Minimizing C₅ = max_k ∫ h(x)(1 - h(x+k)) dx
where h is a step function on [0, 2] → [0, 1] with ∫h = 1.

Two coexisting candidate protocols, routed by the shape of run_code()'s return:

- A类 (exact spec): (breaks, values) — a list of m+1 fractions.Fraction breakpoints
  (strictly increasing, endpoints 0 and 2) and m-1 Fraction segment values in [0,1].
  The evaluator balances the mass constraint exactly by solving the last segment
  value V = (1 - Σ v_i·w_i) / w_last and scores with the EXACT rational maximum of
  M(s) = Σ_{p,q} v_p(1-v_q)·λ(I_p ∩ (I_q-s)) over the sliding-window convention.
  M(s) is piecewise linear with kinks at pairwise break differences {b_j - b_i},
  so the supremum is attained at a kink and is computed with zero rounding error;
  the score uses U = round-up float of the exact max (a certified upper bound).

- Legacy (dense grid): (h_values, c5_bound, n_points) — kept bit-identical to the
  original float pipeline, used for warm-starting from pre-exact constructions.

HACK-PROOF DESIGN (unchanged for legacy):
- Evaluator INDEPENDENTLY recomputes C5 from h_values
- Evaluator validates reported C5 matches computed C5 (tolerance: 1e-8)
- If mismatch detected → validation fails
- Programs cannot fake their scores!
"""

import numpy as np

from simpletes.construction import capture_construction_if_requested
import time
import os
import signal
import subprocess
import tempfile
import traceback
import sys
import pickle
import psutil
import math
import numbers
from fractions import Fraction
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
TIMEOUT_SECONDS = _env_int("EVALUATOR_TIMEOUT_SECONDS", 1100)


# ============================================================================
# A类 LIMITS
# ============================================================================

MAX_SEGMENTS = 64
MAX_DENOM_BITS = 20
MAX_DENOM = 1 << MAX_DENOM_BITS           # 1048576
REL_EQUIOSC_DELTA = Fraction(1, 10**9)    # relative delta for equioscillation count
SENS_DELTA = Fraction(1, 1 << 20)         # exact one-sided break perturbation
SNAP_MAX_DENOM = 64                       # small-denominator cap for snap hints
LOCAL_OPT_EPS = Fraction(1, 10**9)        # |sensitivity| below this counts as locally optimal


# ============================================================================
# EXCEPTIONS
# ============================================================================

class EvaluatorTimeoutError(Exception):
    """Raised when program execution exceeds the time limit."""
    pass


class MemoryLimitExceededError(Exception):
    """Raised when program execution exceeds the memory limit."""
    pass


class SpecError(ValueError):
    """A类 spec validation failure; message is a short, teachable error code."""


# ============================================================================
# VALIDATION (from original verifier.py) — legacy dense-grid path, unchanged
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

    return computed_c5


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
        dict: {"solution": {"kind": "spec"|"legacy", "payload": ...}}
        spec payload: (breaks, values) lists of Fraction
        legacy payload: (h_values ndarray, c5_bound float, n_points int)

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

    # Route by return shape:
    #   (breaks, values) len==2                        -> exact rational spec (A类)
    #   (h_values, c5_bound, n_points) len==3          -> legacy dense grid
    if isinstance(out, (tuple, list)) and len(out) == 2:
        solution = {{"kind": "spec", "payload": tuple(out)}}
    elif isinstance(out, (tuple, list)) and len(out) == 3:
        solution = {{"kind": "legacy", "payload": (np.asarray(out[0], dtype=float), float(out[1]), int(out[2]))}}
    else:
        raise RuntimeError(f'Invalid output format. Expected (breaks, values) or (h_values, c5_bound, n_points), got {{type(out)}} with len={{len(out) if hasattr(out, "__len__") else "N/A"}}')

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
# A类 EXACT RATIONAL KERNEL
# ============================================================================

def _to_list(x, field):
    """ndarray/tuple/list → list; anything else raises SpecError."""
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (list, tuple)):
        return list(x)
    raise SpecError(f"{field}_must_be_list")


def _coerce_rat(x, field):
    """Accept int (not bool) or Fraction; reject floats with a teachable message."""
    if isinstance(x, bool):
        raise SpecError(f"{field}_must_be_int_or_fraction")
    if isinstance(x, numbers.Integral):
        return Fraction(int(x), 1)
    if isinstance(x, Fraction):
        return x
    if isinstance(x, float):
        raise SpecError("break_or_value_is_float_use_Fraction(num,den)")
    raise SpecError(f"{field}_must_be_int_or_fraction")


def validate_spec(payload):
    """Validate an A类 payload; return (breaks, values) as lists of Fractions."""
    if not isinstance(payload, (tuple, list)) or len(payload) != 2:
        raise SpecError("invalid_solution_format_expected_(breaks,_values)")

    breaks = _to_list(payload[0], "breaks")
    if not breaks:
        raise SpecError("breaks_empty")
    breaks = [_coerce_rat(b, "break") for b in breaks]

    m = len(breaks) - 1
    if m > MAX_SEGMENTS:
        raise SpecError(f"too_many_segments m={m}_limit_{MAX_SEGMENTS}")
    for b in breaks:
        if b.denominator > MAX_DENOM:
            raise SpecError("denominator_too_large_limit_2^20")
    if breaks[0] != 0 or breaks[-1] != 2:
        raise SpecError("endpoints_not_0_2")
    for i in range(m):
        if breaks[i + 1] <= breaks[i]:
            raise SpecError("breaks_not_strictly_increasing_zero_width_forbidden")

    values = _to_list(payload[1], "values")
    if len(values) != m - 1:
        hint = "_for_1_segment_values_must_be_empty" if m == 1 else ""
        raise SpecError(f"values_length_mismatch expected_{m - 1}_got_{len(values)}{hint}")
    values = [_coerce_rat(v, "value") for v in values]
    for v in values:
        if v.denominator > MAX_DENOM:
            raise SpecError("denominator_too_large_limit_2^20")
        if v < 0 or v > 1:
            raise SpecError("value_out_of_range_must_be_in_[0,1]")

    return breaks, values


def compute_last_value(breaks, values):
    """Analytically balance the mass constraint; returns the last segment value (exact)."""
    m = len(breaks) - 1
    widths = [breaks[i + 1] - breaks[i] for i in range(m)]
    mass = sum(values[i] * widths[i] for i in range(m - 1))
    v_last = (Fraction(1, 1) - mass) / widths[-1]
    if v_last < 0 or v_last > 1:
        raise SpecError(f"mass_balance_out_of_range v_last={v_last.numerator}/{v_last.denominator}")
    return v_last


def _lam_pq(breaks, p, q, s):
    """Exact overlap length λ(I_p ∩ (I_q − s)) for the sliding-window convention."""
    lo = breaks[p] if breaks[p] > breaks[q] - s else breaks[q] - s
    hi = breaks[p + 1] if breaks[p + 1] < breaks[q + 1] - s else breaks[q + 1] - s
    return hi - lo if hi > lo else Fraction(0)


def M_at(breaks, v_all, s):
    """Direct exact evaluation of M(s) at a fixed shift (O(m²))."""
    total = Fraction(0)
    for p in range(len(v_all)):
        for q in range(len(v_all)):
            lam = _lam_pq(breaks, p, q, s)
            if lam:
                total += v_all[p] * (1 - v_all[q]) * lam
    return total


def tent_events(breaks, v_all):
    """
    Slope-change events for M(s) = Σ_{p,q} v_p(1-v_q)·λ(I_p ∩ (I_q − s)).

    For each pair, λ as a function of s is a tent (0 / ramp / plateau / ramp / 0)
    with slope changes ±w at the four pairwise break differences of the pair.
    """
    events = []
    m = len(v_all)
    for p in range(m):
        for q in range(m):
            w = v_all[p] * (1 - v_all[q])          # ≥ 0; near-binary specs skip most pairs
            if w == 0:
                continue
            bp, bp1 = breaks[p], breaks[p + 1]
            bq, bq1 = breaks[q], breaks[q + 1]
            events.append((bq - bp1, w))
            events.append((bq - bp, -w))
            events.append((bq1 - bp1, -w))
            events.append((bq1 - bp, w))
    return events


def exact_sweep(breaks, v_all):
    """
    Exact piecewise-linear sweep: M(s) is linear between consecutive kinks
    (pairwise break differences), so its max over [−2, 2] is attained at a kink.
    Returns {"best": Fraction, "argmax_shifts": [Fraction], "records": [(s, M, slope_before, slope_after)]}.
    """
    events = tent_events(breaks, v_all)
    events.sort(key=lambda e: e[0])

    best = Fraction(0, 1)              # M(−2) == 0 exactly (empty overlap window)
    argmax = []
    records = []
    M = Fraction(0, 1)
    slope = Fraction(0, 1)
    prev_s = Fraction(-2, 1)

    i, n_ev = 0, len(events)
    while i < n_ev:
        s = events[i][0]
        M += slope * (s - prev_s)      # M is continuous; value at the kink
        prev_s = s
        dslope = Fraction(0, 1)
        while i < n_ev and events[i][0] == s:
            dslope += events[i][1]
            i += 1
        records.append((s, M, slope, slope + dslope))
        if M > best:
            best, argmax = M, [s]
        elif M == best:
            argmax.append(s)
        slope += dslope

    if not argmax:
        argmax = [Fraction(-2, 1)]     # M ≡ 0 (e.g. all w == 0): max is 0 at any s

    return {"best": best, "argmax_shifts": argmax, "records": records}


def fraction_round_up(x):
    """Float upper bound of an exact rational: round-to-nearest, then bump if it fell below."""
    f = float(x)
    if Fraction(f) < x:
        f = math.nextafter(f, math.inf)
    return f


def fraction_round_down(x):
    """Float lower bound of an exact rational."""
    f = float(x)
    if Fraction(f) > x:
        f = math.nextafter(f, -math.inf)
    return f


def fmt_frac(x):
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


# ============================================================================
# A类 DIAGNOSTICS (short, prompt-safe strings; they land in node.metrics)
# ============================================================================

def value_sensitivities(breaks, v_all, s):
    """
    Exact dM/dv_p at shift s for the FREE values (p ≤ m−2), projected along the
    auto-balance coupling: V = v_{m−1} is a function of the free values with
    dV/dv_p = −w_p / w_{m−1}.
    """
    m = len(v_all)
    widths = [breaks[i + 1] - breaks[i] for i in range(m)]
    w_last = widths[-1]
    lam = [[_lam_pq(breaks, p, q, s) for q in range(m)] for p in range(m)]
    row_last = sum((1 - v_all[q]) * lam[m - 1][q] for q in range(m))
    col_last = sum(v_all[r] * lam[r][m - 1] for r in range(m))
    out = []
    for p in range(m - 1):
        d = sum((1 - v_all[q]) * lam[p][q] for q in range(m))
        d -= sum(v_all[r] * lam[r][p] for r in range(m))
        d += (-widths[p] / w_last) * (row_last - col_last)
        out.append((p, d))
    return out


def break_sensitivities(breaks, values, v_all, s):
    """
    Exact one-sided directional derivatives w.r.t. interior breaks, re-balancing
    the mass after each perturbation (derivatives along the feasible manifold).
    Infeasible directions are skipped.
    """
    m = len(v_all)
    base = M_at(breaks, v_all, s)
    out = []
    for p in range(1, m):
        for sign in (1, -1):
            nb = list(breaks)
            nb[p] += sign * SENS_DELTA
            if not (nb[p - 1] < nb[p] < nb[p + 1]):
                continue
            try:
                v_new = compute_last_value(nb, values)
            except SpecError:
                continue
            shifted = M_at(nb, values + [v_new], s)
            out.append((p, sign, (shifted - base) / (sign * SENS_DELTA)))
    return out


def sensitivity_text_from(vs, bs, slope_before, slope_after):
    """Compact one-line sensitivity summary for the best shift."""
    parts = [f"sl+{float(slope_after):+.4f}/sl-{float(slope_before):+.4f}"]
    vs_sorted = sorted(vs, key=lambda t: abs(t[1]), reverse=True)
    for p, d in vs_sorted[:2]:
        parts.append(f"v{p}:{float(d):+.4f}")
    bs_sorted = sorted(bs, key=lambda t: abs(t[2]), reverse=True)
    if bs_sorted:
        p, sign, d = bs_sorted[0]
        parts.append(f"b{p}{'+' if sign > 0 else '-'}:{float(d):+.4f}")
    return " ".join(parts)


def _move_hint(vs, bs):
    """Single strongest actionable move: parameter, direction, exact gain per unit."""
    best_abs, best_txt = None, "none"
    for p, d in vs:
        if best_abs is None or abs(d) > best_abs:
            best_abs = abs(d)
            best_txt = f"v{p}{'down' if d > 0 else 'up'} gain {float(abs(d)):.4f}/unit"
    for p, sign, d in bs:
        if best_abs is None or abs(d) > best_abs:
            best_abs = abs(d)
            best_txt = f"b{p}{'left' if d > 0 else 'right'} gain {float(abs(d)):.4f}/unit"
    return best_txt


def _snap_hint(breaks, v_all, s, mv, best):
    """Nearest small-denominator rational for an active shift, with the exact
    M value there (drift to huge denominators buys nothing -> snap back)."""
    r = s.limit_denominator(SNAP_MAX_DENOM)
    if r < Fraction(-2, 1):
        r = Fraction(-2, 1)
    if r > Fraction(2, 1):
        r = Fraction(2, 1)
    if r == s:
        return f"s={fmt_frac(s)}:small"
    mr = M_at(breaks, v_all, r)
    return f"s={fmt_frac(s)}~{fmt_frac(r)} M={float(mr):.6f} d{float(mr - best):+.2e}"


def build_diagnostics(breaks, values, v_all, sweep):
    """Short diagnostic fields for node.metrics / prompt display."""
    best = sweep["best"]
    records = sweep["records"]
    ranked = sorted(records, key=lambda r: (-r[1], r[0]))[:3]
    active_shifts = [f"s={fmt_frac(s)}:{float(mv):.6f}" for s, mv, _, _ in ranked]
    delta = REL_EQUIOSC_DELTA * best
    equiosc_count = sum(1 for r in records if best - r[1] <= delta)
    if ranked:
        s_star, _, sl_b, sl_a = ranked[0]
        vs = value_sensitivities(breaks, v_all, s_star)
        bs = break_sensitivities(breaks, values, v_all, s_star)
        sens = sensitivity_text_from(vs, bs, sl_b, sl_a)
        max_v = max((abs(d) for _, d in vs), default=Fraction(0))
        max_b = max((abs(d) for _, _, d in bs), default=Fraction(0))
        local_optimal = max_v < LOCAL_OPT_EPS and max_b < LOCAL_OPT_EPS
        move_hint = _move_hint(vs, bs)
        snap_hints = [_snap_hint(breaks, v_all, s, mv, best) for s, mv, _, _ in ranked]
    else:
        sens = ""
        local_optimal = True
        move_hint = "none"
        snap_hints = []
    return {
        "n_segments": len(v_all),
        "n_kinks": len(records),
        "equioscillation_count": equiosc_count,
        "active_shifts": active_shifts,
        "active_sensitivity": sens,
        "local_optimal": local_optimal,
        "move_hint": move_hint,
        "snap_hints": snap_hints,
    }


def build_capture_spec(breaks, v_all):
    """Encodable capture format (all ints; Fraction is NOT supported by encode_construction)."""
    return {
        "kind": "spec",
        "breaks": [[b.numerator, b.denominator] for b in breaks],
        "values": [[v.numerator, v.denominator] for v in v_all],
    }


def evaluate_spec_solution(payload, eval_time):
    """Score an A类 (breaks, values) candidate with the exact rational certificate."""
    try:
        breaks, values = validate_spec(payload)
        v_all = values + [compute_last_value(breaks, values)]
        sweep = exact_sweep(breaks, v_all)
        best = sweep["best"]
        U = fraction_round_up(best)
        c5f = float(best)
        diag = build_diagnostics(breaks, values, v_all, sweep)
    except SpecError as e:
        return _make_error_result(str(e), eval_time)

    capture_construction_if_requested(build_capture_spec(breaks, v_all))

    print(f"Evaluation: valid=True, c5={c5f:.10f}, U={U:.10f}, score={1.0 / (1e-8 + U):.10f}, time={eval_time:.2f}s")

    return {
        "c5": c5f,
        "validity": 1.0,
        "eval_time": float(eval_time),
        "combined_score": float(1.0 / (1e-8 + U)),
        "c5_cert_lo": fraction_round_down(best),
        "c5_cert_hi": U,
        "n_segments": diag["n_segments"],
        "n_kinks": diag["n_kinks"],
        "equioscillation_count": diag["equioscillation_count"],
        "active_shifts": diag["active_shifts"],
        "active_sensitivity": diag["active_sensitivity"],
        "local_optimal": diag["local_optimal"],
        "move_hint": diag["move_hint"],
        "snap_hints": diag["snap_hints"],
    }


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
            - combined_score: 1/(1e-8 + c5) (legacy float path) or
              1/(1e-8 + U) (A类 exact path, U = certified round-up upper bound)
            - error: (optional) Error message if evaluation failed
            - A类 diagnostics: c5_cert_lo/hi, n_segments, n_kinks,
              equioscillation_count, active_shifts, active_sensitivity
    """
    try:
        start_time = time.time()

        res = run_with_timeout(program_path, timeout_seconds=TIMEOUT_SECONDS)

        eval_time = time.time() - start_time

        solution = res.get("solution")
        if not isinstance(solution, dict) or "kind" not in solution or "payload" not in solution:
            return _make_error_result("Invalid runner payload", eval_time)

        kind = solution["kind"]
        payload = solution["payload"]

        if kind == "legacy":
            # Bit-identical legacy pipeline (original float verification)
            if not isinstance(payload, (tuple, list)) or len(payload) != 3:
                return _make_error_result("Invalid solution format. Expected (h_values, c5_bound, n_points)", eval_time)

            h_values, c5_bound, n_points = payload
            h_values = np.asarray(h_values, dtype=float)
            c5_bound = float(c5_bound)
            n_points = int(n_points)

            try:
                c5_value = evaluate_erdos_solution(h_values, c5_bound, n_points)
            except ValueError as e:
                print(f"Validation failed: {e}")
                return {
                    "c5": float('inf'),
                    "validity": 0.0,
                    "eval_time": float(eval_time),
                    "combined_score": 0.0,
                    "error": str(e),
                }

            capture_construction_if_requested((h_values, c5_bound, n_points))

            combined_score = 1.0 / (1e-8 + c5_value)

            print(f"Evaluation: valid=True, c5={c5_value:.10f}, score={combined_score:.10f}, time={eval_time:.2f}s")

            return {
                "c5": float(c5_value),
                "validity": 1.0,
                "eval_time": float(eval_time),
                "combined_score": float(combined_score),
            }

        if kind == "spec":
            return evaluate_spec_solution(payload, eval_time)

        return _make_error_result("Unknown solution kind", eval_time)

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
