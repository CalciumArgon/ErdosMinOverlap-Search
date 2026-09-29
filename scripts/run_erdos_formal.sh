#!/bin/bash
# Formal erdos A类 run: deepseek-v4-pro (thinking, high effort), rpucg, budget 40.
# Run inside a CPU HPC job (HPC-可上网区资源-2) or the prep notebook background.
set -x
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1

set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
export EVALUATOR_CONCURRENT_PROCESSES=8
export SIMPLETES_FORCE_REASONING_EFFORT=high   # switch to xhigh for max thinking budget
export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=/inspire/hdd/global_user/260107010002/home/SimpleTES/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi_proxy/simple/

/root/.local/bin/uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model deepseek/deepseek-v4-pro \
  --selector rpucg \
  --num-chains 4 \
  --k-candidates 4 \
  --max-generations 40 \
  --gen-concurrency 2 \
  --eval-concurrency 8 \
  --init-eval-repeats 2 \
  --max-tokens 24576 \
  --include-construction \
  --log-interval 16 \
  --output-path checkpoints/erdos-A-v4pro-high
