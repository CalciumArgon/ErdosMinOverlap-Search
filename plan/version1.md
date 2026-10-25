# Version 1：A 类精确有理 evaluator（round 1）

- commit 区间：0386a4a … 76510d5（报告 `reports/erdos-A-round1-report.md`）
- 作业：erdos-A-v4pro-high-20260929（HPC，2.5 h，SUCCEEDED）

## 结构
- 程序返回 `(breaks, values)`：Fraction 断点与段值，m ≤ 64，分母 ≤ 2²⁰。
- evaluator 用折点引理精确扫描线求 sup，向上舍入得严格上界；分数 = 1/(1e-8+U)。
- 诊断写入 metrics：active_shifts、active_sensitivity、equioscillation_count。
- legacy 3 元组走 float 管线，用于热启动（2400 维论文解）。
- 框架：宽容 EVOLVE-BLOCK 抽取、rpucg 提示规则"只回代码块"。

## 配置
deepseek-v4-pro，reasoning_effort=high，max_tokens 131072；rpucg chains 4、k 4、max-generations 40；gen/eval 并发 4；评测上限 1100 s。

## 结果
- 40 个候选：0 拒收、0 超时、3 个非法。best = 热启动 0.38086768，无候选超越。
- 最佳演化候选 c5 = 0.385083。14/40（35%）是 h≡1/2（c5 = 0.5）。
- 评测均值 281 s：模型在构造里嵌入了长时间优化器。

## 结论
评测基建正确。主要瓶颈：热启动是 2400 维浮点程序，A 类表示里没有结构种子；诊断信号没被模型利用；平凡候选浪费预算。
