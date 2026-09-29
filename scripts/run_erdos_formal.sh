#!/bin/bash
# Formal erdos A类 run: deepseek-v4-pro (thinking, high effort), rpucg, budget 40.
# Runs inside a CPU HPC job (HPC-可上网区资源-2) or the prep notebook.
set -x
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1

# --- provision uv + Python 3.12 on shared disk (one-time, cached) ---
TOOLS=/inspire/hdd/global_user/260107010002/.tools
if [ ! -x "$TOOLS/uv" ]; then
    mkdir -p "$TOOLS"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS" sh
fi
export PATH="$TOOLS:$PATH"
export UV_PYTHON_INSTALL_DIR="$TOOLS/uv-python"
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi_proxy/simple/

uv python install 3.12
uv sync

# --- secrets + run config ---
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
export EVALUATOR_CONCURRENT_PROCESSES=8
export SIMPLETES_FORCE_REASONING_EFFORT=high   # xhigh: ~2x thinking tokens and wall time
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=/inspire/hdd/global_user/260107010002/home/SimpleTES/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json

.venv/bin/python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model deepseek/deepseek-v4-pro \
  --selector rpucg \
  --num-chains 4 \
  --k-candidates 4 \
  --max-generations 40 \
  --gen-concurrency 4 \
  --eval-concurrency 8 \
  --init-eval-repeats 2 \
  --max-tokens 131072 \
  --include-construction \
  --log-interval 16 \
  --output-path checkpoints/erdos-A-v4pro-high
echo "EXITCODE=$?"
