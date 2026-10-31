#!/bin/bash
# v5 B0 polish baseline (no LLM): scripts/polish_baseline_v5.py on both warm starts,
# grids np.repeat(h0, r) for r in {1, 2, 4} (N = 2048, 4096, 8192), 6 independent processes.
# Each process: trust-region SLP with HiGHS interior point, 4 threads (as one v5 evaluation),
# time limit B0_TIME_LIMIT (default 72000 s = 20 h, about the v5 wall clock).
# Outputs: checkpoints/$RUN_NAME/<warm_start>_r<r>/{trajectory.jsonl,best_construction.json,summary.json}
set -x
REPO=/inspire/hdd/global_user/260107010002/home/SimpleTES
cd "$REPO" || exit 1
RUN_NAME=${RUN_NAME:-erdos-v5-b0}
LIMIT=${B0_TIME_LIMIT:-72000}
OUT=checkpoints/$RUN_NAME
mkdir -p "$OUT"

# The project venv is provisioned by the v4/v5 run scripts (uv sync); wait for any running
# provisioning, then only check that numpy + scipy import. No uv sync here.
TOOLS=/inspire/hdd/global_user/260107010002/.tools
if command -v flock >/dev/null 2>&1; then
    exec 9>"$TOOLS/.provision.lock"; flock 9; flock -u 9
fi
.venv/bin/python -c "import numpy, scipy; from scipy.optimize import linprog; print('numpy', numpy.__version__, 'scipy', scipy.__version__)" || exit 2

declare -A WS=(
  [nightfall]=SOTA/simpletes_payloads/01_NIGHTFALL-DevinWright_2628_construction.json
  [cristian]=SOTA/simpletes_payloads/02_CristianBudala_2623_construction.json
)
for name in nightfall cristian; do
  [ -f "${WS[$name]}" ] || { echo "missing ${WS[$name]}"; exit 2; }
done

export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
pids=()
for name in nightfall cristian; do
  for r in 1 2 4; do
    d="$OUT/${name}_r$r"
    mkdir -p "$d"
    .venv/bin/python scripts/polish_baseline_v5.py --warm-start "${WS[$name]}" --repeat "$r" \
        --time-limit "$LIMIT" --out-dir "$d" > "$d/run.log" 2>&1 &
    pids+=($!)
  done
done
rc=0
for p in "${pids[@]}"; do wait "$p" || rc=1; done
for f in "$OUT"/*/summary.json; do echo "== $f"; cat "$f"; done
echo "EXITCODE=$rc"
exit $rc
