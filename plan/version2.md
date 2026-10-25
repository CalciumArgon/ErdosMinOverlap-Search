# Version 2：压缩热启动 + 可执行诊断（round 2）

- commit 区间：1b455b9 … 2a106b3（报告 `reports/erdos-A-round2-report.md`）
- 作业：erdos-A-v4pro-high-20260930（HPC，1.6 h，SUCCEEDED）

## 相对 v1 的改动
- init 把 2400 维热启动 ε-merge 压缩为 300 段 A 类 spec（c5 0.38094229）。
- 诊断新增 snap_hints、local_optimal、move_hint；MAX_SEGMENTS 512。
- 引擎与提示词不变。

## 结果
- 40 个候选：39 有效。best = 热启动，无候选超越；最佳演化 c5 = 0.381500（差 0.15%）。
- 26/40（65%）是 h≡1/2，比 v1 更差。根因假设：init 里的 `_default_spec()`（h≡1/2）进入每条 prompt，成为易抄的模板。
- 评测均值 14 s（20× 加速）；前排候选撞上 512 段上限。

## 结论
结构种子与评测成本问题解决，搜索仍停在热启动。平凡解陷阱成为主要浪费。v3 改回网格表示，以研究离散化本身。
