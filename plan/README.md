# 版本索引

规则：所有版本都在分支 `erdos-exact-evaluator` 上，每个 version 对应一段 commit 区间，不再另开分支。每个版本一份文档 `plan/versionN.md`，记录结构、改动、实验结果和结论。理论基础见 `reports/problem_formulation.md`。

| Version | 末 commit | 表示 / evaluator | 模型与配置 | 作业 | best c5 | 结论 |
|---|---|---|---|---|---|---|
| v1 | 76510d5 | A 类：Fraction 断点+段值，精确扫描线 | deepseek-v4-pro high；rpucg 4×4，40 gen | erdos-A-v4pro-high-20260929 | 0.38086768（= 热启动） | 评测基建正确；结构种子缺失，35% 候选是 h≡1/2 |
| v2 | 2a106b3 | A 类 + 压缩热启动 + 可执行诊断 | 同 v1 | erdos-A-v4pro-high-20260930 | 0.38086768（= 热启动） | 评测快 20×；平凡解升至 65% |
| v3 | cf57ae1 | legacy N 格数组，float correlate | qwen3.8-max，thinking 16384；rpucg 4×4，40 gen | erdos-legacy-qwen-r3c-20261015 | 0.38086768（= 热启动） | 评估语义提示把平凡解降到 16%；优化循环破坏热启动 |
| (r4) | 10c424a | 同 v3 + 机械拒收常数解 | qwen3.8-max thinking 122880（计划） | 未运行 | — | 被 v4 取代 |
| v4 | 待定 | 同 v3 + 新诊断指标 + 精确复核脚本 | claude-opus-5-5 xhigh；2 探索 + 2 利用链 | erdos-v4-（待定） | 待定 | 见 version4.md |

热启动 0.38086767582732667 来自 `best_results/mathematics_discovery/erdos_minimum_overlap/`（N=2400）。
