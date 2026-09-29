#!/usr/bin/env python
"""Standalone verification of the erdos A类 exact-rational kernel (Linux only).

Run from the repo root on a Linux machine with the project venv:
    .venv/bin/python scripts/verify_erdos_exact_kernel.py

Checks:
  1. Sweep vs independent direct evaluation: for random valid specs, the sweep's
     kink values equal direct O(m^2) Fraction evaluation at every kink (exact
     equality), and best == max over kinks.
  2. Round-up/down certificate: fraction_round_down(best) <= best <= fraction_round_up(best)
     (rational comparisons), and U is a float that upper-bounds float(best).
  3. Analytic cases:
     - h ≡ 1/2 (m=1): M(s) = (1/4)(2-|s|), best == 1/2 at s=0.
     - breaks [0,1,2], first value v: C5 = max(2v(1-v), v^2, (1-v)^2);
       v = 1/3 -> best == 4/9.
  4. Float cross-check: rasterize random specs at n=8192; the discrete
     np.correlate score must be close to float(best) and not exceed U by more
     than discretization tolerance.
  5. Property check: 1000 random exact rational shifts never beat the kink max.
  6. Legacy regression: verify_c5_solution on h = 0.5*ones(100), n=100 -> 0.5.

Exits 0 on full pass, 1 on any failure.
"""

import importlib.util
import random
import sys
from fractions import Fraction

import numpy as np

EVALUATOR_PATH = "datasets/erdos/erdos_min_overlap/evaluator.py"


