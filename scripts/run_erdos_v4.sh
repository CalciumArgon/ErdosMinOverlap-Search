#!/bin/bash
# v4 formal run: Erdős minimum overlap, legacy dense grid, exact-score semantics.
#   BACKEND=openai_stream (default): qwen3.8-max @ apicz.boyuerichdata.com, streamed
#     chat completions, reasoning_effort=$EFFORT (default max, the gateway's top level)
#   BACKEND=anthropic: claude-opus-5-5 (Messages API, streamed, adaptive thinking)
#   rpucg, 4 chains = 2 explore (no warm start) + 2 exploit (global-best warm start)
#   API-health classification -> <instance>/api_health.jsonl, [API-HEALTH] log lines
# Runs inside a CPU HPC job (HPC-可上网区资源-2) or the prep notebook.
#
# Env overrides:
#   RUN_NAME   output dir under checkpoints/ (default erdos-v4)
#   RESUME     checkpoint path to resume from (continues a run past the 24 h job limit)
#   BACKEND    openai_stream (default, qwen) | anthropic (claude; zl.yyapi.cloud cuts streams at ~640 s)
#   EFFORT     generation effort (default max for qwen, high for claude)
#   GEN_TIMEOUT / FIRST_CHUNK_TIMEOUT / STALL_TIMEOUT   seconds (calibrated by smoke_v4.sh)
#   MAX_GENERATIONS, GEN_CONCURRENCY
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
# anthropic SDK for --llm-backend anthropic. Installed after sync (not in uv.lock):
# 0.125.0 is the last 0.x line, which still uses httpx (shared with litellm).
# Only the pypi_proxy mirror carries anthropic; set per command because an exported
# UV_DEFAULT_INDEX (pypi-proxy, used by uv sync) takes precedence over --index-url.
UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi_proxy/simple/ uv pip install --python .venv/bin/python "anthropic==0.125.0"

# --- secrets (never echoed) ---
# simpletes.env defines OPENAI_API_KEY + SIMPLELLM_BASE_URL (qwen) and
# ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL (claude). Both clients read the key
# from the environment, so it never appears in argv.
set +x
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
set -x
BACKEND=${BACKEND:-openai_stream}
if [ "$BACKEND" = anthropic ]; then
    if [ -z "$ANTHROPIC_API_KEY" ] || [ -z "$ANTHROPIC_BASE_URL" ]; then
        echo "missing ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL in simpletes.env"; exit 2
    fi
    LLM_ARGS=(--llm-backend anthropic --model claude-opus-5-5 --api-base "$ANTHROPIC_BASE_URL"
        --reasoning-effort "${EFFORT:-high}" --max-tokens 128000)
else
    if [ -z "$OPENAI_API_KEY" ] || [ -z "$SIMPLELLM_BASE_URL" ]; then
        echo "missing OPENAI_API_KEY / SIMPLELLM_BASE_URL in simpletes.env"; exit 2
    fi
    # max_tokens 131072 is the gateway ceiling; reasoning tokens count against it.
    LLM_ARGS=(--llm-backend openai_stream --model qwen3.8-max --api-base "$SIMPLELLM_BASE_URL"
        --reasoning-effort "${EFFORT:-max}" --max-tokens 131072)
fi

# --- evaluation ---
export EVALUATOR_CONCURRENT_PROCESSES=8
export EVALUATOR_TIMEOUT_SECONDS=3000
REF=/inspire/hdd/global_user/260107010002/home/SimpleTES/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=$REF
export ERDOS_REFERENCE_PATH=$REF
export ERDOS_REFERENCE_C5=0.38086768
# reflection: two-line summary, own effort (--reflection-effort) and timeout
export SIMPLETES_REFLECTION_TIMEOUT=1800

RUN_NAME=${RUN_NAME:-erdos-v4}
RESUME_ARGS=()
if [ -n "$RESUME" ]; then RESUME_ARGS=(--resume "$RESUME"); fi

.venv/bin/python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator_legacy.py \
  --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  "${LLM_ARGS[@]}" \
  --reflection-effort medium \
  --timeout "${GEN_TIMEOUT:-1800}" \
  --first-chunk-timeout "${FIRST_CHUNK_TIMEOUT:-300}" \
  --stall-timeout "${STALL_TIMEOUT:-300}" \
  --selector rpucg \
  --num-chains 4 \
  --explore-chains 2 \
  --shared-construction-scope global \
  --k-candidates 4 \
  --max-generations "${MAX_GENERATIONS:-80}" \
  --gen-concurrency "${GEN_CONCURRENCY:-16}" \
  --eval-concurrency 8 \
  --eval-timeout 3300 \
  --init-eval-repeats 2 \
  --include-construction \
  --save-llm-io \
  --log-interval 4 \
  --output-path "checkpoints/$RUN_NAME" \
  "${RESUME_ARGS[@]}"
rc=$?
echo "EXITCODE=$rc"   # 2 = preflight failed (API never started), 3 = API_FATAL during run
exit $rc
