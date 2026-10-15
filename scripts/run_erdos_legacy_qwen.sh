#!/bin/bash
# Legacy dense-grid erdos run with qwen3.8-max, rpucg, meta-search reflection.
# Studies the two-stage relaxed paradigm (value relaxation + finite grid) with an
# instruction/reflection that make the LLM judge score TRUSTWORTHINESS rather than
# optimize a prescribed solution shape.
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
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi-proxy/simple/

uv python install 3.12
uv sync

# --- secrets + run config ---
# simpletes.env must define OPENAI_API_KEY (litellm auto-reads it for openai/ models)
# and SIMPLELLM_BASE_URL=https://apicz.boyuerichdata.com/v1
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
export EVALUATOR_CONCURRENT_PROCESSES=4
# NOTE: SIMPLETES_FORCE_REASONING_EFFORT is intentionally NOT set. It pins
# allowed_openai_params=["reasoning_effort"] (litellm_client.py:240-243), which
# 4xx's if the qwen gateway rejects that field. drop_params=True handles the rest.
# Re-enable only if a smoke test shows qwen burning the token budget on hidden
# thinking (empty content).
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=/inspire/hdd/global_user/260107010002/home/SimpleTES/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json

.venv/bin/python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator_legacy.py \
  --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model openai/qwen3.8-max \
  --api-base "$SIMPLELLM_BASE_URL" \
  --selector rpucg \
  --num-chains 4 \
  --k-candidates 4 \
  --max-generations 40 \
  --gen-concurrency 4 \
  --eval-concurrency 4 \
  --init-eval-repeats 2 \
  --max-tokens 131072 \
  --include-construction \
  --log-interval 16 \
  --output-path checkpoints/erdos-legacy-qwen-r3
echo "EXITCODE=$?"
