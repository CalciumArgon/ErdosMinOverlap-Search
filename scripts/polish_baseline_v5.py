#!/usr/bin/env python
"""B0 polish baseline for v5: a generic local optimizer, no LLM.

Question it answers: how much does a standard numerical method improve a warm start on
its own, with a CPU budget at least as large as one v5 candidate (3000 s) and up to the
whole v5 wall clock (~20 h)? A v5 gain only counts as search progress if it beats this.

Method: trust-region sequential linear programming (SLP) on the fixed grid np.repeat(h0, r).
  minimize C(h) = (2/n) max_k c_k(h),  c_k(h) = sum_t h[t+k] (1 - h[t]),
  over 0 <= h <= 1, sum(h) = n/2.
Each iteration linearizes the shifts close to the max and solves, with HiGHS,
  min_{d, t} t  s.t.  C_k(h) + grad C_k(h) . d <= C(h) + t  (k near the max),
                     sum(d) = 0,  -h <= d <= 1-h,  |d|_inf <= rho.
A step is accepted only if the TRUE C(h+d), computed exactly like the evaluator
(np.correlate in float64, sum(h) == n/2 exactly), strictly decreases. rho follows the
usual actual/predicted ratio rule. The final best array is certified in exact rational
arithmetic with scripts/certify_erdos_grid.py.

Usage (repo root, project venv):
    .venv/bin/python scripts/polish_baseline_v5.py --warm-start PAYLOAD.json --repeat 2 \
        --time-limit 72000 --out-dir checkpoints/erdos-v5-b0/nightfall_r2
Outputs in --out-dir: trajectory.jsonl, best_construction.json, summary.json.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import types

import numpy as np
from scipy.optimize import linprog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKS = (3000, 6 * 3600)  # one v5 eval budget; 6 h


def load_helpers():
    """simpletes.construction (without simpletes/__init__) and certify_erdos_grid."""
    pkg = types.ModuleType("simpletes")
    pkg.__path__ = [os.path.join(ROOT, "simpletes")]
    sys.modules.setdefault("simpletes", pkg)
    sys.path.insert(0, ROOT)
    from simpletes.construction import decode_construction, encode_construction, write_payload
    spec = importlib.util.spec_from_file_location(
        "certify_erdos_grid", os.path.join(ROOT, "scripts", "certify_erdos_grid.py"))
    cert = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cert)
    return decode_construction, encode_construction, write_payload, cert


def true_c5(h):
    """Exactly the evaluator's float pipeline (evaluator_legacy.verify_c5_solution)."""
    n = len(h)
    corr = np.correlate(h, 1.0 - h, mode="full") * (2.0 / n)
    return float(np.max(corr)), corr


def fix_mass(h):
    """Clip to [0, 1] and make sum(h) == n/2 hold exactly in float64 (as the evaluator checks)."""
    h = np.clip(h, 0.0, 1.0)
    target = len(h) / 2.0
    for _ in range(8):
        r = target - float(np.sum(h))
        if r == 0.0:
            return h
        room = (1.0 - h) if r > 0 else h
        i = int(np.argmax(room))
        if room[i] < abs(r):
            return None
        h[i] = min(1.0, max(0.0, h[i] + r))
    return h if float(np.sum(h)) == target else None


def grad_rows(h, lags):
    """Rows (n/2) * dC_k/dh = dc_k/dh for the given lags (dense, len(lags) x n)."""
    n = len(h)
    g = 1.0 - h
    G = np.zeros((len(lags), n))
    for r, k in enumerate(lags):
        if k >= 0:
            G[r, k:] += g[: n - k]       # d/dh[j] of h[j]   (j = t + k)
            G[r, : n - k] -= h[k:]       # d/dh[j] of -h[j]  (j = t)
        else:
            m = -k
            G[r, : n - m] += g[m:]
            G[r, m:] -= h[: n - m]
    return G


def lp_step(h, corr, rho, max_rows, lp_time):
    """Solve the trust-region LP. Returns (d, predicted decrease in C, rows, status);
    d is None when HiGHS did not finish (status 1 = time limit)."""
    n = len(h)
    M = float(corr.max())
    # A lag can only overtake the max within the trust region if its gap is < ~4 rho + 4 rho^2.
    delta = 4.0 * rho + 4.0 * rho * rho
    cand = np.nonzero(corr >= M - delta)[0]
    if len(cand) > max_rows:
        cand = cand[np.argsort(-corr[cand])[:max_rows]]
    lags = cand - (n - 1)
    # Variables: u = d / rho (n entries), tau. In scaled units (c = (n/2) C):
    #   G u - tau/rho * ... -> written as  G_k . u - tau <= (n/2)(M - C_k) / rho
    A = np.empty((len(cand), n + 1))
    A[:, :n] = grad_rows(h, lags)
    A[:, n] = -1.0
    b = (n / 2.0) * (M - corr[cand]) / rho
    A_eq = np.ones((1, n + 1))
    A_eq[0, n] = 0.0
    lo = np.maximum(-1.0, -h / rho)
    hi = np.minimum(1.0, (1.0 - h) / rho)
    bounds = np.column_stack([np.append(lo, -np.inf), np.append(hi, np.inf)])
    c = np.zeros(n + 1)
    c[n] = 1.0
    # Interior point: on NIGHTFALL (n=2048, 1395 rows) 34.5 s vs 137 s for dual simplex,
    # same step (predicted 2.4301e-9, actual 2.4300e-9).
    res = linprog(c, A_ub=A, b_ub=b, A_eq=A_eq, b_eq=[0.0], bounds=bounds, method="highs-ipm",
                  options={"time_limit": float(lp_time)})
    if res.status != 0 or res.x is None:
        return None, 0.0, len(cand), int(res.status)   # status 1 = time limit
    tau = float(res.x[n])
    pred = -tau * rho * 2.0 / n          # predicted decrease of C (first order)
    return res.x[:n] * rho, pred, len(cand), 0


