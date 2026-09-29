"""Erdős minimum overlap — exact piecewise protocol (A类).

construct_h() must return (breaks, values):
  breaks: m+1 fractions.Fraction, strictly increasing, breaks[0] == 0, breaks[-1] == 2.
  values: m-1 Fractions in [0,1] — one per segment EXCEPT the last; the evaluator
          balances the last segment exactly: v_last = (1 - sum(v_i*w_i)) / w_last.
Legacy 3-tuples (h_values, c5_bound, n_points) are accepted for warm-start only.
"""
# EVOLVE-BLOCK-START
from fractions import Fraction

import numpy as np


def _project_box_sum(v, s, lo=0.0, hi=1.0):
    # Bisection on tau for x = clip(v - tau, lo, hi) such that sum(x) = s.
    if not np.all(np.isfinite(v)):
        raise ValueError("h_values contain NaN or inf values")
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


def _legacy_to_spec(g):
    """Warm-start only: compress a legacy (h, c5, n) global into an A类 spec.

    Greedy epsilon-merge of adjacent cells (|v - run_mean| <= 0.02) with
    dyadic-mean run values (denominator 2^16) — measured on the paper
    solution this preserves c5 to ~1e-4 with ~300 segments, while uniform
    quantization destroys it (the optimum's intermediate values carry most
    of the optimality). The balanced segment is chosen as a TAIL of
    consecutive runs (split point k) so the auto-balanced value stays in
    [0,1]; the evaluator re-balances it exactly.
    """
    h = np.asarray(g[0], dtype=np.float64).reshape(-1)
    n = int(g[2])
    if h.shape[0] != n or n < 1:
        return None
    EPS = 0.02
    runs = []
    cur, mean = [0], h[0]
    for i in range(1, n):
        if abs(h[i] - mean) <= EPS:
            cur.append(i)
            mean = np.mean(h[cur])
        else:
            runs.append((cur[0], i, mean))
            cur, mean = [i], h[i]
    runs.append((cur[0], n, mean))
    if len(runs) > 512:
        return None
    breaks_all = [Fraction(2 * r[0], n) for r in runs] + [Fraction(2, 1)]
    values_all = [Fraction(int(round(r[2] * 2**16)), 2**16) for r in runs]
    widths = [breaks_all[i + 1] - breaks_all[i] for i in range(len(values_all))]
    mass = sum(values_all[i] * widths[i] for i in range(len(values_all)))
    for k in range(len(values_all) - 1, 0, -1):
        mass -= values_all[k] * widths[k]
        w_tail = Fraction(2, 1) - breaks_all[k]
        if 1 - w_tail <= mass <= 1:
            return breaks_all[: k + 1] + [Fraction(2, 1)], values_all[:k]
    return None


def _decode_global(g):
    """Decode GLOBAL_BEST_CONSTRUCTION into a returnable construction, or None."""
    if isinstance(g, dict) and g.get("kind") == "spec":
        try:
            breaks = [Fraction(n, d) for n, d in g["breaks"]]
            vals = [Fraction(n, d) for n, d in g["values"]][:-1]
            if len(vals) == len(breaks) - 1:
                return breaks, vals
        except Exception:
            pass
    if isinstance(g, (tuple, list)) and len(g) == 3:
        try:
            return _legacy_to_spec(g)
        except Exception:
            pass
    return None


def _default_spec():
    """Simple valid spec: h ≡ 1/2 (m=8 uniform blocks); exact mass, C5 = 1/2."""
    breaks = [Fraction(k, 4) for k in range(9)]
    return breaks, [Fraction(1, 2)] * 7


def construct_h():
    try:
        g = GLOBAL_BEST_CONSTRUCTION  # builtin installed by the framework (sitecustomize)
    except Exception:
        g = None
    out = _decode_global(g)
    return out if out is not None else _default_spec()

# EVOLVE-BLOCK-END


def run_code():
    """Returns whatever construct_h() returns: (breaks, values) Fractions (A类)
    or a legacy (h_values, c5_bound, n_points) tuple for warm-start."""
    return construct_h()
