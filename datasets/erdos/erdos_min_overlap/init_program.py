"""Erdős minimum overlap — legacy dense-grid protocol.

construct_h() returns (h_values, n_points):
  h_values: 1-D float array of length n_points, entries in [0, 1].
  n_points: int, number of uniform grid cells over [0, 2] (dx = 2 / n_points).

run_code() (below the EVOLVE-BLOCK, fixed by the harness) projects h_values onto
the feasible set {0 <= h <= 1, sum(h) == n_points / 2 exactly}, recomputes
c5_bound with the same formula the evaluator uses, and returns the 3-tuple
(h_values, c5_bound, n_points) the evaluator expects.

GLOBAL_BEST_CONSTRUCTION, when present, is a validated (h_values, c5_bound,
n_points) tuple from the current chain-best solution and is used as a warm start.
"""
# EVOLVE-BLOCK-START
import numpy as np


def construct_h():
    """Return (h_values, n_points) for the dense-grid protocol.

    Warm-starts from GLOBAL_BEST_CONSTRUCTION when it is a usable
    (h, c5, n) tuple; otherwise falls back to a neutral feasible array.
    The fallback is deliberately non-degenerate: a flat h ≡ 0.5 satisfies the
    constraints but is the trivial maximizer of the overlap (C5 = 0.5), so it is
    only a last-resort seed, never a target.
    """
    g = None
    try:
        g = GLOBAL_BEST_CONSTRUCTION  # installed by the framework when provided
    except Exception:
        g = None

    if isinstance(g, (tuple, list)) and len(g) == 3:
        try:
            h = np.asarray(g[0], dtype=np.float64).reshape(-1)
            n = int(g[2])
            if h.shape[0] == n and n > 0 and np.all(np.isfinite(h)):
                return np.clip(h, 0.0, 1.0), n
        except Exception:
            pass

    # Neutral fallback: 240 random cells perturbed around 0.5, mean preserved.
    rng = np.random.default_rng(0)
    n = 240
    h = 0.5 + rng.uniform(-0.4, 0.4, n)
    h -= h.mean() - 0.5          # keep mean at 0.5 so projection is a no-op-ish
    return np.clip(h, 0.0, 1.0), n

# EVOLVE-BLOCK-END


def run_code():
    """Run the Erdős minimum overlap construction and return the 3-tuple.

    Returns:
        tuple: (h_values, c5_bound, n_points)
            h_values: np.ndarray, shape (n_points,), discretized step function h
            c5_bound: float, max overlap recomputed from this h_values
            n_points: int, number of bins used to discretize [0, 2]
    """
    h_values, n_points = construct_h()

    n = int(n_points)
    target_sum = n / 2.0

    h_values = np.asarray(h_values, dtype=np.float64).reshape(-1)
    if h_values.shape[0] != n:
        raise ValueError(f"Expected h_values shape ({n},), got {h_values.shape}")
    if not np.all(np.isfinite(h_values)):
        raise ValueError("h_values contain NaN or inf values")

    def _project_box_sum(v: np.ndarray, s: float, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
        # Bisection on tau for x = clip(v - tau, lo, hi) such that sum(x) == s.
        tau_lo = float(np.min(v) - hi)
        tau_hi = float(np.max(v) - lo)
        for _ in range(80):
            tau = (tau_lo + tau_hi) / 2.0
            x = np.clip(v - tau, lo, hi)
            if float(np.sum(x, dtype=np.float64)) > s:
                tau_lo = tau
            else:
                tau_hi = tau
        return np.clip(v - tau_hi, lo, hi)

    h_values = _project_box_sum(h_values, target_sum)

    # The evaluator requires sum(h) == n/2 EXACTLY; the projection lands within
    # float tolerance, so nudge the residual onto a single interior cell that has
    # slack. This keeps the exact-equality cross-check from tripping a rescale.
    residual = target_sum - float(np.sum(h_values, dtype=np.float64))
    if residual != 0.0:
        if residual > 0:
            room = 1.0 - h_values
            idx = int(np.argmax(room))
            if room[idx] >= residual:
                h_values[idx] += residual
        else:
            need = -residual
            idx = int(np.argmax(h_values))
            if h_values[idx] >= need:
                h_values[idx] -= need

    dx = 2.0 / n_points
    j_values = 1.0 - h_values
    correlation = np.correlate(h_values, j_values, mode="full") * dx
    c5_bound = float(np.max(correlation))

    return h_values, c5_bound, n_points