def load_evaluator():
    spec = importlib.util.spec_from_file_location("erdos_evaluator", EVALUATOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E = load_evaluator()
FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def random_spec(rng, max_m=12):
    """Random valid spec with varied denominators (powers of two up to 2^20 or small primes)."""
    m = rng.randint(1, max_m)
    denom = rng.choice([2, 3, 4, 5, 7, 8, 16, 64, 256, 4096, 1 << 20])
    if 2 * denom - 1 < m:  # need m distinct interior break candidates
        denom = rng.choice([16, 64, 256, 4096, 1 << 20])
    candidates = set()
    while len(candidates) < m:
        candidates.add(Fraction(rng.randint(1, 2 * denom - 1), denom))
    breaks = [Fraction(0, 1)] + sorted(candidates) + [Fraction(2, 1)]
    values = [Fraction(rng.randint(0, 1)) if rng.random() < 0.6 else
              Fraction(rng.randint(0, 20), rng.choice([4, 8, 16, 64, 1024, 1 << 20]))
              for _ in range(m - 1)]
    try:
        v_last = E.compute_last_value(breaks, values)
    except E.SpecError:
        # values = 1/2 always balance: V = (w_last/2)/w_last = 1/2
        values = [Fraction(1, 2)] * (m - 1)
        v_last = E.compute_last_value(breaks, values)
    return breaks, values + [v_last]


def test_sweep_consistency(rng, n_specs=50):
    for i in range(n_specs):
        breaks, v_all = random_spec(rng)
        sweep = E.exact_sweep(breaks, v_all)
        direct_max = Fraction(-1, 1)
        for s, M_rec, _, _ in sweep["records"]:
            direct = E.M_at(breaks, v_all, s)
            if direct != M_rec:
                check(f"sweep-vs-direct spec#{i} s={s}",
                      False, f"sweep={M_rec} direct={direct}")
                return
            direct_max = max(direct_max, direct)
        if direct_max != sweep["best"]:
            check(f"sweep-best spec#{i}", False,
                  f"best={sweep['best']} direct_max={direct_max}")
            return
        for s in sweep["argmax_shifts"]:
            if E.M_at(breaks, v_all, s) != sweep["best"]:
                check(f"argmax spec#{i}", False, f"argmax shift {s} not max")
                return
    check(f"sweep-vs-direct ({n_specs} random specs)", True)


def test_certificate(rng, n_specs=50):
    for i in range(n_specs):
        breaks, v_all = random_spec(rng)
        best = E.exact_sweep(breaks, v_all)["best"]
        lo, hi = E.fraction_round_down(best), E.fraction_round_up(best)
        if not (Fraction(lo) <= best <= Fraction(hi)):
            check(f"certificate bracket spec#{i}", False,
                  f"best={best} lo={lo} hi={hi}")
            return
        if not (lo <= float(best) <= hi):
            check(f"certificate float bracket spec#{i}", False,
                  f"float(best)={float(best)} lo={lo} hi={hi}")
            return
    check(f"certificate bracket ({n_specs} random specs)", True)


def test_analytic_constant_half():
    breaks = [Fraction(0, 1), Fraction(2, 1)]
    values = []
    v_last = E.compute_last_value(breaks, values)
    sweep = E.exact_sweep(breaks, [v_last])
    check("analytic h≡1/2: v_last == 1/2", v_last == Fraction(1, 2), f"got {v_last}")
    check("analytic h≡1/2: best == 1/2", sweep["best"] == Fraction(1, 2),
          f"got {sweep['best']}")
    check("analytic h≡1/2: argmax at s=0",
          Fraction(0, 1) in sweep["argmax_shifts"], f"got {sweep['argmax_shifts']}")
    U = E.fraction_round_up(sweep["best"])
    check("analytic h≡1/2: U == 0.5", U == 0.5, f"got {U}")


def test_analytic_two_segments():
    breaks = [Fraction(0, 1), Fraction(1, 1), Fraction(2, 1)]
    values = [Fraction(1, 3)]
    v_last = E.compute_last_value(breaks, values)
    sweep = E.exact_sweep(breaks, values + [v_last])
    check("analytic 2-seg: v_last == 2/3", v_last == Fraction(2, 3), f"got {v_last}")
    # C5 = max(2v(1-v), v^2, (1-v)^2) = max(4/9, 1/9, 4/9) = 4/9
    check("analytic 2-seg: best == 4/9", sweep["best"] == Fraction(4, 9),
          f"got {sweep['best']}")


def test_float_cross_check(rng, n_specs=20, n=8192):
    for i in range(n_specs):
        breaks, v_all = random_spec(rng)
        best = E.exact_sweep(breaks, v_all)["best"]
        h = np.zeros(n)
        x = (np.arange(n) + 0.5) * 2.0 / n
        for p in range(len(v_all)):
            h[(x >= float(breaks[p])) & (x < float(breaks[p + 1]))] = float(v_all[p])
        disc = float(np.max(np.correlate(h, 1.0 - h, mode="full")) * 2.0 / n)
        U = E.fraction_round_up(best)
        if abs(disc - float(best)) > 2e-2:
            check(f"float cross-check spec#{i}", False,
                  f"discrete={disc:.6f} exact={float(best):.6f}")
            return
        if disc > U + 1e-12:
            check(f"float cross-check upper-bound spec#{i}", False,
                  f"discrete={disc:.12f} U={U:.12f}")
            return
    check(f"float cross-check ({n_specs} specs, n={n})", True)


def test_property_kink_max(rng, n_specs=20, n_shifts=1000):
    for i in range(n_specs):
        breaks, v_all = random_spec(rng)
        best = E.exact_sweep(breaks, v_all)["best"]
        for _ in range(n_shifts):
            s = Fraction(rng.randint(-2 * 1024, 2 * 1024), 1024)
            if E.M_at(breaks, v_all, s) > best:
                check(f"kink-max property spec#{i}", False,
                      f"s={s} M={E.M_at(breaks, v_all, s)} > best={best}")
                return
    check(f"kink-max property ({n_specs} specs × {n_shifts} shifts)", True)


def test_legacy_regression():
    h = np.ones(100) * 0.5
    c5 = E.verify_c5_solution(h, 0.5, 100)
    check("legacy regression: c5 == 0.5", abs(c5 - 0.5) < 1e-12, f"got {c5}")
    try:
        E.verify_c5_solution(h, 0.6, 100)
        check("legacy regression: c5 mismatch rejected", False, "no error raised")
    except ValueError:
        check("legacy regression: c5 mismatch rejected", True)


def test_spec_errors():
    try:
        E.validate_spec(([0.0, 1.0, 2.0], [Fraction(1, 2)]))
        check("spec error: float breaks rejected", False, "no error raised")
    except E.SpecError as e:
        check("spec error: float breaks rejected", "float" in str(e), f"got {e}")
    try:
        E.validate_spec(([Fraction(0), Fraction(1), Fraction(2)], [Fraction(2, 1)]))
        check("spec error: value out of range rejected", False, "no error raised")
    except E.SpecError as e:
        check("spec error: value out of range rejected", "range" in str(e), f"got {e}")
    try:
        E.validate_spec(([Fraction(0), Fraction(2)], [Fraction(1, 2)]))
        check("spec error: values_length_mismatch for m=1", False, "no error raised")
    except E.SpecError as e:
        check("spec error: values_length_mismatch for m=1", "mismatch" in str(e), f"got {e}")


def test_diagnostics(rng, n_specs=10):
    for i in range(n_specs):
        breaks, v_all = random_spec(rng)
        values = v_all[:-1]
        sweep = E.exact_sweep(breaks, v_all)
        diag = E.build_diagnostics(breaks, values, v_all, sweep)
        for key in ("n_segments", "n_kinks", "equioscillation_count",
                    "active_shifts", "active_sensitivity"):
            if key not in diag:
                check(f"diagnostics keys spec#{i}", False, f"missing {key}")
                return
        assert len(diag["active_sensitivity"]) <= 200
    check(f"diagnostics sanity ({n_specs} specs)", True)


def main():
    if sys.platform == "win32":
        print("This verification script is Linux-only (the evaluator imports `resource`).")
        print("Run it on the cluster: .venv/bin/python scripts/verify_erdos_exact_kernel.py")
        sys.exit(0)
    rng = random.Random(12345)
    test_analytic_constant_half()
    test_analytic_two_segments()
    test_sweep_consistency(rng)
    test_certificate(rng)
    test_float_cross_check(rng)
    test_property_kink_max(rng)
    test_legacy_regression()
    test_spec_errors()
    test_diagnostics(rng)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
