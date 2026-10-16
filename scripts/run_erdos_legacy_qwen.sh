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
#
# HARD GATEWAY CEILING (probed 2026-10-15): max_tokens must be in [1, 131072];
# a request with max_tokens>131072 is rejected with InvalidParameter. Because
# reasoning tokens count AGAINST max_tokens on this gateway, thinking_budget must
# stay below 131072 or the visible content is truncated to empty. So the 262144
# "gateway max" for thinking_budget is unreachable in practice — the real ceiling
# is max_tokens=131072 with thinking_budget just under it, leaving ~8k for the
# emitted program. Round 4 therefore runs the deepest FEASIBLE thinking:
#   thinking_budget=122880, max_tokens=131072.
#
# THINKING SEMANTICS (C.1c streamed campaign, 2026-10-16): this endpoint spends
# the WHOLE thinking_budget on reasoning before emitting any content, at
# ~45 tok/s. So a deep call sends zero bytes for the first ~45 min — not a dead
# request, an alive-but-mute-until-done one. Streamed measurements:
#   tb=16384 -> ~6 min thinking; tb=65536 -> 29 min; tb=122880 -> 31 min
#   (parallel load; serial calls may differ). Non-streamed round trips are
#   measured by the E/F probes (thinking + content + overhead).
# CONSEQUENCE FOR --timeout: the generation path (litellm_client.py) is a
# SYNCHRONOUS completion — one timeout for the whole call, thinking included.
# A timeout shorter than think+write silently loses the entire batch slot
# (LLMClient retry=0; the batch finalizes and the run keeps going, which is
# exactly the "hours of useless thinking" failure we must not ship). Round-3's
# 5400 covered a lone 16K call; this script runs 4-wide at tb=122880, where
# per-call latency inflates under load — hence the much larger value below.
# NOTE: SIMPLETES_FORCE_REASONING_EFFORT is intentionally NOT set — it pins
# allowed_openai_params=["reasoning_effort"], which qwen's gateway rejects.
export SIMPLETES_EXTRA_BODY='{"thinking_budget": 122880}'
# Reflection is a two-line summary and must NOT inherit the deep generation budget
# (it runs on the eval-worker critical path once per batch). Give it its own small
# bounded thinking budget + timeout (see policies/base.py reflect_on_winner).
export SIMPLETES_REFLECTION_THINKING=8192
export SIMPLETES_REFLECTION_TIMEOUT=1200
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
  --timeout 21600 \
  --include-construction \
  --log-interval 16 \
  --output-path checkpoints/erdos-legacy-qwen-r4
echo "EXITCODE=$?"
