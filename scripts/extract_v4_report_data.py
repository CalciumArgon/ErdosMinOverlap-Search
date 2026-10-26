#!/usr/bin/env python
"""Collect everything the v4 report needs from one run instance into a single JSON (run on qz).

Usage: .venv/bin/python scripts/extract_v4_report_data.py <instance_dir> <out.json> [--no-certify]

Contents:
- config / metadata of the newest db_state
- one row per node: chain, role, step in chain, parents, warm-start source, all
  evaluator metrics, token usage, reflection text, failure flag
- every api_health row (generation / reflection / probe timing, tokens, class)
- evaluation / generation failures
- global-best timeline in evaluation-completion order
- for the root reference and every global-best breakthrough: exact certified
  bound (scripts/certify_erdos_grid.certify, rational arithmetic), active lags,
  near-active lag counts, and downsampled h / correlation curves for plots

No API key or prompt secret is read; llm_input / llm_output are summarised by length only.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from fractions import Fraction

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from certify_erdos_grid import certify, round_up  # noqa: E402

REF_C5_CERT = "0.380867675828"   # certified bound of the warm-start reference (smoke stage b)
MAX_PLOT_POINTS = 1200


def load_h_snapshot(path: str) -> np.ndarray:
    s = json.load(open(path, encoding="utf-8"))
    item = s["items"][0] if isinstance(s, dict) and "items" in s else s
    data = item["data"] if isinstance(item, dict) else item
    return np.asarray(data, dtype=np.float64)


def corr_float(h: np.ndarray) -> np.ndarray:
    """c_k for k = -(N-1)..N-1 (np.correlate(h, 1-h, 'full') order) via FFT; plots only."""
    n = len(h)
    size = 1 << (2 * n - 1).bit_length()
    fa = np.fft.rfft(h, size)
    fb = np.fft.rfft((1.0 - h)[::-1], size)
    return np.fft.irfft(fa * fb, size)[: 2 * n - 1]


def downsample(x: np.ndarray, m: int, how: str) -> list[float]:
    if len(x) <= m:
        return [float(v) for v in x]
    edges = np.linspace(0, len(x), m + 1).astype(int)
    f = np.max if how == "max" else np.mean
    return [float(f(x[a:b])) for a, b in zip(edges[:-1], edges[1:]) if b > a]


def diff_vs_reference(h: np.ndarray, ref: np.ndarray) -> dict:
    """h - (closest symmetry image of ref), both on the common refinement grid.

    The best solutions are near-identical to the reference, so the curves overlap
    in a plot; their difference shows where the search actually changed h.
    """
    n, m = len(h), len(ref)
    lcm = n * m // np.gcd(n, m)
    hh, rr = np.repeat(h, lcm // n), np.repeat(ref, lcm // m)
    images = {"identity": rr, "reflect": rr[::-1], "complement": 1 - rr, "reflect+complement": (1 - rr)[::-1]}
    name, img = min(images.items(), key=lambda kv: float(np.abs(hh - kv[1]).sum()))
    d = hh - img
    return {"image": name, "l1": float(np.abs(d).sum() * 2.0 / lcm), "max_abs": float(np.abs(d).max()),
            "plot": downsample(d, MAX_PLOT_POINTS, "mean"),
            "plot_absmax": downsample(np.abs(d), MAX_PLOT_POINTS, "max")}


def construction_profile(path: str, do_certify: bool, ref: np.ndarray | None = None) -> dict:
    h = load_h_snapshot(path)
    n = len(h)
    dx = 2.0 / n
    c = corr_float(h) * dx
    cmax = float(c.max())
    out = {
        "n_points": n,
        "c5_float": cmax,
        "near_active": {f"1e-{p}": int(np.sum(c >= cmax - 10.0 ** (-p))) for p in (6, 8, 10, 12)},
        "frac_cells_strictly_inside": float(np.mean((h > 1e-9) & (h < 1 - 1e-9))),
        "h_plot": downsample(h, MAX_PLOT_POINTS, "mean"),
        "corr_plot_shift": [float(s) for s in np.linspace(-2 + dx, 2 - dx, min(MAX_PLOT_POINTS, len(c)))],
        "corr_plot": downsample(c, MAX_PLOT_POINTS, "max"),
    }
    if ref is not None:
        out["diff_vs_reference"] = diff_vs_reference(h, ref)
    k = int(np.argmax(c))
    w = max(1, n // 40)  # zoom window around the peak, shown at full resolution where small
    lo, hi = max(0, k - w), min(len(c), k + w + 1)
    out["peak_shift"] = (k - (n - 1)) * dx
    out["peak_zoom_shift"] = [float((j - (n - 1)) * dx) for j in range(lo, hi)][:: max(1, (hi - lo) // 400)]
    out["peak_zoom_corr"] = [float(v) for v in c[lo:hi]][:: max(1, (hi - lo) // 400)]
    if do_certify:
        cert = certify(h)
        out["cert_upper_bound"] = round_up(cert["c5"], 12)
        out["cert_c5_float"] = float(cert["c5"])
        out["cert_argmax_lags"] = cert["argmax_lags"][:20]
        out["cert_n_active"] = len(cert["argmax_lags"])
        out["cert_mass_delta"] = float(cert["mass_delta"])
        out["cert_vs_reference"] = float(cert["c5"] - Fraction(REF_C5_CERT))
    return out


def main() -> int:
    inst, out_path = sys.argv[1], sys.argv[2]
    do_certify = "--no-certify" not in sys.argv[3:]
    d = sorted(glob.glob(os.path.join(inst, "db_state_*")))[-1]
    cfg = json.load(open(os.path.join(d, "config.json")))
    meta = json.load(open(os.path.join(d, "metadata.json")))
    nodes = json.load(open(os.path.join(d, "nodes.json")))
    failures = json.load(open(os.path.join(d, "failure.json")))
    # older config.json snapshots do not store explore_chains; v4 runs use 2
    explore = int(cfg.get("explore_chains") if cfg.get("explore_chains") is not None
                  else os.environ.get("EXPLORE_CHAINS", 2))

    rows = []
    for n in sorted(nodes, key=lambda x: x.get("created_at") or ""):
        m = n.get("metrics") if isinstance(n.get("metrics"), dict) else {}
        ch = n.get("chain_idx")
        rows.append({
            "id": n["id"],
            "chain": ch,
            "role": "root" if ch is None else ("explore" if ch < explore else "exploit"),
            "gen_id": n.get("gen_id"),
            "parents": n.get("parent_ids") or [],
            "warm_source": n.get("shared_construction_id"),
            "created_at": n.get("created_at"),
            "status": n.get("status"),
            "score": n.get("score"),
            "metrics": m,
            "token_usage": n.get("token_usage"),
            "reflection": (n.get("reflection") or "")[:1200],
            "code_chars": len(n.get("code") or ""),
            "llm_output_chars": len(n.get("llm_output") or ""),
        })
    # step index inside each chain = rank of its gen_id (batches are sequential per chain)
    for ch in {r["chain"] for r in rows if r["chain"] is not None}:
        gens = sorted({r["gen_id"] for r in rows if r["chain"] == ch and r["gen_id"] is not None})
        for r in rows:
            if r["chain"] == ch and r["gen_id"] is not None:
                r["step"] = gens.index(r["gen_id"]) + 1

    health = [json.loads(line) for line in open(os.path.join(inst, "api_health.jsonl"), encoding="utf-8")]
    fails = [{"type": f.get("type"), "reason": str(f.get("reason"))[:300], "health": f.get("health")}
             for f in failures]

    # global-best timeline (lower c5 is better; only valid evaluated nodes)
    timeline, best = [], None
    for r in rows:
        c5 = r["metrics"].get("c5")
        if c5 is None or not r["metrics"].get("validity"):
            continue
        if best is None or c5 < best - 1e-15:
            best = c5
            timeline.append({"id": r["id"], "chain": r["chain"], "role": r["role"], "step": r.get("step"),
                             "created_at": r["created_at"], "c5": c5})

    shared_dir = os.path.join(inst, "shared_constructions")
    root = os.path.join(shared_dir, timeline[0]["id"] + ".json") if timeline else None
    ref = load_h_snapshot(root) if root and os.path.exists(root) else None
    profiles = {}
    for t in timeline:
        p = os.path.join(shared_dir, t["id"] + ".json")
        if os.path.exists(p):
            print("profile", t["id"][:8], flush=True)
            profiles[t["id"]] = construction_profile(p, do_certify, ref)

    data = {"instance": os.path.basename(inst), "db_state": os.path.basename(d), "config": cfg,
            "metadata": meta, "nodes": rows, "health": health, "failures": fails,
            "timeline": timeline, "profiles": profiles, "reference_cert": REF_C5_CERT}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print("wrote", out_path, os.path.getsize(out_path), "bytes;", len(rows), "nodes,",
          len(health), "health rows,", len(timeline), "breakthroughs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
