#!/bin/bash
# Smoke test for the legacy-qwen run: tiny budget, verifies end-to-end wiring.
# Confirms: preflight 1-token ping passes, qwen returns non-empty content,
# the warm-start init node scores ~= 0.38087, and a reflection starting with
# 'Approach:' is produced. Upload via `inspire notebook scp`, run with setsid.
set -x
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1

TOOLS=/inspire/hdd/global_user/260107010002/.tools
export PATH="$TOOLS:$PATH"
export UV_PYTHON_INSTALL_DIR="$TOOLS/uv-python"
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi-proxy/simple/

set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
export EVALUATOR_CONCURRENT_PROCESSES=2
export SIMPLETES_EXTRA_BODY='{"thinking_budget": 8192}'
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=/inspire/hdd/global_user/260107010002/home/SimpleTES/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json

# Egress probe first: the boyuerichdata endpoint is external.
curl -sS -m 20 -o /dev/null -w "EGRESS_HTTP=%{http_code}\n" "$SIMPLELLM_BASE_URL/models" || echo "EGRESS_PROBE_FAILED"

.venv/bin/python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator_legacy.py \
  --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model openai/qwen3.8-max \
  --api-base "$SIMPLELLM_BASE_URL" \
  --selector rpucg \
  --num-chains 2 \
  --k-candidates 2 \
  --max-generations 2 \
  --gen-concurrency 2 \
  --eval-concurrency 2 \
  --init-eval-repeats 1 \
  --max-tokens 32768 \
  --timeout 600 \
  --include-construction \
  --log-interval 1 \
  --output-path checkpoints/erdos-legacy-qwen-smoke
echo "SMOKE_EXITCODE=$?"
