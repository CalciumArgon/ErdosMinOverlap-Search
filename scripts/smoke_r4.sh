#!/bin/bash
# Round-4 pre-flight at the FEASIBLE config: max_tokens ceiling is 131072 on this
# gateway, and reasoning tokens count against it, so thinking_budget=122880 with
# max_tokens=131072 is the deepest workable setting (262144 was rejected:
# "Range of max_tokens should be [1, 131072]").
#
# Checks, in order of cost:
#   1. egress to the external gateway
#   2. degenerate gate rejects a constant array (fast, no LLM)
#   3. the reflection call path with its OWN small bounded budget (fast, ~2 min)
#      -- this is new code in policies/base.py; must be verified before formal run
#   4. one generation call at the real budget: measures latency + non-empty content
# Run detached (step 4 can take ~45+ min); poll /tmp/smoke_r4.log.
cd /inspire/hdd/global_user/260107010002/home/SimpleTES || exit 1
set -a
. /inspire/hdd/global_user/260107010002/.secrets/simpletes.env
set +a
OUT=/tmp/smoke_r4.log
rm -f "$OUT"

echo "=== 1. egress ===" | tee -a "$OUT"
curl -sS -m 20 -o /dev/null -w "EGRESS_HTTP=%{http_code}\n" "$SIMPLELLM_BASE_URL/models" 2>&1 | tee -a "$OUT"

echo "=== 2. degenerate gate (fast, no LLM) ===" | tee -a "$OUT"
.venv/bin/python - <<'PY' 2>&1 | tee -a "$OUT"
import numpy as np, importlib.util
spec=importlib.util.spec_from_file_location("ev","datasets/erdos/erdos_min_overlap/evaluator_legacy.py")
ev=importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
try:
    ev.verify_c5_solution(np.full(100,0.5),0.5,100); print("GATE FAIL: constant not rejected")
except ValueError as e: print("GATE OK constant rejected:", str(e)[:55])
PY

echo "=== 3. reflection call with its own bounded budget (fast) ===" | tee -a "$OUT"
SIMPLETES_EXTRA_BODY='{"thinking_budget": 122880}' \
SIMPLETES_REFLECTION_THINKING=8192 \
SIMPLETES_REFLECTION_TIMEOUT=1200 \
.venv/bin/python - <<'PY' 2>&1 | tee -a "$OUT"
import os, sys, time, asyncio, json
sys.path.insert(0, ".")
from simpletes.policies.rpucg import RpucgPolicy
from simpletes.node import Node
p = RpucgPolicy(num_chains=1, max_generations=1, k=1, reflection_mode=True,
                llm_policy_model="openai/qwen3.8-max",
                llm_policy_api_base=os.environ["SIMPLELLM_BASE_URL"],
                llm_policy_api_key=os.environ["OPENAI_API_KEY"])
n = Node(id="smoke", code="def construct_h():\n    return [0.5]*10, 10\n",
         metrics={"c5": 0.5, "validity": 1.0, "combined_score": 2.0, "error": None},
         score=2.0,
         llm_input="Task: minimize max_k integral h(x)(1-h(x+k))dx over [0,2], sum(h)=n/2. Write construct_h().")
t0=time.time()
out = asyncio.run(p.reflect_on_winner(n))
dt=time.time()-t0
print("reflection elapsed=%.0fs len=%d"%(dt,len(out)))
print("starts_with_Approach:", out.startswith("Approach"))
print("TEXT:", out[:700] if out else "<EMPTY -- reflection path broken>")
PY

echo "=== 4. one generation call at thinking_budget=122880 (measure latency) ===" | tee -a "$OUT"
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
        messages=[{"role":"user","content":prompt}],max_tokens=131072,temperature=0.7,
        timeout=5400,drop_params=True,extra_body={"thinking_budget":122880})
    dt=time.time()-t0; m=r.choices[0].message
    c=getattr(m,"content","") or ""; rc=getattr(m,"reasoning_content","") or ""
    u=r.usage
    print("OK elapsed=%.0fs (%.1f min) finish=%s"%(dt,dt/60.0,r.choices[0].finish_reason),flush=True)
    print("usage:",json.dumps({k:getattr(u,k,None) for k in ("prompt_tokens","completion_tokens","reasoning_tokens","total_tokens")}),flush=True)
    print("content_len:",len(c),"reasoning_len:",len(rc),flush=True)
    print("HAS_EVOLVE_BLOCK:", "# EVOLVE-BLOCK-START" in c and "# EVOLVE-BLOCK-END" in c,flush=True)
    print("content_head:",c[:200].replace(chr(10)," "),flush=True)
except Exception as e:
    print("FAIL elapsed=%.0fs %s: %s"%(time.time()-t0,type(e).__name__,str(e)[:200]),flush=True)
print("SMOKE_R4_DONE",flush=True)
PY
