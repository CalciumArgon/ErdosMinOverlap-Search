/* ---------- charts (rebuilt on theme change so colors follow the tokens) ---------- */
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const alpha = (c, a) => { const h = c.replace("#", ""); if (h.length !== 6) return c; const n = parseInt(h, 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
let charts = [], diffSel = best.id;
const chainColor = ch => ch === 2 ? css("--exploit") : ch === 3 ? alpha(css("--exploit"), 0.55) : ch === 0 ? css("--explore") : ch === 1 ? alpha(css("--explore"), 0.55) : css("--ref");
const FLOOR = 0.05;

function base(xTitle, yTitle, extra = {}) {
  const ink = css("--muted"), grid = alpha(css("--rule").length === 7 ? css("--rule") : "#888888", 0.8);
  return { responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
    interaction: { mode: "nearest", intersect: false },
    plugins: { legend: { labels: { color: ink, boxWidth: 12, font: { size: 11 } } },
      tooltip: { callbacks: extra.tooltip || {} } },
    scales: { x: Object.assign({ type: "linear", title: { display: true, text: xTitle, color: ink }, ticks: { color: ink }, grid: { color: grid } }, extra.x || {}),
              y: Object.assign({ title: { display: true, text: yTitle, color: ink }, ticks: { color: ink }, grid: { color: grid } }, extra.y || {}) } };
}

function buildCharts() {
  if (typeof Chart === "undefined") {
    $$(".canvas-box").forEach(b => { b.innerHTML = '<p class="muted">图表库（cdnjs Chart.js 4.4.1）没有加载，可能是离线打开。表格中的数据完整。</p>'; });
    return;
  }
  charts.forEach(c => c.destroy()); charts = [];
  const mk = (id, cfg) => charts.push(new Chart($(id), cfg));
  const lastH = Math.max(...nodes.map(n => hrs(n.created_at)));

  // 1. exploit chains: gain over the reference (×1e9, log)
  const exp = [2, 3].filter(c => roleOfChain(c) === "exploit").map(c => ({
    label: `链 ${c}（利用）`, type: "scatter", backgroundColor: chainColor(c), borderColor: chainColor(c), pointRadius: 4,
    data: valid.filter(n => n.chain === c).map(n => ({ x: hrs(n.created_at), y: Math.max((REF - n.metrics.c5) * 1e9, FLOOR), id: n.id, raw: (REF - n.metrics.c5) * 1e9 })) }));
  const stepPts = TL.map(t => ({ x: hrs(t.created_at), y: Math.max((REF - t.c5) * 1e9, FLOOR) }));
  stepPts.push({ x: lastH, y: stepPts[stepPts.length - 1].y });
  exp.push({ label: "全局最好", type: "line", data: stepPts, stepped: "after", borderColor: css("--accent"), borderWidth: 2, pointRadius: 0 });
  mk("#chart-exploit", { type: "scatter", data: { datasets: exp }, options: base("运行时间 (h)", "比参照解低 (×10⁻⁹)", {
    y: { type: "logarithmic", min: FLOOR, ticks: { color: css("--muted"), callback: v => v <= FLOOR ? "≤0" : (Number.isInteger(Math.log10(v)) ? v : "") } },
    tooltip: { label: ctx => ctx.raw.id ? `${id8(ctx.raw.id)}：${ctx.raw.raw.toFixed(3)} ×10⁻⁹` : `全局最好 ${ctx.raw.y.toFixed(2)} ×10⁻⁹` } }) });

  // 2. explore chains: gap above the reference (×1e-4)
  const ex2 = [0, 1].filter(c => roleOfChain(c) === "explore").map(c => ({
    label: `链 ${c}（探索）`, backgroundColor: chainColor(c), borderColor: chainColor(c), pointRadius: 4,
    data: valid.filter(n => n.chain === c).map(n => ({ x: hrs(n.created_at), y: (n.metrics.c5 - REF) * 1e4, id: n.id })) }));
  ex2.push({ label: "参照解", type: "line", data: [{ x: 0, y: 0 }, { x: lastH, y: 0 }], borderColor: css("--ref"), borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 });
  mk("#chart-explore", { type: "scatter", data: { datasets: ex2 }, options: base("运行时间 (h)", "c5 − c5_ref (×10⁻⁴)", {
    y: { min: 0, suggestedMax: 30 }, tooltip: { label: ctx => ctx.raw.id ? `${id8(ctx.raw.id)}：+${ctx.raw.y.toFixed(3)} ×10⁻⁴` : "参照解" } }) });

  // 3. breakthrough ladder
  const bts = TL.slice(1);
  mk("#chart-ladder", { type: "bar", data: { labels: bts.map((t, i) => `#${i + 1} 链${t.chain}`),
    datasets: [{ label: "比参照解低 (×10⁻⁹)", data: bts.map(t => (REF - t.c5) * 1e9), backgroundColor: bts.map(t => chainColor(t.chain)) }] },
    options: Object.assign(base("", "比参照解低 (×10⁻⁹)", { x: { type: "category" }, y: { type: "logarithmic" },
      tooltip: { label: ctx => `${ctx.parsed.y.toFixed(3)} ×10⁻⁹（N = ${(P[bts[ctx.dataIndex].id] || {}).n_points ?? "?"}）` } }), { parsing: true }) });

  // 4. h_new − h_ref for the selected breakthrough
  const dp = (P[diffSel] || {}).diff_vs_reference || { plot: [], plot_absmax: [] };
  const xs = a => a.map((y, i) => ({ x: 2 * (i + 0.5) / a.length, y }));
  mk("#chart-diff", { type: "line", data: { datasets: [
    { label: "|差| 区间最大值", data: xs(dp.plot_absmax), borderColor: alpha(css("--accent"), 0.35), backgroundColor: alpha(css("--accent"), 0.15), fill: true, pointRadius: 0, borderWidth: 1 },
    { label: "差（区间均值）", data: xs(dp.plot), borderColor: css("--exploit"), pointRadius: 0, borderWidth: 1.5 } ] },
    options: base("x ∈ [0, 2]", "h_new − h_ref", { x: { min: 0, max: 2 }, y: { ticks: { color: css("--muted"), callback: v => sci(v, 0) } } }) });

  // 5. overlap curve A(s): reference vs best (envelope of maxima)
  const cp = p => (p.corr_plot || []).map((y, i) => ({ x: (p.corr_plot_shift || [])[i], y }));
  mk("#chart-corr", { type: "line", data: { datasets: [
    { label: "参照解", data: cp(refP), borderColor: css("--ref"), pointRadius: 0, borderWidth: 1.2 },
    { label: "本轮最好", data: cp(bestP), borderColor: css("--accent"), pointRadius: 0, borderWidth: 1.2 },
    { label: "最好解的 C(h)", data: [{ x: -2, y: bestP.c5_float }, { x: 2, y: bestP.c5_float }], borderColor: css("--bad"), borderDash: [4, 4], pointRadius: 0, borderWidth: 1 } ] },
    options: base("平移 s", "A_h(s)", { x: { min: -2, max: 2 } }) });

  // 6. how many shifts sit near the maximum
  const lev = [["1e-6", 0.35], ["1e-8", 0.65], ["1e-10", 1]];
  mk("#chart-near", { type: "bar", data: { labels: TL.map((t, i) => i ? `#${i} 链${t.chain}` : "参照"),
    datasets: lev.map(([k, a]) => ({ label: `距最大值 ≤ ${k.replace("1e-", "10^-")}`, data: TL.map(t => ((P[t.id] || {}).near_active || {})[k] || null), backgroundColor: alpha(css("--accent"), a) })) },
    options: Object.assign(base("", "格点平移个数", { x: { type: "category" }, y: { type: "logarithmic" } }), { parsing: true }) });

  // 7. the best h(x) itself
  mk("#chart-h", { type: "line", data: { datasets: [
    { label: "参照解", data: xs(refP.h_plot || []), borderColor: css("--ref"), pointRadius: 0, borderWidth: 2.5 },
    { label: "本轮最好", data: xs(bestP.h_plot || []), borderColor: css("--accent"), pointRadius: 0, borderWidth: 1 } ] },
    options: base("x ∈ [0, 2]", "h(x)", { x: { min: 0, max: 2 }, y: { min: 0, max: 1 } }) });

  // 8. generation latency vs output tokens
  mk("#chart-gen", { type: "scatter", data: { datasets: [
    { label: "ok", data: genOk.map(h => ({ x: h.elapsed_s / 60, y: h.output_tokens })), backgroundColor: alpha(css("--accent"), 0.7), pointRadius: 3.5 },
    { label: "非 ok", data: gens.filter(h => h.class !== "ok").map(h => ({ x: (h.elapsed_s || 0) / 60, y: h.output_tokens || 0 })), backgroundColor: css("--bad"), pointRadius: 5 } ] },
    options: base("生成耗时 (min)", "输出 token（含推理）", { y: { min: 0 } }) });
}

const dc = $("#diff-controls");
dc.innerHTML = TL.slice(1).map((t, i) => `<button type="button" data-id="${t.id}" aria-pressed="${t.id === diffSel}">#${i + 1} 链${t.chain}</button>`).join("");
$$("button", dc).forEach(b => b.addEventListener("click", () => {
  diffSel = b.dataset.id; $$("button", dc).forEach(x => x.setAttribute("aria-pressed", String(x === b))); buildCharts();
}));
buildCharts();
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", buildCharts); } catch (e) { /* old browsers */ }
new MutationObserver(buildCharts).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
