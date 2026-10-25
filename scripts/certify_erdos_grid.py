#!/usr/bin/env python
"""Exact rational certification of a dense-grid Erdős minimum-overlap bound.

Given grid heights h (n cells on [0, 2]), computes in exact arithmetic

    C5(h) = (2/n) * max_k sum_i h_i (1 - h_{i+k})

which equals C(f_h) for the step function f_h (problem_formulation.md Prop 6.1)
and is therefore a rigorous upper bound on the Erdős constant (Thm 5.1).

Steps:
  1. Every float64 entry is converted exactly to a dyadic rational.
  2. 0 <= h_i <= 1 is checked exactly.
  3. Mass: if sum(h) != n/2 exactly, the whole difference is moved onto ONE
     cell that has room (the certified function is then this corrected array;
     the size of the change is reported). No rescaling, no tolerance.
  4. All h_i are scaled by a common power of two D, so every correlation is an
     integer combination; the full correlation is computed exactly with one
     big-integer product (Kronecker substitution), optionally cross-checked by
     the direct O(n^2) sum.
  5. The rational maximum is printed, together with a decimal rounded UP.

Usage (repo root, project venv):
    .venv/bin/python scripts/certify_erdos_grid.py CONSTRUCTION.json [--digits 12]
        [--direct] [--repeat 2 3] [--expect 0.38086768]
CONSTRUCTION is a SimpleTES construction payload ((h, c5, n) tuple), a .npy
array, or a JSON list of floats. Exit code 0 on success, 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from fractions import Fraction

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def load_h(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        return np.asarray(np.load(path), dtype=np.float64).reshape(-1)
    from simpletes.construction import decode_construction
    with open(path, encoding="utf-8") as f:
        val = decode_construction(json.load(f))
    if isinstance(val, (tuple, list)) and len(val) == 3 and not np.isscalar(val[0]):
        val = val[0]
    return np.asarray(val, dtype=np.float64).reshape(-1)


def to_dyadic(h: np.ndarray) -> list[Fraction]:
    if not np.all(np.isfinite(h)):
        raise ValueError("non-finite entry")
    return [Fraction(float(x)) for x in h]  # exact for every float64


def fix_mass(q: list[Fraction]) -> tuple[list[Fraction], Fraction, int | None]:
    """Move sum(q) - n/2 onto one cell with enough room. Returns (q, delta, idx)."""
    n = len(q)
    delta = Fraction(n, 2) - sum(q)
    if delta == 0:
        return q, delta, None
    room = [(1 - x) if delta > 0 else x for x in q]
    idx = max(range(n), key=lambda i: room[i])
    if room[idx] < abs(delta):
        raise ValueError(f"mass defect {float(delta):.3e} exceeds the room of every single cell")
    q = list(q)
    q[idx] += delta
    return q, delta, idx


def scale_to_int(q: list[Fraction]) -> tuple[list[int], int]:
    """Common power-of-two denominator D; returns (H with H_i = q_i * D, D)."""
    p = 0
    for x in q:
        d = x.denominator
        if d & (d - 1):
            raise ValueError("non-dyadic entry")  # cannot happen for float input
        p = max(p, d.bit_length() - 1)
    D = 1 << p
    return [int(x * D) for x in q], D


def correlation_kronecker(H: list[int], D: int) -> list[int]:
    """c_k = sum_i H_i (D - H_{i+k}) for every lag, as exact integers.

    Lags are ordered like np.correlate(h, 1-h, 'full'). Computed as the
    coefficients of one big-integer product.
    """
    n = len(H)
    G = [D - x for x in H]
    nbytes = (2 * D.bit_length() + n.bit_length() + 2 + 7) // 8
    # Pack with fixed-width little-endian limbs (a bytes join is linear in size;
    # repeated shifting would be quadratic). X = 2^(8 * nbytes).
    a = int.from_bytes(b"".join(x.to_bytes(nbytes, "little") for x in H), "little")         # sum H_i X^i
    b = int.from_bytes(b"".join(x.to_bytes(nbytes, "little") for x in reversed(G)), "little")  # sum G_j X^(n-1-j)
    prod = a * b  # coeff of X^m = sum_{i - j = m - (n-1)} H_i G_j  (all terms >= 0, no carries)
    raw = prod.to_bytes((2 * n - 1) * nbytes, "little")
    # Index m is lag k = m - (n-1): exactly the order of np.correlate(h, 1 - h, 'full').
    return [int.from_bytes(raw[m * nbytes:(m + 1) * nbytes], "little") for m in range(2 * n - 1)]


def correlation_direct(H: list[int], D: int) -> list[int]:
    n = len(H)
    G = [D - x for x in H]
    out = []
    for lag in range(-(n - 1), n):  # np.correlate: c[lag] = sum_j h[j + lag] g[j]
        s = 0
        for j in range(n):
            i = j + lag
            if 0 <= i < n:
                s += H[i] * G[j]
        out.append(s)
    return out


def certify(h: np.ndarray, *, direct: bool = False) -> dict:
    n = len(h)
    q = to_dyadic(h)
    if any(x < 0 or x > 1 for x in q):
        raise ValueError("entry outside [0, 1]")
    q, delta, idx = fix_mass(q)
    H, D = scale_to_int(q)
    corr = correlation_kronecker(H, D)
    if direct:
        if correlation_direct(H, D) != corr:
            raise AssertionError("Kronecker and direct correlations differ")
    cmax = max(corr)
    c5 = Fraction(2 * cmax, n * D * D)
    return {"n": n, "c5": c5, "mass_delta": delta, "mass_cell": idx,
            "argmax_lags": [k - (n - 1) for k, c in enumerate(corr) if c == cmax]}


def round_up(x: Fraction, digits: int) -> str:
    scale = 10 ** digits
    num = -((-x.numerator * scale) // x.denominator)  # ceil
    s = str(num).rjust(digits + 1, "0")
    return f"{s[:-digits]}.{s[-digits:]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("construction")
    ap.add_argument("--digits", type=int, default=12)
    ap.add_argument("--direct", action="store_true", help="also run the O(n^2) direct sum")
    ap.add_argument("--repeat", type=int, nargs="*", default=[], help="check np.repeat invariance for these r")
    ap.add_argument("--expect", type=float, default=None, help="fail unless |float(c5) - expect| < 5e-9")
    args = ap.parse_args()

    h = load_h(args.construction)
    ok = True
    res = certify(h, direct=args.direct)
    c5 = res["c5"]
    print(f"n_points          = {res['n']}")
    print(f"mass correction   = {float(res['mass_delta']):.3e}"
          + (f" on cell {res['mass_cell']}" if res["mass_cell"] is not None else " (none needed)"))
    print(f"active lags       = {len(res['argmax_lags'])} (first: {res['argmax_lags'][:8]})")
    print(f"C5 exact          = {c5.numerator.bit_length()}-bit / {c5.denominator.bit_length()}-bit rational")
    print(f"C5 float          = {float(c5):.15f}")
    print(f"C5 rounded up     = {round_up(c5, args.digits)}   <- certified upper bound")
    # float pipeline the evaluator uses, for comparison
    hf = np.asarray(h, dtype=np.float64)
    fl = float(np.max(np.correlate(hf, 1.0 - hf, mode="full")) * (2.0 / len(hf)))
    print(f"evaluator float   = {fl:.15f}  (diff {fl - float(c5):+.3e})")
    for r in args.repeat:
        rr = certify(np.repeat(h, r))
        same = rr["c5"] == c5
        ok &= same
        print(f"repeat r={r}: n={rr['n']} exact-equal={same}")
    if args.expect is not None:
        hit = abs(float(c5) - args.expect) < 5e-9
        ok &= hit
        print(f"expect {args.expect}: {'OK' if hit else 'MISMATCH'}")
    print("CERTIFY " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