def polish(h0, time_limit, max_rows, rho0, rho_min, log, save, t_start):
    h = fix_mass(h0.copy())
    if h is None:
        raise ValueError("cannot make sum(h) == n/2 exactly for the start array")
    best, corr = true_c5(h)
    start = best
    rho, it, acc = rho0, 0, 0
    hist = [(0.0, best)]  # (completion time of an accepted step, best after it)
    last_save = time.time()
    lp_time = 3600.0
    while True:
        el = time.time() - t_start
        if el >= time_limit:
            reason = "time_limit"
            break
        if rho < rho_min:
            reason = "converged (rho < rho_min)"
            break
        it += 1
        t0 = time.time()
        d, pred, rows, st = lp_step(h, corr, rho, max_rows, min(lp_time, max(10.0, time_limit - el)))
        t_lp = time.time() - t0
        rec = {"t": round(time.time() - t_start, 1), "it": it, "best": best, "rho": rho,
               "rows": rows, "lp_s": round(t_lp, 2)}
        if d is None and st == 1:
            # LP too expensive for its time budget: a cost problem, not a step-size one.
            rec["status"] = "lp_timeout"
            lp_time *= 2.0
            log(rec)
            continue
        if d is None:
            rec.update(status="lp_failed", lp_status=st)
            rho *= 0.25
            log(rec)
            continue
        if pred <= 1e-16:
            rec.update(status="no_descent", pred=pred)
            rho *= 0.25
            log(rec)
            continue
        hn = fix_mass(h + d)
        if hn is None:
            rec["status"] = "mass_fix_failed"
            rho *= 0.25
            log(rec)
            continue
        cn, corrn = true_c5(hn)
        actual = best - cn
        ratio = actual / pred if pred > 0 else 0.0
        rec.update(pred=pred, actual=actual, ratio=round(ratio, 4))
        if cn < best:
            h, best, corr = hn, cn, corrn
            acc += 1
            hist.append((time.time() - t_start, best))
            rec["status"] = "accepted"
            if ratio > 0.75:
                rho = min(0.25, rho * 2.0)
            elif ratio < 0.25:
                rho *= 0.5
        else:
            rec["status"] = "rejected"
            rho *= 0.25
        log(rec)
        if time.time() - last_save > 600:
            save(h, best)
            last_save = time.time()
    # Best among steps that had COMPLETED by each mark (a step straddling the mark does not
    # count). None if the run stopped before the mark for a reason other than convergence.
    el = time.time() - t_start
    marks = {m: (min(b for t, b in hist if t <= m) if (el >= m or reason.startswith("converged"))
                 else None) for m in MARKS}
    save(h, best)
    return h, start, best, it, acc, marks, reason


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warm-start", required=True)
    ap.add_argument("--repeat", type=int, default=1, help="optimize on np.repeat(h0, r)")
    ap.add_argument("--time-limit", type=float, default=72000.0)
    ap.add_argument("--max-rows", type=int, default=6000)
    ap.add_argument("--rho0", type=float, default=1e-6)
    ap.add_argument("--rho-min", type=float, default=1e-13)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    decode, encode, write_payload, cert = load_helpers()
    with open(args.warm_start, encoding="utf-8") as f:
        val = decode(json.load(f))
    h0 = np.repeat(np.asarray(val[0], dtype=np.float64).reshape(-1), args.repeat)
    os.makedirs(args.out_dir, exist_ok=True)
    traj = open(os.path.join(args.out_dir, "trajectory.jsonl"), "w", encoding="utf-8")

    def log(rec):
        traj.write(json.dumps(rec) + "\n")
        traj.flush()

    def save(h, c):
        write_payload(os.path.join(args.out_dir, "best_construction.json"),
                      encode((h, float(c), len(h))))

    t_start = time.time()
    h, start, best, it, acc, marks, reason = polish(
        h0, args.time_limit, args.max_rows, args.rho0, args.rho_min, log, save, t_start)
    elapsed = time.time() - t_start
    traj.close()

    def exact(arr):
        r = cert.certify(arr)
        return r["c5"], cert.round_up(r["c5"], 15)

    c0, c0_s = exact(h0)
    c1, c1_s = exact(h)
    summary = {
        "warm_start": os.path.relpath(args.warm_start, ROOT).replace("\\", "/"),
        "repeat": args.repeat, "n": int(len(h)), "method": "trust-region SLP (HiGHS interior point)",
        "time_limit_s": args.time_limit, "elapsed_s": round(elapsed, 1), "stop_reason": reason,
        "iterations": it, "accepted": acc,
        "start_float": start, "best_float": best,
        "best_float_at_3000s": marks[3000], "best_float_at_6h": marks[6 * 3600],
        "start_exact_round_up": c0_s, "best_exact_round_up": c1_s,
        "gain_exact": float(c0 - c1),
    }
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
