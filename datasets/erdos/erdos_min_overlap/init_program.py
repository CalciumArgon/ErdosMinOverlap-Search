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

    Quantizes values to dyadic rationals (1/16 -> 1/8 -> 1/4 -> 1/2 -> 0/1)
    and merges equal runs, so the chains seed from a READABLE piecewise
    structure instead of a 2400-element grid program. The balanced segment is
    chosen as a TAIL of consecutive runs (split point k): the evaluator
    re-balances it exactly, so the mass constraint stays satisfied and the
    balanced value stays in [0,1] as long as the prefix mass fits the window.
    """
    h = np.asarray(g[0], dtype=np.float64).reshape(-1)
    n = int(g[2])
    if h.shape[0] != n or n < 1:
        return None
    for q in (16, 8, 4, 2, 1):
        vals = np.round(h * q) / q
        runs = []
        cur_v, start = vals[0], 0
        for i in range(1, n):
            if vals[i] != cur_v:
                runs.append((start, i, cur_v))
                cur_v, start = vals[i], i
        runs.append((start, n, cur_v))
        if len(runs) > 64:
            continue
        breaks_all = [Fraction(2 * r[0], n) for r in runs] + [Fraction(2, 1)]
        values_all = [Fraction(int(round(r[2] * q)), q) for r in runs]
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
