#!/bin/bash
# v5 formal run: same harness as v4 (run_erdos_v4.sh), warm start = a current SOTA construction.
#   WARM_START=nightfall  EinsteinArena #2628 NIGHTFALL-DevinWright, N=2048, C5 0.380856404354668
#   WARM_START=cristian   EinsteinArena #2623 CristianBudala,        N=2048, C5 0.380856588297483
#   4 chains, all exploit (explore_chains=0), global-best shared construction
#   k=4 candidates per step, 240 generations -> 60 prompts = 15 sequential steps per chain
# Differences from v4 are listed in plan/version5.md ("与 v4 的差异").
#
# Env overrides:
#   WARM_START   nightfall | cristian (required)
#   RUN_NAME     output dir under checkpoints/ (default erdos-v5-$WARM_START)
#   RESUME       checkpoint path to resume from (continues a run past the job time limit)
#   THINKING_BUDGET (default 122880), GEN_TIMEOUT / FIRST_CHUNK_TIMEOUT / STALL_TIMEOUT
#   MAX_GENERATIONS (default 240), K_CANDIDATES (default 4)
#   GEN_CONCURRENCY (default 16 = 4 chains x k), EVAL_CONCURRENCY (default 16)
set -x
REPO=/inspire/hdd/global_user/260107010002/home/SimpleTES
cd "$REPO" || exit 1

# --- warm start (payloads are gitignored under SOTA/; checked by sha256) ---
case "$WARM_START" in
  nightfall)
    WS_PATH=$REPO/SOTA/simpletes_payloads/01_NIGHTFALL-DevinWright_2628_construction.json
    WS_SHA=d885d0d63102e55a49ddda61fc4c12b5834209a2b1509bde348c155e5654df37
    WS_C5=0.3808564043546677 ;;
  cristian)
    WS_PATH=$REPO/SOTA/simpletes_payloads/02_CristianBudala_2623_construction.json
    WS_SHA=e9a545f3a48171510c8c994d143da8c6a2b98ab21c0896337faa412454eae323
    WS_C5=0.38085658829748237 ;;
  *) echo "WARM_START must be nightfall or cristian (got '$WARM_START')"; exit 2 ;;
esac
echo "$WS_SHA  $WS_PATH" | sha256sum -c - || { echo "warm-start payload missing or changed"; exit 2; }

# --- provision uv + Python 3.12 on shared disk (as v4) ---
# Serialized with flock: the v5 jobs share one .venv and may start at the same time.
TOOLS=/inspire/hdd/global_user/260107010002/.tools
export PATH="$TOOLS:$PATH"
export UV_PYTHON_INSTALL_DIR="$TOOLS/uv-python"
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi-proxy/simple/
provision() {
    if [ ! -x "$TOOLS/uv" ]; then
        mkdir -p "$TOOLS"
        curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS" sh
    fi
    uv python install 3.12
    uv sync
    UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi_proxy/simple/ uv pip install --python .venv/bin/python "anthropic==0.125.0"
}
if command -v flock >/dev/null 2>&1; then
    exec 9>"$TOOLS/.provision.lock"
    flock 9
    provision
    flock -u 9
else
    provision
fi

# --- secrets (never echoed) ---
set +x
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
set -x
if [ -z "$OPENAI_API_KEY" ] || [ -z "$SIMPLELLM_BASE_URL" ]; then
    echo "missing OPENAI_API_KEY / SIMPLELLM_BASE_URL in simpletes.env"; exit 2
fi
# Same model and depth as v4 (qwen3.8-max, thinking_budget 122880, max_tokens 131072).
export SIMPLETES_EXTRA_BODY="{\"thinking_budget\": ${THINKING_BUDGET:-122880}}"
LLM_ARGS=(--llm-backend openai_stream --model qwen3.8-max --api-base "$SIMPLELLM_BASE_URL"
    --reasoning-effort "${EFFORT:-max}" --max-tokens 131072)

# --- evaluation (as v4) ---
export EVALUATOR_CONCURRENT_PROCESSES=8   # v4 value: keeps the per-program RLIMIT_AS identical to v4
export EVALUATOR_TIMEOUT_SECONDS=3000
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=$WS_PATH
export ERDOS_REFERENCE_PATH=$WS_PATH
export ERDOS_REFERENCE_C5=$WS_C5
export SIMPLETES_REFLECTION_TIMEOUT=1800
# v5: 64 MiB (default 4 MiB). Above ~2e5 cells a new best would otherwise be dropped silently
# (capture_construction_if_requested returns False) and never pushed or recoverable.
export SIMPLETES_SHARED_CONSTRUCTION_MAX_BYTES=67108864

RUN_NAME=${RUN_NAME:-erdos-v5-$WARM_START}
mkdir -p "checkpoints/$RUN_NAME"
# Instruction = v4 text with this run's reference value (only the number and "15 decimals" differ).
INSTR="checkpoints/$RUN_NAME/instruction_v5_$WARM_START.txt"
sed "s/__REFERENCE_C5__/$WS_C5/g" datasets/erdos/erdos_min_overlap/erdos_min_overlap_v5.txt > "$INSTR"
if grep -q '__REFERENCE_C5__' "$INSTR"; then echo "instruction placeholder not rendered"; exit 2; fi

RESUME_ARGS=()
if [ -n "$RESUME" ]; then RESUME_ARGS=(--resume "$RESUME"); fi

.venv/bin/python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator_legacy.py \
  --instruction "$INSTR" \
  "${LLM_ARGS[@]}" \
  --reflection-effort medium \
  --timeout "${GEN_TIMEOUT:-5400}" \
  --first-chunk-timeout "${FIRST_CHUNK_TIMEOUT:-300}" \
  --stall-timeout "${STALL_TIMEOUT:-300}" \
  --selector rpucg \
  --num-chains 4 \
  --explore-chains 0 \
  --shared-construction-scope global \
  --k-candidates "${K_CANDIDATES:-4}" \
  --max-generations "${MAX_GENERATIONS:-240}" \
  --gen-concurrency "${GEN_CONCURRENCY:-16}" \
  --eval-concurrency "${EVAL_CONCURRENCY:-16}" \
  --eval-timeout 3300 \
  --init-eval-repeats 2 \
  --include-construction \
  --save-llm-io \
  --log-interval 2 \
  --output-path "checkpoints/$RUN_NAME" \
  "${RESUME_ARGS[@]}"
rc=$?
echo "EXITCODE=$rc"   # 2 = preflight/setup failed, 3 = API_FATAL during run
exit $rc
