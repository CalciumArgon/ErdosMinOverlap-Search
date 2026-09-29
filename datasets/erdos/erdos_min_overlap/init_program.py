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


def _legacy_postprocess(g):
    """Warm-start only: convert a legacy (h, c5, n) global into the old 3-tuple
    (bit-identical to the original dense-grid run_code post-processing)."""
    h = np.asarray(g[0], dtype=np.float64).reshape(-1)
    n = int(g[2])
    if h.shape[0] != n:
        return None
    h = _project_box_sum(h, n / 2.0)
    c5 = float(np.max(np.correlate(h, 1.0 - h, mode="full") * 2.0 / n))
    return h, c5, n


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
            return _legacy_postprocess(g)
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
