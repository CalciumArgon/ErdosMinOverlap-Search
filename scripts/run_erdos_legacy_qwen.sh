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
# qwen3.8-max is a reasoning model: with unbounded thinking it spends the whole
# completion budget on hidden reasoning and never emits content (the worker hangs
# until the request timeout). Bound the thinking channel via the gateway's own
# knob, forwarded through litellm extra_body by SIMPLETES_EXTRA_BODY support in
# litellm_client.py / policies/base.py.
# LATENCY (measured on the real 5.8k-char prompt, this endpoint):
#   thinking_budget=16384 -> one generation ~364s, completion ~16.9k tokens,
#                            content ~1.4k chars (a real program).
#   thinking_budget=32768 -> >900s, which is why the first formal attempt hit
#                            litellm APITimeoutError at --timeout 900.
# So: budget 16384 keeps reasoning substantive yet finishes in ~6 min, and
# --timeout 1500 gives >4x margin over the observed single-call latency.
# NOTE: SIMPLETES_FORCE_REASONING_EFFORT is intentionally NOT set — it pins
# allowed_openai_params=["reasoning_effort"], which qwen's gateway rejects.
export SIMPLETES_EXTRA_BODY='{"thinking_budget": 16384}'
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
  --max-tokens 65536 \
  --timeout 1500 \
  --include-construction \
  --log-interval 16 \
  --output-path checkpoints/erdos-legacy-qwen-r3
echo "EXITCODE=$?"
