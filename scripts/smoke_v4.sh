#!/bin/bash
# v4 smoke tests (prep notebook). Usage:  bash scripts/smoke_v4.sh [a|b|c|deep|all]
#   a     gateway protocol + API classes (ping, bad key, short timeout, 8-way concurrency)
#   b     evaluator / certify (no LLM): reference reproduces 0.38086768, repeat
#         invariance, diagnostics fields, constant rejection
#   c     mini run: 1 explore + 1 exploit chain, low effort, then --resume
#   deep  one real-depth xhigh generation call (long: calibrates --timeout)
# Output: /tmp/smoke_v4/<stage>.log ; grep "SMOKE\|CERTIFY\|API-HEALTH".
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1
export PATH=/inspire/hdd/global_user/260107010002/.tools:$PATH
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env   # never echoed
set +a
export SMOKE_DIR=/tmp/smoke_v4
mkdir -p "$SMOKE_DIR"
PY=.venv/bin/python
export UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi-proxy/simple/
UV_DEFAULT_INDEX=http://nexus.sii.shaipower.online/repository/pypi_proxy/simple/ uv pip install --python $PY "anthropic==0.125.0" >/dev/null || { echo "SMOKE anthropic install FAIL"; exit 1; }
# absolute: evaluator subprocesses run with cwd = a temp eval dir
REF=$PWD/best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json
STAGE=${1:-all}

stage_a() {
    echo "=== a.1 gateway protocol (HTTP status only) ==="
    for path in /v1/messages /v1/chat/completions; do
        if [ "$path" = /v1/messages ]; then
            body='{"model":"claude-opus-5-5","max_tokens":64,"messages":[{"role":"user","content":"pong?"}]}'
            code=$(curl -sS -m 60 -o "$SMOKE_DIR/proto_messages.json" -w "%{http_code}" \
                -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
                -H "content-type: application/json" -d "$body" "$ANTHROPIC_BASE_URL$path")
        else
            body='{"model":"claude-opus-5-5","max_tokens":64,"messages":[{"role":"user","content":"pong?"}]}'
            code=$(curl -sS -m 60 -o "$SMOKE_DIR/proto_chat.json" -w "%{http_code}" \
                -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
                -H "content-type: application/json" -d "$body" "$ANTHROPIC_BASE_URL$path")
        fi
        echo "SMOKE proto $path HTTP=$code"
    done
    head -c 400 "$SMOKE_DIR/proto_messages.json"; echo
    echo "=== a.2 thinking display=summarized accepted? (stream, first 30 event types) ==="
    body='{"model":"claude-opus-5-5","max_tokens":2048,"stream":true,"thinking":{"type":"adaptive","display":"summarized"},"output_config":{"effort":"high"},"messages":[{"role":"user","content":"Is 1001 prime? Think briefly."}]}'
    curl -sS -N -m 300 -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" -d "$body" "$ANTHROPIC_BASE_URL/v1/messages" \
        | grep -o '"type":"[a-z_]*"' | head -30 | tr '\n' ' '; echo
    echo "=== a.3 client classes ==="
    $PY scripts/smoke_v4_api.py ping badkey shorttime conc 8
}

