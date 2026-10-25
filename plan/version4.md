# Version 4 计划：Erdős minimum overlap meta-search

> 状态：计划已批准，实施中。基线 commit 10c424a；完成后的 commit 与结果见文末"结果"一节（待填）。

## Context

v1–v3 没有任何候选超过 warm start（c5=0.38086768），三轮的报告在 reports/ 下。r4 的深思考配置（origin/erdos-legacy-meta 的 cca57c0、97fbe6b）从未运行，由本版本替代。

本轮保持 AlphaEvolve 式 meta search 不变：LLM 进化"生成 h 的代码"。改动集中在 meta-meta 层：
- 任务语义；
- 链分工与信息流；
- 诊断信号；
- 深度预算与 API 健康监控。

用户新要求：
- (1) 把问题的完整逻辑链写成严格文档；
- (2) 不建新分支：version 对应 commit，并用文档记录各版本；
- (3) 换新 API 做非常深的搜索；API 故障必须早发现，并与"思考太久没写完"区分开。

### 关键理论结论（文档 §3–§5 给出完整证明）

**Swinnerton-Dyer 定理**（Haugland 1996 引用；Haugland 2016, arXiv:1609.08000 §1 重述）：μ := lim M(n)/n 存在，且等于 inf C(f)。下确界取在 [0,2] 上 [0,1] 值、∫f=1 的阶梯函数上；只取 0/1 值的阶梯函数，下确界也相同。

由此：
- evaluator 接受的任何合法网格数组，都是 μ 的严格上界。只剩浮点误差，用有理数精确复核即可消除。
- 不存在"分数值松弛 vs 二值"的最优值 gap：两个下确界相等。proof.md 留下的反向不等式由此解决。
- round 3 在同一网格上测到的二值化 +4.6%，是固定分辨率下的差距。它随分辨率 → ∞ 消失：随机舍入构造的误差是 O(√(log n / n))。
- "换 N 分数剧变"并不说明 bound 失效：重采样等于换了一个函数，而 np.repeat 上采样严格保持分数。
- 真正的 gap 只有两个：
  - 网格 gap：μ_N ≥ μ，沿加细单调不增并收敛到 μ；
  - 最优性 gap：C(f) − μ 未知。下界为 White 2022 的 0.379005，需要核实来源。

### 框架瓶颈（读代码确认，未在运行中验证）

1. **链间不共享。** shared construction 只在链内取最优（simpletes/engine/core.py:747-757）。
2. **提示里看不到小改进。** prompt 中的指标按 `:.6f` 打印（simpletes/generator.py:101-102），而有意义的改进在 1e-6～1e-5。
3. **API 失败白白消耗预算。** 失败的 LLM 调用照样计入 generation_attempts（scheduler.py:198-199，core.py:626-639），而且只打一行日志：API 出错会悄悄吃掉预算。
4. **超时类型无法区分。** 生成调用是同步的非流式 completion（litellm_client.py:111-134），超时时无法分辨"已在思考但没写完"和"压根没开始"。

## 0. Git 与版本管理（不建新分支）

- 现在的分支是 erdos-exact-evaluator，可以 fast-forward 到 origin/erdos-legacy-meta（已验证：HEAD 是它的祖先），把 r4 的两个 commit 并进来。
- 工作方式：
  - harness 要求编辑前隔离，所以用 detached worktree：`git worktree add --detach .claude/worktrees/v4 origin/erdos-legacy-meta`，再用 EnterWorktree(path) 进入。这不会产生新分支名。
  - 每个逻辑步骤一个 commit，用 `git push origin HEAD:erdos-exact-evaluator` 推送。
  - 主 checkout 再执行 `git merge --ff-only`。
  - qz 端用 `git pull` 同步。
- 注意：erdos-exact-evaluator 是远端默认分支。按你"就在这个分支上"的要求，直接推送到它。
- 版本文档放在 `plan/` 下：
  - `plan/README.md`：版本索引表，列出 version、commit id、evaluator/表示、配置、作业名、best c5、一句话结论；
  - `plan/version1.md` ~ `version3.md`：每份约 30 行，写结构、改动、结果、结论，并链接 reports/；
  - `plan/version4.md`：本计划。
- reports/report1020.html 目前未跟踪，一并提交，因为它是 v3 结论的来源之一。

## 1. `reports/problem_formulation.md`：完整逻辑链（每步给严格陈述或证明）

