# Version 3：legacy 网格 + 评估语义提示（round 3）

- commit 区间：59879a3 … cf57ae1（报告 `reports/erdos-legacy-meta-round3-report.md`、`reports/report1020.html`）
- 作业：erdos-legacy-qwen-r3c-20261015（HPC，1.7 h，SUCCEEDED）

## 结构
- 回到 legacy evaluator：程序返回 `(h_values, c5_bound, n_points)`，`max(np.correlate(h,1-h,'full'))·2/N`，要求 sum = N/2。
- 指令删去所有"好解长什么样"的提示，改为讲评估语义：分数对返回的阶梯函数精确，但当时认为它只是松弛问题的上界；列出网格 artifact 与松弛 artifact，提供可选自查（加密网格、二值化）。
- rpucg reflection 改为两行 Approach / Insight，Insight 判断分数是否可信。
- qwen thinking_budget 16384，timeout 1500（更大预算会超时）。

## 结果
- 38 个候选：37 有效，平凡解 6 个（16%）。best = 热启动，无候选超越。
- 最佳演化候选 c5 = 0.3983：二值化后 SA。模型据此判断"分数值确实优于二值"（同网格 +4.6%）。
- 节点 5035fef2 得 0.412：GLOBAL_BEST_CONSTRUCTION 没传到该链，程序退回兜底帐篷解。
- 多个 reflection 指出：自写的 subgradient/SA 循环把热启动推坏。

## 结论
- 评估语义提示有效（平凡解 65% → 16%）。
- "二值化差距"是固定 N 的分辨率现象，不是问题本身的 gap：由 Swinnerton-Dyer 定理，分数值与二值最优值相等（`reports/problem_formulation.md` 定理 5.1、§8.3）。v4 据此取消二值化。
- 框架问题：shared construction 只在链内共享；prompt 以 6 位小数打印指标，看不到 1e-6 级改进。
- r4（732b13b … 10c424a：机械拒收常数解、qwen 深思考预算）从未运行，由 v4 取代。
