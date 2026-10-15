#!/bin/bash
# Round-4 pre-flight: measure the REAL production per-call latency at
# thinking_budget=262144 and confirm non-empty content, plus unit-check the
# degenerate gate. Deliberately a direct litellm probe rather than a full main.py
# generation: the harness wiring is unchanged from round 3 (which ran end-to-end),
# only the budget/timeout moved, so the only new risks are (a) gateway accepts
# 262144 and (b) one call returns visible content within --timeout. Run detached.
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
OUT=/tmp/smoke_r4.log
rm -f "$OUT"

echo "=== egress ===" | tee -a "$OUT"
curl -sS -m 20 -o /dev/null -w "EGRESS_HTTP=%{http_code}\n" "$SIMPLELLM_BASE_URL/models" 2>&1 | tee -a "$OUT"

echo "=== degenerate gate (fast, no LLM) ===" | tee -a "$OUT"
.venv/bin/python - <<'PY' 2>&1 | tee -a "$OUT"
import numpy as np, importlib.util
spec=importlib.util.spec_from_file_location("ev","datasets/erdos/erdos_min_overlap/evaluator_legacy.py")
ev=importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
try:
    ev.verify_c5_solution(np.full(100,0.5),0.5,100); print("GATE FAIL: constant not rejected")
except ValueError as e: print("GATE OK constant rejected:", str(e)[:55])
PY

echo "=== single litellm call at thinking_budget=262144 (measure latency) ===" | tee -a "$OUT"
.venv/bin/python - <<'PY' 2>&1 | tee -a "$OUT"
import os, time, json
from litellm import completion
base=os.environ["SIMPLELLM_BASE_URL"]; key=os.environ["OPENAI_API_KEY"]
instr=open("datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt",encoding="utf-8").read()
prompt=("Task: "+instr+"\n\nReturn ONE python code block including # EVOLVE-BLOCK-START and "
        "# EVOLVE-BLOCK-END defining construct_h() that returns (h_values, n_points). No prose.\n")
print("prompt_chars:",len(prompt),flush=True)
t0=time.time()
try:
    r=completion(model="openai/qwen3.8-max",api_base=base,api_key=key,
        messages=[{"role":"user","content":prompt}],max_tokens=300000,temperature=0.7,
        timeout=7200,drop_params=True,extra_body={"thinking_budget":262144})
    dt=time.time()-t0; m=r.choices[0].message
    c=getattr(m,"content","") or ""; rc=getattr(m,"reasoning_content","") or ""
    u=r.usage
    print("OK elapsed=%.0fs (%.1f min) finish=%s"%(dt,dt/60.0,r.choices[0].finish_reason),flush=True)
    print("usage:",json.dumps({k:getattr(u,k,None) for k in ("prompt_tokens","completion_tokens","reasoning_tokens","total_tokens")}),flush=True)
    print("content_len:",len(c),"reasoning_len:",len(rc),flush=True)
    print("content_head:",c[:200].replace(chr(10)," "),flush=True)
except Exception as e:
    print("FAIL elapsed=%.0fs %s: %s"%(time.time()-t0,type(e).__name__,str(e)[:200]),flush=True)
print("SMOKE_R4_DONE",flush=True)
PY