1. **原始问题**
   - 定义 {1..2n} 的等分 A ⊔ B，以及 M_k = #{(a,b) ∈ A×B : a − b = k}、M(n) = min_A max_k M_k。
   - 写出 M_k = Σ_x 1_A(x+k)·1_B(x) 的形式。
   - 列出平凡上下界与文献界（Haugland 2016、White 2022、AlphaEvolve、TTT-Discover），引用逐条核实。
2. **连续泛函**
   - f : [0,2] → [0,1]，∫f = 1，A_f(s) = ∫_{D_s} f(x)(1 − f(x+s)) dx，C(f) = sup_s A_f(s)。
   - 引理：C(f) ≤ 1/2（附证明）。
   - 对称群：反射 f(2−x)、补 1−f、两者复合都保持 C 不变（附证明）。
   - C 非凸：A_f(s) 中有 −f·f 项。
3. **L¹ 稳定性**：|C(f) − C(g)| ≤ 2‖f − g‖₁。沿用 proof.md 的证明。
4. **离散 ⇄ 连续的两个方向**
   - (a) 嵌入：A ↦ f_A(y) = 1_A(⌈ny⌉)，可得 C(f_A) = max_k M_k / n。
     - 其中证明阶梯函数的 A(s) 在 k/n 之间是线性的，所以 sup 在格点 shift 上取到。
     - 推出：对每个 n，M(n)/n ≥ inf_{0/1 阶梯} C ≥ inf_{[0,1] 阶梯} C。
   - (b) 随机舍入：给定 m 段阶梯 f，按格平均 p_x 独立取 X_x ~ Bernoulli(p_x)。
     - 偏差：E M_k 与 n·A_f(k/n) 之差 ≤ 2m（只有含断点的格子会有偏差）。
     - 集中性：翻转一位，M_k 至多变化 1。由 McDiarmid 加上对 4n+1 个 shift 取 union bound，并把 |A| 精确修正到 n，得到 M(n) ≤ n·C(f) + 2m + O(√(n log n))。
5. **定理（Swinnerton-Dyer，自证）**
   - 由 4(a)(b) 得 lim M(n)/n 存在，并且 = inf_{[0,1] 阶梯} C = inf_{0/1 阶梯} C = inf_{可测 f} C。最后一个等号由第 3 节加上阶梯函数的 L¹ 稠密性得到。
   - 推论：分数值与二值的最优值 gap 为 0。proof.md 中"反向不等式需另证"由此闭合。
6. **搜索问题**
   - 网格类 F_N = {v ∈ [0,1]^N, Σv = N/2}，μ_N := min C 在 F_N 上取到（紧集上连续函数）。
   - 性质：μ_N ≥ μ；μ_{rN} ≤ μ_N（repeat 嵌入）；μ_N → μ（格平均保质量，L¹ 误差 ≤ 2m·(2/N)）。
   - np.correlate 在 F_N 上精确，浮点误差另计。
   - 解释"换 N 剧变"：重采样等于换了一个函数，只有 repeat 保持分数。
7. **期望结构**（只写数学上必然的性质，不写猜测的形状）
   - 一阶必要条件（Danskin + 质量约束的拉格朗日）：局部极小处必有多个 active shift，或 active 方向的组合满足 0 ∈ conv。
   - 对称轨道：在反射、补变换下的解等价。
   - 质量约束下的可行方向。
8. **从搜索解恢复原问题**
   - 上界本身不需要恢复：μ ≤ C(h) 由第 5 节直接得到。
   - 若要显式等分：对 h 做 r 倍细化后按第 4(b) 节随机舍入，得到 M(n)/n ≤ C(h) + O(√(log n / n))。
   - 同时说明：固定格点上的二值化差距（round 3 的 +4.6%）随 n → ∞ 消失，不是问题本身的 gap。
9. **gap 汇总**
   - (G1) 浮点：精确有理数复核后为 0。
   - (G2) 网格：μ_N − μ ≥ 0，只影响可达值，不影响上界有效性。
   - (G3) 最优性：0 ≤ C(h) − μ ≤ C(h) − 已知下界。
   - (G4) 松弛：0（第 5 节）。
10. **与 proof.md 的对应**：哪些结论保留（Lipschitz、L¹ 稳定性、折点论证），哪些被取代（第二阶段二值化）。

