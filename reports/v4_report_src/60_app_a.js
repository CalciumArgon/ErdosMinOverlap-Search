(function () {
"use strict";
const D = JSON.parse(document.getElementById("report-data").textContent);
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fin = x => x != null && isFinite(x);
const med = a => { const b = a.filter(fin).sort((x, y) => x - y); return b.length ? b[Math.floor((b.length - 1) / 2)] : null; };
const mx = a => { const b = a.filter(fin); return b.length ? Math.max(...b) : null; };
const fx = (x, d = 1) => fin(x) ? Number(x).toFixed(d) : "–";
const SUP = { "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹" };
const sup = e => String(parseInt(e, 10)).split("").map(c => SUP[c] || c).join("");
const sci = (x, d = 2) => { if (!fin(x)) return "–"; if (x === 0) return "0"; const [m, e] = Number(x).toExponential(d).split("e"); return `${m}×10${sup(e)}`; };
const fill = (k, html) => $$(`[data-k="${k}"]`).forEach(el => { el.innerHTML = html; });
const parseT = iso => Date.parse(String(iso).slice(0, 23) + "Z");
const tok = u => { if (!u || typeof u !== "object") return null; return u.completion_tokens ?? u.output_tokens ?? u.total_tokens ?? null; };
const id8 = id => id ? String(id).slice(0, 8) : "–";

const nodes = D.nodes || [];
const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
const root = nodes.find(n => n.role === "root") || nodes[0];
const REF = root.metrics.c5;
const t0 = parseT(root.created_at);
const hrs = iso => (parseT(iso) - t0) / 3.6e6;
const TL = D.timeline || [];
const P = D.profiles || {};
const best = TL[TL.length - 1];
const bestP = P[best.id] || {};
const refP = P[TL[0].id] || {};
const bestNode = byId[best.id] || {};
const evaluated = nodes.filter(n => n.role !== "root" && n.metrics && n.metrics.c5 != null);
const valid = evaluated.filter(n => n.metrics.validity);
const gens = (D.health || []).filter(h => h.kind === "generation");
const genOk = gens.filter(h => h.class === "ok");
const roleOfChain = c => (nodes.find(n => n.chain === c) || {}).role;

/* ---------- headline figures ---------- */
const certBest = bestP.cert_upper_bound;
const certRef = refP.cert_upper_bound || D.reference_cert;
const exactBest = fin(bestP.cert_c5_float) ? bestP.cert_c5_float : best.c5;
const exactRef = fin(refP.cert_c5_float) ? refP.cert_c5_float : REF;
const impr = exactRef - exactBest;
fill("instance", esc(D.instance)); fill("instance2", esc(D.instance)); fill("db_state", esc(D.db_state));
fill("generated", esc(D.generated || ""));
fill("best_cert", certBest ? esc(certBest) : esc(best.c5.toFixed(12)) + " <span class=\"muted\">(未复核)</span>");
fill("best_cert_inline", certBest || best.c5.toFixed(12)); fill("best_cert_inline2", certBest || best.c5.toFixed(12));
fill("best_cert_note", `N = ${bestP.n_points || "?"}，链 ${best.chain} 第 ${best.step} 步，节点 <span class="mono">${id8(best.id)}</span>`);
fill("ref_cert", esc(certRef));
fill("improvement", sci(impr, 3));
fill("improvement_rel", `相对改进 ${sci(impr / exactRef, 2)}`);
fill("counts", `${evaluated.length} / ${gens.length}`);
const totOut = gens.reduce((s, h) => s + (h.output_tokens || 0), 0);
const totGenH = gens.reduce((s, h) => s + (h.elapsed_s || 0), 0) / 3600;
const lastT = Math.max(...nodes.map(n => parseT(n.created_at)));
fill("counts_note", `有效 ${valid.length}；生成输出共 ${fx(totOut / 1e6, 2)}M token，累计生成 ${fx(totGenH, 1)} h；墙钟 ${fx((lastT - t0) / 3.6e6, 1)} h`);
fill("best_n", String(bestP.n_points || "?"));
fill("best_nactive", String(bestP.cert_n_active ?? "?"));
fill("best_near8", String((bestP.near_active || {})["1e-8"] ?? "?"));
fill("ref_near8", String((refP.near_active || {})["1e-8"] ?? "?"));
const g1 = fin(bestP.cert_c5_float) ? Math.abs((bestNode.metrics || {}).c5 - bestP.cert_c5_float) : null;
fill("float_diff", g1 == null ? "未复核" : sci(g1, 1));
fill("g1", g1 == null ? "未复核" : `float 误差 ${sci(g1, 1)} → 0`);
fill("g3", `≤ ${sci(exactBest - 0.379005, 2)}`);

const btRoles = TL.slice(1).map(t => t.role);
const allExploit = btRoles.length && btRoles.every(r => r === "exploit");
fill("headline_text",
  `本轮共 ${TL.length - 1} 次刷新全局最好，${allExploit ? "全部来自利用链" : "来自 " + [...new Set(btRoles)].join("、")}。` +
  `最好解来自链 ${best.chain} 第 ${best.step} 步（节点 <span class="mono">${id8(best.id)}</span>，N = ${bestP.n_points}），` +
  `严格上界 <strong class="mono">${esc(certBest || best.c5.toFixed(12))}</strong>，比参照解 ${esc(certRef)} 低 ${sci(impr, 2)}。`);

let relay = 0, self = 0;
TL.slice(1).forEach(t => {
  const src = byId[(byId[t.id] || {}).warm_source];
  if (!src || src.role === "root") return;
  if (src.chain !== t.chain) relay++; else self++;
});
fill("relay_text",
  `突破的链顺序：${TL.slice(1).map(t => "链 " + t.chain).join(" → ")}。按每个突破节点拿到的 warm start 来源统计：` +
  `${relay} 次是在<strong>另一条链</strong>推来的全局最好解上继续下降得到的，${self} 次是在本链自己之前的突破上继续下降，其余直接从参照解出发。` +
  `本轮新增的全局共享（修改 #6）在这里起了作用：没有它，一条链的进展传不到另一条链。`);

const nFail = (D.failures || []).length;
fill("failures_text", nFail ? `另有 ${nFail} 条失败记录（${[...new Set((D.failures || []).map(x => x.type + "：" + String(x.reason).slice(0, 60)))].join("；")}）。这些候选没有分数，不在表中。` : "没有失败记录。");
