/* ---------- static tables ---------- */
const C = D.config || {};
const setupRows = [
  ["生成模型", `${esc(C.model || "qwen3.8-max")}（openai_stream 后端）`, "apicz.boyuerichdata.com；流式 chat completions"],
  ["思考深度", "thinking_budget = 122880", "max_tokens 上限 131072，推理也计入；给代码留约 8K"],
  ["max_tokens / 生成超时", `${esc(C.max_tokens)} / ${esc(C.timeout)} s`, "首包超时 300 s，流停顿超时 300 s"],
  ["选择器", esc(C.selector || "rpucg"), "链内父代选择不变（PUCT）"],
  ["链", "4 条：链 0、1 探索（无 warm start），链 2、3 利用（全局最好 warm start）", "--shared-construction-scope global"],
  ["每步候选 k / 总生成数", `2 / ${esc(C.max_generations)}`, "每条链串行 10 步，backpressure = 0"],
  ["并发", `生成 ${esc(C.gen_concurrency)} / 评测 ${esc(C.eval_concurrency)}`, "= 4 链 × k"],
  ["评测预算", `程序 3000 s，外层 ${esc(C.eval_timeout)} s`, "evaluator_legacy.py，精确 correlate，diagnostics 入 prompt"],
  ["反思", "同一模型，effort medium，不继承 thinking_budget", "rpucg 两行 Approach / Insight"],
  ["warm start", "best_results/…/erdos_minimum_overlap_best_construction.json", `N = 2400，c5 = ${REF.toFixed(13)}`],
  ["计算资源", "qz HPC-可上网区资源-2，40 CPU / 200 GiB", "作业 erdos-v4-qwen-20261026b，镜像 slurm-k8s-cluster:20250101841"],
];
$("#setup-table tbody").innerHTML = setupRows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td class="muted">${r[2]}</td></tr>`).join("");

const lit = [
  ["下界", "0.379005", "White 2022, arXiv:2201.05704", "Fourier / 对偶方法；本范式无法改进下界"],
  ["上界", "0.3809268534", "Haugland 2016, arXiv:1609.08000", "阶梯函数构造"],
  ["上界", "0.380924", "AlphaEvolve（Georgiev–Gómez-Serrano–Tao–Wagner 2025）", "LLM 进化搜索"],
  ["上界", "0.380876", "TTT-Discover (2026)", "erdosproblems.com #36 列出的当前公开最好"],
  ["上界", esc(certRef), "本仓库参照解（warm start）", "N = 2400；值已精确复核，是否已发表未核实"],
  ["上界", `<strong>${esc(certBest || best.c5.toFixed(12))}</strong>`, "<strong>本轮 v4</strong>", `N = ${bestP.n_points}；精确有理数复核`],
];
$("#lit-table tbody").innerHTML = lit.map(r => `<tr><td>${r[0]}</td><td class="num mono">${r[1]}</td><td>${r[2]}</td><td class="muted">${r[3]}</td></tr>`).join("");

const chip = r => `<span class="chip ${r}">${{ root: "参照", explore: "探索", exploit: "利用" }[r] || r}</span>`;
let prevC5 = null;
$("#bt-table tbody").innerHTML = TL.map((t, i) => {
  const p = P[t.id] || {}, n = byId[t.id] || {}, m = n.metrics || {};
  const gRef = REF - t.c5, gPrev = prevC5 == null ? null : prevC5 - t.c5; prevC5 = t.c5;
  return `<tr><td class="num">${i}</td><td class="mono">${esc(String(t.created_at).slice(11, 19))}</td><td>${chip(t.role)} ${t.chain ?? ""}</td><td class="num">${t.step ?? "–"}</td>
    <td class="mono">${id8(t.id)}</td><td class="num">${p.n_points ?? m.n_points ?? "–"}</td><td class="num">${t.c5.toFixed(13)}</td>
    <td class="num">${p.cert_upper_bound ? esc(p.cert_upper_bound) : '<span class="muted">未复核</span>'}</td>
    <td class="num ${gRef > 0 ? "better" : "worse"}">${i ? sci(gRef, 2) : "–"}</td><td class="num">${gPrev == null ? "–" : sci(gPrev, 2)}</td>
    <td class="num">${sci(m.l1_to_reference ?? (p.diff_vs_reference || {}).l1, 2)}</td><td class="num">${(p.near_active || {})["1e-8"] ?? "–"}</td><td class="num">${p.cert_n_active ?? "–"}</td></tr>`;
}).join("");

/* ---------- full node table ---------- */
const cols = [
  { k: "id", t: "节点", v: n => n.id, h: n => `<span class="mono">${id8(n.id)}</span>` },
  { k: "role", t: "角色", v: n => n.role, h: n => chip(n.role) },
  { k: "chain", t: "链", v: n => n.chain ?? -1, h: n => n.chain ?? "–", num: 1 },
  { k: "step", t: "步", v: n => n.step ?? 0, h: n => n.step ?? "–", num: 1 },
  { k: "t", t: "完成 (h)", v: n => hrs(n.created_at), h: n => fx(hrs(n.created_at), 2), num: 1 },
  { k: "parent", t: "父代", v: n => (n.parents || [])[0] || "", h: n => `<span class="mono">${(n.parents || []).map(id8).join(", ") || "–"}</span>` },
  { k: "warm", t: "warm 来源", v: n => n.warm_source || "", h: n => { const s = byId[n.warm_source]; return n.warm_source ? `<span class="mono">${id8(n.warm_source)}</span>${s && s.chain != null ? ` <span class="muted">(链${s.chain})</span>` : ""}` : "–"; } },
  { k: "c5", t: "c5", v: n => n.metrics.c5 ?? 9, h: n => fin(n.metrics.c5) ? n.metrics.c5.toFixed(13) : "–", num: 1 },
  { k: "d", t: "Δ ×10⁹", v: n => fin(n.metrics.c5) ? (n.metrics.c5 - REF) * 1e9 : 1e18, h: n => { if (!fin(n.metrics.c5)) return "–"; const d = (n.metrics.c5 - REF) * 1e9; return `<span class="${d < -1e-3 ? "better" : ""}">${Math.abs(d) >= 1e5 ? sci(d, 2) : d.toFixed(3)}</span>`; }, num: 1 },
  { k: "N", t: "N", v: n => n.metrics.n_points ?? 0, h: n => n.metrics.n_points ?? "–", num: 1 },
  { k: "act", t: "active", v: n => n.metrics.n_active_shifts ?? 0, h: n => n.metrics.n_active_shifts ?? "–", num: 1 },
  { k: "l1", t: "L¹ 到参照", v: n => n.metrics.l1_to_reference ?? 9, h: n => sci(n.metrics.l1_to_reference, 2), num: 1 },
  { k: "ws", t: "warm?", v: n => n.metrics.used_warm_start ? 1 : 0, h: n => n.metrics.used_warm_start == null ? "–" : (n.metrics.used_warm_start ? "是" : "否") },
  { k: "unch", t: "原样返回", v: n => n.metrics.returned_reference_unchanged ? 1 : 0, h: n => n.metrics.returned_reference_unchanged ? "是" : "–" },
  { k: "ev", t: "评测 (s)", v: n => n.metrics.eval_time ?? 0, h: n => fx(n.metrics.eval_time, 0), num: 1 },
  { k: "tok", t: "输出 token", v: n => tok(n.token_usage) ?? 0, h: n => tok(n.token_usage) ?? "–", num: 1 },
  { k: "code", t: "代码字符", v: n => n.code_chars, h: n => n.code_chars, num: 1 },
  { k: "refl", t: "反思（截断）", v: n => n.reflection || "", h: n => `<div class="refl">${esc((n.reflection || "").slice(0, 320))}</div>` },
];
let sortK = "t", sortDir = 1, filt = "all";
const thead = $("#node-table thead tr");
thead.innerHTML = cols.map(c => `<th data-k="${c.k}" class="${c.num ? "num" : ""}" tabindex="0" aria-sort="${c.k === sortK ? "ascending" : "none"}">${c.t}</th>`).join("");
function renderNodes() {
  const col = cols.find(c => c.k === sortK);
  const rows = nodes.filter(n => n.metrics && (filt === "all" || n.role === filt || (filt === "better" && fin(n.metrics.c5) && n.metrics.c5 < REF - 1e-15)))
    .slice().sort((a, b) => { const x = col.v(a), y = col.v(b); return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
  $("#node-table tbody").innerHTML = rows.map(n => `<tr>${cols.map(c => `<td class="${c.num ? "num" : ""}">${c.h(n)}</td>`).join("")}</tr>`).join("");
  $$("#node-table th").forEach(th => th.setAttribute("aria-sort", th.dataset.k === sortK ? (sortDir > 0 ? "ascending" : "descending") : "none"));
}
const onSort = th => { const k = th.dataset.k; sortDir = k === sortK ? -sortDir : 1; sortK = k; renderNodes(); };
$$("#node-table th").forEach(th => { th.addEventListener("click", () => onSort(th)); th.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSort(th); } }); });
$$("#node-filter button").forEach(b => b.addEventListener("click", () => {
  filt = b.dataset.f; $$("#node-filter button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); renderNodes();
}));
renderNodes();

/* ---------- API health table ---------- */
const groups = {};
(D.health || []).forEach(h => { const k = h.kind + "|" + h.class; (groups[k] = groups[k] || []).push(h); });
$("#health-table tbody").innerHTML = Object.entries(groups).sort().map(([k, a]) => {
  const [kind, cls] = k.split("|"); const el = a.map(h => (h.elapsed_s || 0) / 60);
  return `<tr><td>${esc(kind)}</td><td><span class="chip ${cls === "ok" ? "ok" : "bad"}">${esc(cls)}</span></td><td class="num">${a.length}</td>
    <td class="num">${fx(med(el), 1)} / ${fx(mx(el), 1)}</td><td class="num">${fx(mx(a.map(h => h.first_event_s)), 1)}</td><td class="num">${fx(mx(a.map(h => h.max_gap_s)), 1)}</td>
    <td class="num">${med(a.map(h => h.output_tokens)) ?? "–"} / ${mx(a.map(h => h.output_tokens)) ?? "–"}</td><td class="num">${med(a.map(h => h.thinking_chars)) ?? "–"}</td><td class="num">${med(a.map(h => h.text_chars)) ?? "–"}</td></tr>`;
}).join("");

const limits = D.limits || [
  "改进是精修，不是新结构：最好解相对参照解的 L¹ 位移约 10⁻⁶–10⁻⁵ 量级，峰的结构没有变。探索链从零构造，最好停在约 2×10⁻⁴ 的差距上，没有发现可以竞争的新结构。",
  "只有一次运行、一个随机性实现，分不清哪些改进来自配置、哪些来自运气。要判断修改 #5–#7 各自的贡献，需要做对照（例如关闭全局共享，或改回 :.6f）。",
  "最好解的精确 argmax 只有一个平移，而接近最大值的平移有数百个：离 KKT 点还有距离（7.5 节），继续下降空间明显。下一版可以把“接近 active 的平移集合”和一个可行下降方向作为诊断字段交给利用链，或允许利用链在 rN 上做更长的局部优化。",
  "探索链的 3000 s 评测预算大多用于从零优化，但最好的从零结构仍然差 2×10⁻⁴。是否值得保留 2 条探索链，取决于下一轮是追求新结构还是继续精修。",
  "对外宣称新纪录之前，需要核实参照解来源，并独立复核 problem_formulation.md 的证明（7.6 节）。",
];
fill("limits_list", limits.map(x => `<li>${x}</li>`).join(""));