proof.md 本身不改，只在开头加一行指向 problem_formulation.md。

## 2. 任务语义

**`datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt`**
- 删去"relaxation、不是原问题"一段，改为一句陈述：按 Swinnerton-Dyer 定理，合法数组就是 μ 的严格上界。
- 写明：
  - 分数对返回的阶梯函数精确；
  - repeat 上采样不改变分数；
  - 参照值 0.38086768，有意义的改进量级是 1e-6。
- 评测预算改为 3000 s，并明确鼓励把时间花在真正的数值搜索上。
- 继续不规定解的形状，也不提供工具（v4 决定）。

**reflection 模板**（`simpletes/policies/rpucg.py:42-57`）
- Insight 改为诊断搜索动力学：
  - 是否用了 warm start；
  - gap_to_reference；
  - 和参照解的结构距离（新结构还是微调）；
  - 时间用量；
  - 瓶颈在哪个组件；
  - 下一步改什么。
- 仍禁止描述"好解长什么样"。

## 3. 链分工：2 条探索链 + 2 条利用链（新增 `--explore-chains 2`）

**探索链**（chain_idx < 2）
- 评测时不注入 GLOBAL_BEST_CONSTRUCTION（None），init 程序退回中性兜底。
- prompt 中的 shared-construction 段（generator.py:288-296）换成："本链不提供 warm start；目标是从头构造并优化出新的结构"。
- 常数解已由 evaluator 机械拒绝。

**利用链**
- 新增 `--shared-construction-scope global`：任何链（包括探索链）上出现的节点只要刷新全局最优，就把它的 construction 推给所有利用链。改动在 core.py:747 一带。
- 文案相应改为 "current global-best"。

**选择器不改**：rpucg 的父代仍从本链节点中选。

## 4. 诊断指标（`evaluator_legacy.py` 的返回字典，会进入 prompt）

- `c5_str`：10 位小数。
- `gap_to_reference_e6` = (c5 − ref)×1e6。ref 由 env `ERDOS_REFERENCE_C5` 设置，负值表示新纪录。
- `used_warm_start`：evaluator 进程中能否拿到 GLOBAL_BEST_CONSTRUCTION。
- `returned_reference_unchanged`。
- `l1_to_reference`：返回函数与参照解之间的精确 L¹ 距离，取对称轨道（反射、补变换）上的最小值。用分段常数函数在公共断点上精确积分，计算量 O(N+2400)。这是描述性的新颖度指标，不带形状引导。
- `n_active_shifts`（tol 1e-9）、`n_points`。

## 5. API 健康监控（区分"慢"和"坏"）

**生成调用改为流式**
- 修改 `simpletes/llm/litellm_client.py:111-134` 的 `_worker_generate`，用 `stream=True` 累积 reasoning 与 content。
- 记录：首包时间、最后一包时间、reasoning 和 content 的字符数、finish_reason、usage、总耗时。

**每次调用按以下类别分类**

| 类别 | 判据 | 含义 |
|---|---|---|
| `api_no_start` | 连接、鉴权、4xx/5xx 异常，或首包超时（`--first-chunk-timeout`，默认 600 s，由 smoke 校准） | API 坏了，压根没开始生成 |
| `api_stalled` | 已有包，但超过 `--stall-timeout` 秒没有新包 | 中途断流，API 问题 |
| `timeout_mid_generation` | 一直在出包，但撞到总 `--timeout` | 预算太大或 timeout 太短 |
| `truncated_length` | finish_reason=length | 思考吃光了 max_tokens |
| `empty_content` | 正常结束但没有内容 | 输出为空 |
| `ok` | 其余情况 | 正常 |

**兜底：存活探针**
- 若 smoke 发现新 API 在思考阶段不推送 reasoning 流（首包要等思考结束），首包判据就失效。
- 此时由引擎每 5 分钟发一个 1-token 的 ping，并记录结果。
- 长调用期间若 ping 连续失败，按 `api_no_start` 或 `api_stalled` 处理。

**预算保护**
- API 类错误（`api_no_start`、`api_stalled`）退还 generation_attempts，按指数退避重排队。
- 连续 3 次 API 类错误时，暂停调度并写入 `API_ALERT`。
- 30 分钟内仍不恢复，就以非零退出码终止 run，避免空烧 24 h。
- `timeout_mid_generation` 和 `truncated_length` 照常计入预算，作为"深但没写完"单独统计。