stage_b() {
    echo "=== b.1 certify reference ==="
    $PY scripts/certify_erdos_grid.py "$REF" --direct --repeat 2 3 --expect 0.38086768
    echo "=== b.2 evaluator diagnostics + constant rejection ==="
    # PYTHONPATH=repo root so sitecustomize installs GLOBAL_BEST_CONSTRUCTION in the child
    PYTHONPATH=$PWD ERDOS_REFERENCE_PATH=$REF ERDOS_REFERENCE_C5=0.38086768 EVALUATOR_TIMEOUT_SECONDS=600 \
    SIMPLETES_SHARED_CONSTRUCTION_PATH=$REF \
    $PY - <<'PY'
import importlib.util, json, os, tempfile, numpy as np
spec = importlib.util.spec_from_file_location("ev", "datasets/erdos/erdos_min_overlap/evaluator_legacy.py")
ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
# init program with the warm start returns the reference unchanged
m = ev.evaluate("datasets/erdos/erdos_min_overlap/init_program.py")
print("SMOKE eval-warm:", json.dumps({k: m.get(k) for k in (
    "c5_str", "gap_to_reference_e6", "used_warm_start", "l1_to_reference",
    "returned_reference_unchanged", "n_active_shifts", "n_points", "error")}))
ok = (m.get("validity") == 1.0 and m.get("used_warm_start") is True
      and m.get("returned_reference_unchanged") is True and abs(m["gap_to_reference_e6"]) < 0.01)
# without the warm start the fallback is evaluated and is far from the reference
os.environ.pop("SIMPLETES_SHARED_CONSTRUCTION_PATH")
m2 = ev.evaluate("datasets/erdos/erdos_min_overlap/init_program.py")
print("SMOKE eval-cold:", json.dumps({k: m2.get(k) for k in (
    "c5_str", "used_warm_start", "l1_to_reference", "returned_reference_unchanged", "error")}))
ok &= m2.get("used_warm_start") is False and (m2.get("l1_to_reference") or 0) > 0.01
# exact L1 helper: repeat-refined copy is at distance 0, reflection/complement too
ref = ev._load_reference_h()
d = [ev.orbit_l1_to_reference(np.repeat(ref, 2), ref), ev.orbit_l1_to_reference(ref[::-1], ref),
     ev.orbit_l1_to_reference(1 - ref, ref)]
print("SMOKE l1-orbit (all ~0):", d); ok &= max(d) < 1e-12
try:
    ev.verify_c5_solution(np.full(100, 0.5), 0.5, 100); print("SMOKE constant: FAIL not rejected"); ok = False
except ValueError as e:
    print("SMOKE constant rejected:", str(e)[:60])
print("SMOKE stage-b", "PASS" if ok else "FAIL")
PY
}

stage_c() {
    echo "=== c.1 mini run (1 explore + 1 exploit, effort low) ==="
    export EVALUATOR_CONCURRENT_PROCESSES=4 EVALUATOR_TIMEOUT_SECONDS=300
    export SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=$REF ERDOS_REFERENCE_PATH=$REF ERDOS_REFERENCE_C5=0.38086768
    export SIMPLETES_REFLECTION_TIMEOUT=600
    rm -rf checkpoints/smoke-v4
    common=(--init-program datasets/erdos/erdos_min_overlap/init_program.py
        --evaluator datasets/erdos/erdos_min_overlap/evaluator_legacy.py
        --instruction datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt
        --llm-backend anthropic --model claude-opus-5-5 --api-base "$ANTHROPIC_BASE_URL"
        --reasoning-effort low --reflection-effort low --max-tokens 32000 --timeout 1800
        --first-chunk-timeout 300 --stall-timeout 600
        --selector rpucg --num-chains 2 --explore-chains 1 --shared-construction-scope global
        --k-candidates 2 --gen-concurrency 4 --eval-concurrency 4 --eval-timeout 400
        --init-eval-repeats 1 --include-construction --save-llm-io --log-interval 2
        --debug-prompt-lines 0 --output-path checkpoints/smoke-v4)
    $PY main.py "${common[@]}" --max-generations 4; echo "SMOKE mini-run EXITCODE=$?"
    inst=$(ls -d checkpoints/smoke-v4/*/instance-* | head -1)
    echo "SMOKE instance=$inst"
    wc -l "$inst/api_health.jsonl"
    grep -c '"class": "ok"' "$inst/api_health.jsonl"
    echo "=== c.2 resume to 6 generations ==="
    $PY main.py "${common[@]}" --max-generations 6 --resume "$inst"; echo "SMOKE resume EXITCODE=$?"
    grep -h "pushed to exploit\|Chain role\|API_ALERT" "$inst/run.log" | head
}

case $STAGE in
    a) stage_a ;; b) stage_b ;; c) stage_c ;;
    deep) $PY scripts/smoke_v4_api.py deep ;;
    all) stage_a; stage_b; stage_c ;;
esac 2>&1 | tee "$SMOKE_DIR/$STAGE.log"