**落盘与日志**
- 每次调用一行写入 `<instance>/api_health.jsonl`。
- 同时在 stdout 打印 `[API-HEALTH] <class> ...`，可以直接 `inspire hpc logs | grep` 查看。
- reflection 调用（非流式）的异常也走同一套分类。
- 开启 `--save-llm-io`，保留思考内容，用于分析是否出现了新结构。

## 6. 预算（新 API 待提供；数值由 smoke 实测后确定）

- 4 链，k=4，`--max-generations 80`（20 个 prompt，每链约 5 步）。
- `--gen-concurrency 16`：让每链 k=4 并行，同一时间 4 条链都有调用在跑。具体值取决于 smoke 测到的 API 并发上限。
- 思考预算尽量取 API 允许的最大值。
- `--timeout` ≈ 2×(思考预算 / 实测吞吐) + 余量。
- `--eval-timeout 3300`，`EVALUATOR_TIMEOUT_SECONDS=3000`。
- `--eval-concurrency 8`，HPC 配额 0,40,200。
- 若墙钟会超过 HPC 的 24 h 上限，用 `--resume` 从 checkpoint 续跑新作业。resume 在 smoke 中验证。
- 密钥只写在 qz 的 `.secrets/simpletes.env`，不进 git，也不在输出里回显。

## 7. 严格复核：`scripts/certify_erdos_grid.py`

- 把 float64 精确转成二进有理数，校验 0≤h≤1。
- 质量做有理数精确修正：只改一个有余量的格子，并报告修改量。
- 用 Python 大整数做 O(N²) 精确相关，输出有理数上界，以及向上取整的十进制值。

## 执行顺序（批准后）

1. 建 detached worktree 并 fast-forward。
2. 写 problem_formulation.md 和 plan/*，commit。
3. 写代码（§2–§7），commit 后推送到 erdos-exact-evaluator。
4. 你提供新 API key、base URL 和模型名。我写进 qz 的 secrets 文件，并改 run 脚本里的模型和 base。
5. qz 端执行 `inspire notebook connection refresh simpletes-prep`，再 exec `git pull`。
6. Smoke（notebook）：
   - (a) API 校准：ping；是否推送 reasoning 流；首包时间与吞吐；max_tokens 上限；4 路和 16 路并发；故意填错 key，应判为 `api_no_start`；故意设小 timeout，应判为 `timeout_mid_generation`。
   - (b) certify 能复现 0.38086768；repeat 不变性；新指标；常数解拒收。
   - (c) 迷你 run（1 探索链 + 1 利用链，小思考预算）：验证链分工、全局推送、api_health.jsonl 和 resume。
7. 正式 HPC 作业 `erdos-v4-<date>`。
8. 定时检查（ScheduleWakeup）：
   - 第 1 小时每约 10 分钟一次，专门抓 API 类错误；
   - 之后每 30–60 分钟一次。
   - 出现 `api_*` 或 `API_ALERT` 立即报告；深度超时类在阶段汇总里报告。
9. 结束后：certify best，写 reports/erdos-v4-report.md，补齐 plan/version4.md 的结果节，更新 plan/README.md 索引，commit 并 push。

## 关键文件

- 新增文档：reports/problem_formulation.md、plan/{README,version1..4}.md。
- 任务目录：datasets/erdos/erdos_min_overlap/{erdos_min_overlap.txt, evaluator_legacy.py}。
- 框架：
  - simpletes/llm/litellm_client.py（流式与分类）
  - simpletes/engine/{core.py, scheduler.py}（链分工、全局推送、退还预算、告警）
  - simpletes/generator.py:288-296
  - simpletes/policies/{rpucg.py, base.py}
  - simpletes/config.py、cli.py（新增 flag）
- 脚本：scripts/{run_erdos_v4.sh, smoke_v4.sh, certify_erdos_grid.py}。

## 验证

- 本地不运行任何代码。所有测试在 qz 上做（执行顺序第 6 步）。
- 成功判据：
  - smoke 全部通过，API 分类在人为制造的两类故障上都判对；
  - 正式 run 中 API 类错误被及时发现；
  - 理想结果：出现 gap_to_reference_e6 < 0 的候选，certify 后仍成立。
  - 次一级结果：探索链产出 l1_to_reference 大且 c5 有竞争力的新结构，作为下一版利用链的种子。
