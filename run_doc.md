# SimpleTES 运行手册

> 落点任务：**Erdős minimum overlap**（`datasets/erdos/erdos_min_overlap/`）
> 目标运行环境：**Linux**
> 本文档由仓库代码静态阅读写成（`main.py` / `simpletes/**` / `datasets/erdos/**` / `best_results/**`）。
> 所有 flag 名、默认值、文件路径、行号引用均逐条回查源码。凡属推断的内容都显式标注了「推断」。

---

## 目录

1. [框架总览：什么是"程序空间搜索"](#1-框架总览什么是程序空间搜索)
2. [预算模型：C / L / K / Φ](#2-预算模型c--l--k--φ)
3. [环境与前置条件（Linux）](#3-环境与前置条件linux)
4. [模型与后端配置（两套对照）](#4-模型与后端配置两套对照)
5. [选择器 Φ 怎么选](#5-选择器-φ-怎么选)
6. [erdos 任务剖析](#6-erdos-任务剖析)
7. [推荐启动配方（两套）](#7-推荐启动配方两套)
8. [预测试与启动前 checklist](#8-预测试与启动前-checklist)
9. [运行预算与时间估算](#9-运行预算与时间估算)
10. [监控、checkpoint 与 resume](#10-监控checkpoint-与-resume)
11. [结果读取与后续探索](#11-结果读取与后续探索)
- [附录 A：完整 flag 速查表](#附录-a完整-flag-速查表)
- [附录 B：源码索引](#附录-b源码索引)

---

## 1. 框架总览：什么是"程序空间搜索"

SimpleTES 的范式是：**不生成解，而是生成"生成解的代码"**，然后让代码去跑出解。

具体到 erdos：LLM 写的不是那串 `h` 数组，而是 `construct_h()` 这个**函数**——一个能把 `h` 造出来的构造算法。evaluator 执行这段代码、拿到它产出的 `h`，再独立打分。

### 1.1 一次 step 的完整链路

一个 step 是"一个逻辑批次"（由 `gen_id` 标识），不是一个候选。链路如下（逐行核实）：

```
SchedulerMixin._scheduler_loop                 simpletes/engine/scheduler.py:266
  └─ _schedule_generation                      scheduler.py:173
       ├─ 预算检查：generation_attempts >= max_generations ? 停         scheduler.py:190
       ├─ _select_inspirations_and_prompt       scheduler.py:66
       │    ├─ selector.select(...)            → 挑历史 + 选链
       │    ├─ selector.get_policy_context(...) → 该链的策略上下文
       │    └─ generator.build_prompt(...)      → 拼出完整提示词
       ├─ generation_attempts += k                                   scheduler.py:199
       ├─ selector.register_batch(gen_id, chain_idx, insp_ids, k)    scheduler.py:122
       └─ 把 k 个 GenerationTask 推进 gen_queue                      scheduler.py:216
            │
            ├─ gen workers（gen_concurrency 个） 取任务 → 调 LLM
            │    └─ Generator.generate → LLMBackend.generate_batch(prompt, n=k)
            │         └─ 从输出里用 EVOLVE-BLOCK marker 抽出代码，拼回完整文件
            │
            └─ RuntimeBase.handle_generation_output   runtime.py:48
                 · 建 Node（parent_ids = 本批的 inspiration_ids → DAG 的边）
                 · 推入 eval_queue
                      │
                      └─ eval workers（eval_concurrency 个）
                           └─ EvaluatorWorker.evaluate(code)   独立子进程
                                · 写候选到 <eval_dir>/program.py
                                · python -c <runner> evaluator.py program.py
                                · 解析 stdout 末行 JSON
                           └─ SimpleTESEngine._commit_node      core.py:720
                                · 校验并加入 NodeDatabase
                                · 更新 best_score / 每链共享构造
                                · 触发 checkpoint（按 log_interval）
                                · selector.on_child_done(node, parents)
                           └─ selector.finalize_batch           policies/base.py:451
                                · 全部 k 个子节点完成后收尾
                                · 生成 reflection（每个批次一次额外 LLM 调用）
                                · 只把本批胜者提交进 chain
```

### 1.2 三个容易混淆的概念

| 概念 | 是什么 | 存在哪 |
|------|--------|--------|
| **Node** | 一个被评测过的完整程序 | `NodeDatabase`，**存全部**（含每批的 k 个失败候选） |
| **chain** | 一条演化轨迹的历史 | `TrajectoryPolicyBase.chains[c]`，**只存每批胜者** |
| **batch** (`gen_id`) | 一次 prompt → k 个候选的一组 | `policy._batches`，k 个孩子全部结束才关闭 |

关键区别：**数据库里有所有程序，链里只有赢家。** 所以 `--k-candidates 4` 时你花了 4 次评测，链上只记 1 步。这也是为什么 `--max-generations` 和"链的步数"不是一回事（见 §2）。

DAG 的边是**隐式**的：`Node.parent_ids` 就是产生它的那批 `inspiration_ids`（`runtime.py:59`），一个节点可以有多个父节点。六个选择器里**只有 `rpucg` 真的去走这个图**（`policies/rpucg.py:100` 的 `_build_children_map`）。

### 1.3 EVOLVE-BLOCK：唯一允许改的区域

`EvolveBlockContext.from_program`（`utils/code_extract.py:58`）把 init program 切成三块：

```
prefix  = 文件开头 → 直到并包含 "# EVOLVE-BLOCK-START" 那一行
evolved = LLM 生成的内容
suffix  = 从 "# EVOLVE-BLOCK-END" 那一行 → 文件结尾
最终文件 = f"{prefix}\n{evolved}\n{suffix}"
```

含义：**块外的代码 LLM 永远动不了**，而且会被原样贴进提示词。这对 erdos 特别重要——`run_code()` 里的 box-sum 投影和 `np.correlate` 计算是固定的，LLM 只能改 `construct_h()`。

两个硬性行为：

- init program **没有 marker 会直接 `SystemExit(2)`** 终止（`engine/core.py:186-191`）。
- LLM 输出里找不到 marker 的话，这次生成被丢弃，理由记为 `missing_evolve_block_markers` / `empty_evolve_block` / `no_code_block` 等（`utils/code_extract.py:157`）。

### 1.4 文件地图

| 路径 | 职责 |
|------|------|
| `main.py` | CLI 入口：解析 → 校验 → 准备任务 → 预检 → 建引擎 → 跑 |
| `main_wizard.py` | 交互式启动器（见 §8.4 的注意事项） |
| `simpletes/cli.py` | 全部 argparse 定义 |
| `simpletes/config.py` | `EngineConfig` dataclass + 参数合理性警告 + venv 解析 |
| `simpletes/engine/core.py` | `SimpleTESEngine`：状态、提交、checkpoint、resume |
| `simpletes/engine/scheduler.py` | 调度循环 |
| `simpletes/engine/runtime.py` | 队列与 worker 生命周期 |
| `simpletes/engine/checkpoint.py` | 落盘与加载 |
| `simpletes/generator.py` | 提示词拼装、代码抽取 |
| `simpletes/evaluator.py` | `EvaluatorWorker`：子进程隔离与超时 |
| `simpletes/policies/` | 六个选择器 |
| `simpletes/llm/` | 两个后端：`litellm_client.py` / `vllm_forcing.py` |
| `simpletes/construction.py` | 跨进程共享构造（`GLOBAL_BEST_CONSTRUCTION`） |
| `simpletes/templates/` | 提示词模板 |
| `sitecustomize.py` | 仓库根目录的钩子，自动把共享构造装成 builtin（见 §7.2） |

---

## 2. 预算模型：C / L / K / Φ

README 把四个杠杆抽象成 C / L / K / Φ。落到代码上是：

| 杠杆 | 含义 | 对应 flag | 默认 |
|:----:|------|-----------|:----:|
| **C** | 并行探索的链数 | `--num-chains` | 4 |
| **K** | 局部 best-of-K | `--k-candidates` | 4 |
| **Φ** | 历史→提示词策略 | `--selector` | `balance` |
| **L** | 每条链的细化深度 | *无独立 flag*，由总预算推出 | — |

### 2.1 ⚠️ 坑 1：`--max-generations` 计的是**候选数**，不是 prompt 数

CLI 的 help 文案写的是 *"Number of generation prompts to schedule"*（`cli.py:38`），但代码实际做的是：

```python
# scheduler.py:198-199
self.generation_attempts += k      # k = k_candidates，不是 +1
```

所以 `--max-generations 100 --k-candidates 4` 实际是 **100 个候选**，也就是 25 个 prompt。按 help 文案理解会把预算估错 K 倍。

### 2.2 L 是怎么算出来的

`_policy_summary`（`engine/core.py:227-246`）：

```python
chains      = max(1, num_chains)
base        = max_generations // chains          # 每链候选配额
rem         = max_generations %  chains
base_prompt = ceil(base / k_candidates)          # ← 这就是 L
extra_prompt= ceil((base+1)/k) - base_prompt     # 前 rem 条链多一步
```

即 **`L = ceil(max_generations / num_chains / k_candidates)`**（对前 `rem` 条链是 `L+1`）。

启动时会把这行打出来，可以直接对账：

```
chains=4, local_bon(k)=4, prompts/chain=7
```

### 2.3 成本换算表

设 `M = --max-generations`、`C = --num-chains`、`K = --k-candidates`、`N = --num-inspirations`：

| 量 | 公式 | 默认值（M=100, C=4, K=4, N=5） |
|----|------|:---:|
| 生成的候选数 = 评测次数 | `Σ_c ceil(chain_budget[c]/K)·K` ≈ M | 112 |
| prompt 批次数 | ≈ M / K | 28 |
| LLM 生成调用 | ≈ 候选数（`stream_k_candidates` 默认 True，每个候选一次调用） | 112 |
| reflection 调用 | = 批次数（`reflection_mode` 默认开启，`config.py:230`） | +28 |
| LLM 策略额外调用 | `llm_*` 三个选择器 +1/批次，且**同步阻塞调度循环** | +28 |
| 评测子进程 | 候选数 + `--init-eval-repeats` | 112 + 16 = 128 |
| 实际并发批次数 | ≈ C（`--backpressure-multiplier 0` 时） | 4 |

> `--num-inspirations`（N）不影响调用次数，只影响提示词长度。N 越大，每个候选携带的上下文越丰富，token 成本越高。N=0 会切到"静态提示词模式"，此时**强制要求 `--num-chains 1`**，否则直接 `ValueError`（`engine/core.py:171-174`）。

---

## 3. 环境与前置条件（Linux）

### 3.1 必需的软件

| 项 | 要求 | 依据 |
|----|------|------|
| Python | **≥ 3.11** | `pyproject.toml` 的 `requires-python` |
| 包管理器 | `uv`（推荐）或 `pip` | README Quickstart |
| 依赖安装 | `uv sync`；可选 `uv sync --extra vllm` | README |
| erdos 任务依赖 | **仅 `numpy`** | `datasets/erdos/README.md` |
| GPU | **不需要** | erdos evaluator 纯 CPU |
| 编译器 / 网络 / 容器 | **不需要** | erdos 自包含，无下载 |

安装后：

```bash
uv sync                  # 基础依赖
uv sync --extra vllm     # 可选：vLLM token-forcing 后端
```

### 3.2 为什么必须跑在 Linux 上

**这是本任务最硬的约束。** `datasets/erdos/erdos_min_overlap/evaluator.py` 依赖三个 POSIX-only 的东西：

| 位置 | 代码 | 后果 |
|------|------|------|
| `evaluator.py:30` | `import resource`（模块顶层，无保护） | 在 Windows 上抛 `ModuleNotFoundError` |
| `evaluator.py:178-188` | 子进程脚本里的 `import resource` + `resource.setrlimit(RLIMIT_AS/RLIMIT_DATA)` | 子进程直接崩，结果文件不生成 |
| `evaluator.py:282` | `os.killpg(os.getpgid(pid), SIGKILL)` | POSIX-only，超时清理路径不可用 |

框架侧的失败模式很隐蔽：`_EVAL_RUNNER`（`simpletes/evaluator.py:77`）用 `exec_module` 加载 evaluator，模块顶层一抛异常就打印 `{"error": ..., "combined_score": -inf}` 并 `exit(1)`。于是：

- 搜索流程**能正常启动**，日志看起来一切正常；
- 但**每一次评测**都是 `combined_score = -inf`；
- `validate_node_for_db`（`node.py:123`）要求 `combined_score` 有限，所以每个节点都被丢弃；
- 结果是 `evaluation_failures` 一路涨，`best_score` 永远是 `-inf`，**跑多久都不会有任何进展**。

在 Linux 上这三处全部正常，无需任何改动。

> 顺带一提：框架自身的 `_kill_process_group`（`simpletes/evaluator.py:143-154`）**有** Windows 回退（捕获 `OSError` 后退到 `proc.kill()`）。所以问题不在框架，只在 erdos 这个任务的 evaluator。

### 3.3 评测子进程用哪个 Python

`resolve_eval_python`（`config.py:91-108`）的优先级：

1. `--eval-venv <dir>`（显式指定，会做严格校验，路径不存在直接 `parser.error` 退出）
2. 自动探测 `<task_dir>/venv`
3. 都没有 → `sys.executable`（即跑 `main.py` 的那个解释器）

`<task_dir>` 的推导在 `task_dir_from_evaluator_path`（`config.py:50-88`）：向上找最近的名为 `datasets` 的祖先，再取**第一段路径**。对 `datasets/erdos/erdos_min_overlap/evaluator.py` 来说，结果是 **`datasets/erdos`**（family 层，不是 subtask 层）——这样同一个 venv 可以给该 family 下所有子任务共用。

**erdos 没有任何 task-local venv**（`datasets/erdos/venv` 和 `datasets/erdos/erdos_min_overlap/venv` 都不存在），所以默认走 `sys.executable`。这意味着：**跑 `main.py` 的环境必须自己能 `import numpy` 和 `import psutil`。**

> 如果日后你为 erdos 建了 venv（`datasets/erdos/venv`），框架会自动发现它。但注意 `task_dir` 是 family 层，所以那个 venv 会被 erdos 家族下所有任务共用。

### 3.4 erdos 不需要任何"准备"步骤

`datasets/erdos/` **没有 `data_manifest.json`**，所以：

- `uv run python scripts/prepare_task.py --list` **不会列出 erdos**（该脚本只遍历有 manifest 的 family：`ahc / astrodynamics / numerical_tasks / open_problems_bio / scaling_law / zapbench / znaa`）；
- `python scripts/prepare_task.py --task erdos` 会直接报 `No manifest found for task 'erdos'.` 并退出码 1；
- `main.py` 启动时的 `check_and_prepare_task`（`utils/task_prep.py:159`）发现没有 manifest 就立即返回，什么都不做。

**结论：erdos 无需 prepare，不要跑那个命令。**

---

## 4. 模型与后端配置（两套对照）

SimpleTES 支持两个 LLM 后端，由 `--llm-backend` 选择（`cli.py:263-269`，默认 `litellm`）。

### 4.1 两套配置对照

| | **A. 论文配置**（gpt-oss + vLLM） | **B. 商业 API**（LiteLLM） |
|---|---|---|
| `--llm-backend` | `vllm_token_forcing` | `litellm`（默认，可省略） |
| `--model` | 你部署的 gpt-oss 模型名 | `provider/model`，如 `gemini/gemini-2.0-flash` |
| 端点 | `--api-base` 指向自建 vLLM（客户端默认 `http://127.0.0.1:18000/v1`） | 省略（用 provider 默认），或 `--api-base` 指向代理 |
| 凭据 | 本地端点通常不需要 | `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / … |
| 额外参数 | `--context-window`、`--response-budget`、`--reasoning-budget` | `--reasoning-effort`（仅对含 `gpt-oss` 的模型名生效） |
| 与论文的关系 | **这是论文原配置** | 更省事，但严格说**不是**原配置 |
| 适用场景 | 追求贴近论文 / 大批量省钱 | 快速验证、上游模型能力更强 |

### 4.2 凭据是怎么解析的

**重要事实：`simpletes/` 里没有任何读环境变量的代码。** 解析顺序是：

1. `--api-key` / `--api-base` 命令行参数 → 存进 `config`；只有非 `None` 时才会透传给 litellm（`llm/litellm_client.py:227-230`）
2. 否则由 **LiteLLM 自己**按 provider 查它的环境变量（`GEMINI_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` …）
3. `main_wizard.py` 额外会读仓库根的 `keys/openai_api_base` 和 `keys/openai_api_key` 两个文件，**仅作为交互提示的默认值**（该目录被 gitignore，当前不存在）

模型字符串格式就是 LiteLLM 的 `provider/model`，仓库不做任何解析或校验，原样传给 `litellm.completion(model=...)`。

**建议把 key 放环境变量**，不要写进命令行——`--api-key` 会出现在 shell history 和 `ps` 里。

### 4.3 preflight（启动前 1-token ping）

`main.py:95-132`。**只对 `litellm` 后端生效**；`vllm_token_forcing` 会直接跳过。

- 成功：静默通过。
- 失败：打印红色面板（model / api base / 错误类型 / 消息）并 **`sys.exit(2)`**。
- 绕过：`--skip-preflight`（本地后端还在启动时有用）。

### 4.4 LLM 类选择器的额外配置

如果你用 `llm_elite` / `llm_puct` / `llm_rpucg`，它们会**额外**发起 LLM 调用，用的是独立的配置：

| flag | 默认 |
|------|------|
| `--llm-policy-model` | 回退到 `--model` |
| `--llm-policy-api-base` | 回退到 `--api-base` |
| `--llm-policy-api-key` | 回退到 `--api-key` |
| `--llm-policy-pool-size` | `llm_elite` 默认 15；`llm_puct`/`llm_rpucg` 默认 20 |

另外 **reflection 默认是开启的**（`--disable-reflection` 未给时 `reflection_mode=True`，`config.py:230`），它对**所有**链式选择器都生效，每个批次多一次 LLM 调用，走的也是 `llm_policy_*` 配置。

---

## 5. 选择器 Φ 怎么选

`uv run python main.py --list-policies` 输出（`cli.py:367-373`，按字母序）：

```
Available inspiration policies:
  - balance
  - llm_elite
  - llm_puct
  - llm_rpucg
  - puct
  - rpucg
```

| 选择器 | 机制 | 需要的额外 flag | 备注 |
|--------|------|-----------------|------|
| `balance` | 分层采样：必含链内最优 + 按比例从 elite / mid / 全体抽 | `--exploitation-ratio` `--exploration-ratio` `--elite-ratio` | 默认；低配置探索最稳 |
| `puct` | PUCT 打分 `Q + c·scale·P·sqrt(1+T)/(1+n)` 取 top-n | `--puct-c` | 树搜索风味 |
| **`rpucg`** | **DAG 感知**：`V(s)=max(raw, γ·max_child V)` 全图反向传播 + 反近亲贪心选择（排除已选节点的 1-hop 邻域） | `--puct-c` `--rpucg-gamma` | **README 标注 "Paper-style; strongest single selector"** |
| `llm_elite` | 每链维护有界 elite 池，由 LLM 决定 ADD / REPLACE / REJECT | `--llm-policy-pool-size` `--elite-selection-strategy` + LLM 配置 | 需要 LLM 调用 |
| `llm_puct` | PUCT 预筛 → LLM 重排 | 同上 + `--puct-c` | 噪声链适用 |
| `llm_rpucg` | RPUCG 预筛 → LLM 重排 | 同上 + RPUCG 参数 | DAG 历史丰富时适用 |

### ⚠️ `rpucg` 走的是另一条提示词路径

`generator.py:303-322`：当 `selector == "rpucg"` 时，提示词**完全绕开模板**——没有 policy context 段，没有 `=== REFERENCE SOLUTIONS ===` / strategy 块。失败模式的呈现方式也不同（`format_failure_patterns_inline` 而非分块模板，`generator.py:272-275`）。reflection 也用独立的 `RPUCG_REFLECTION_PROMPT_TEMPLATE`。

**含义**：换选择器不只是换"挑哪些历史"，提示词结构本身也会变。切换 `balance` ↔ `rpucg` 的差异比字面看起来大得多。

### 参数校验

`--selector` **没有** argparse 的 `choices=`，是运行时校验（`cli.py:419-425`）。名字打错会在启动早期 `exit(1)` 并提示 `--list-policies`。

另外 `examine_args`（`config.py:291-419`）会发一堆**警告但不中断**，值得留意：

- `max_generations < num_chains` → 部分链配额为 0
- `gen_concurrency + eval_concurrency > CPU 核数` → 提示可能过载
- `--log-interval <= 0` / `--db-show-interval <= 0` → 分别关闭周期性 checkpoint / DB 面板

---

## 6. erdos 任务剖析

### 6.1 数学问题

求阶梯函数 `h: [0, 2] → [0, 1]`，**最小化**

```
C₅ = max_k ∫ h(x)·(1 − h(x+k)) dx
```

约束：

1. `h(x) ∈ [0, 1]` 对所有 x
2. `∫₀² h(x) dx = 1`

离散化后（`n_points` 个采样点，`dx = 2.0/n_points`）：`0 ≤ h[i] ≤ 1` 且 `sum(h) == n_points/2` **精确相等**。

### 6.2 三件套文件

| 文件 | 作用 |
|------|------|
| `datasets/erdos/erdos_min_overlap/init_program.py` | 种子。EVOLVE-BLOCK = **第 1-19 行**（`import numpy` + `construct_h()`）；`run_code()` 在块外，固定不可改 |
| `datasets/erdos/erdos_min_overlap/evaluator.py` | 评测：独立重算 C₅ 并校验自报值 |
| `datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt` | 展示给模型的指令 |

**种子当前长什么样**（`init_program.py:4-17`）：`h ≡ 0.5` 加零均值均匀噪声 `U(-0.4, 0.4)`，`n_points ~ U{40..99}`。实测这版种子的 `C₅ ≈ 0.507`，`combined_score ≈ 1.97`——远不如论文最终解。

**块外固定部分**（`init_program.py:22-66`）做了两件事，LLM 改不了：

1. `_project_box_sum(v, n/2)`：80 步二分求 τ，把 `clip(v-τ, 0, 1)` 投影到 `{0≤h≤1, Σh = n/2}`
2. 用 `np.correlate(h, 1-h, mode="full") * dx` 算 `max` 作为 `c5_bound` 返回

所以**即使 LLM 返回的 `h` 不满足约束，也会被自动投影**——但 `n_points` 必须是 `int`，`h.shape[0]` 必须等于它。

### 6.3 评分与防作弊

```python
# evaluator.py:355
combined_score = 1.0 / (1e-8 + c5_value)      # 越大越好
```

HACK-PROOF 设计（`verify_c5_solution`，`evaluator.py:68-124`）：

- evaluator **独立重算** C₅，不信任程序自报的值；
- 自报值必须与重算值在 `atol=1e-8` 内一致，否则 `ValueError`；
- `h` 必须是 1-D、长度等于 `n_points`、全有限、**全部在 `[0,1]` 内（无容差）**；
- 若 `sum(h) != n/2`，按比例缩放；缩放后越界则拒绝。

失败时返回 `{"c5": inf, "validity": 0.0, "combined_score": 0.0, "error": ...}`，**永不抛异常**（`evaluate()` 外层有兜底 `except`）。

> 文档与代码的小出入：`evaluator.py:10` 的 docstring 写 "tolerance: 1e-4"，实际代码用的是 `atol=1e-8`（`:121`）。以代码为准。

### 6.4 两层超时

| 层 | 位置 | 默认值 |
|----|------|:---:|
| 内层（任务自己的子进程超时） | `evaluator.py:47` `TIMEOUT_SECONDS`，可被环境变量 `EVALUATOR_TIMEOUT_SECONDS` 覆盖 | **1100 s** |
| 外层（框架硬杀） | `--eval-timeout`（`config.py:129`） | **3000 s** |

`.txt` 里告诉模型的是 1100 s，和 `TIMEOUT_SECONDS` 一致。**内层必须小于外层**，否则外层先杀，你只会看到 `{"error": "timeout"}` 而拿不到任务自己的诊断信息。

框架**从不设置** `EVALUATOR_TIMEOUT_SECONDS`，它只是被 `os.environ.copy()` 传递——也就是说这是给你在命令行前置环境变量用的覆盖点。

### 6.5 其它可调环境变量（erdos evaluator 自己读的）

| 环境变量 | 默认 | 含义 |
|----------|:---:|------|
| `EVALUATOR_TIMEOUT_SECONDS` | 1100 | 单次评测超时 |
| `EVALUATOR_CONCURRENT_PROCESSES` | **64** | 用于算每进程内存上限：`0.9 × 总RAM / 该值` |
| `EVALUATOR_OS_BUFFER_PERCENT` | 0.10 | 保留给 OS 的内存比例 |

`EVALUATOR_CONCURRENT_PROCESSES` 默认 64 是按"64 个进程并发"设计的。如果你实际只跑 8 路并发，每个进程只能拿到 `0.9×RAM/64` 的内存上限——**白白浪费**。建议把它设成你的 `--eval-concurrency`，让内存上限匹配真实并发。

### 6.6 论文结果

| 量 | 值 | 来源 |
|----|----|------|
| `Ψ(h)` = `C₅` | **0.38086767582732667** | `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json` |
| `combined_score` | **≈ 2.62558** | **换算得出** `1/(1e-8 + 0.38086767582732667)`，该值仓库未存 |
| 解的形状 | `n_points = 2400` | 同一 JSON |

论文那份最解的程序在 `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best.py`（478 行），是一个七阶段流水线：Paley 构造热启动 → 供体-受体随机交换 → 光滑 max 代理上的 Adam → 针对最差位移的引导交换 → 二值化 → 二值最优交换 → 模拟退火。它自限 `max_time = 1080.0` 秒（给 1100 s 留 20 s 余量）。

> `combined_score` 这个换算值是本文档算的，不是仓库里存的。`best_results` 下**没有**任何元数据 sidecar（无模型名、无预算、无选择器、无链数）。

### 6.7 ⚠️ 坑 2：`requirements.txt` 会向模型撒谎

`datasets/erdos/requirements.txt` 内容如下：

```
# Task-local requirements for circle_packing evaluator env (see pyproject.toml).
numpy
scipy
scikit-learn
cvxpy[CBC,CVXOPT,GLOP,GLPK,GUROBI,MOSEK,PDLP,SCIP,XPRESS,ECOS]
psutil
```

这是**从 `circle_packing` 抄来的残留**（连注释头都没改）。而 `load_task_requirements(datasets/erdos)` 会读它，并把包名列表**注入提示词**：

```
Available packages from requirements.txt (these are the task-local dependencies you can use):
- numpy
- scipy
- scikit-learn
- cvxpy[...]
- psutil
```

`generator.py:277-285`。

**问题**：erdos 实际只需要 `numpy`。评测子进程用的是 `sys.executable`（没有 task-local venv），scipy/sklearn/cvxpy **不一定装了**。模型看到"你可以用 scipy"，就会写 `import scipy` 的代码 → 评测直接失败 → 白白烧掉一次评测（在 erdos 上可能值十几分钟）。

**可选修复**：把该文件裁剪成只列实际可用的包（至少 `numpy`，如果确实装了再加 `psutil`）。这会改变给模型的提示词，属于有意的行为改动，请自行决定。

---

## 7. 推荐启动配方（两套）

> **关于"贴近论文"的诚实声明**
> 仓库里**没有**记录 erdos 原始实验的预算、链数、选择器（`best_results` 下无元数据）。下面配方中的 `--num-chains 4` / `--k-candidates 4` / `--num-inspirations 5` 是 `EngineConfig` 的默认值，`--selector rpucg` 依据 README 的 "Paper-style; strongest single selector"。**这些是推断，不是实证。** 真正确定的只有：任务三件套、评分公式、1100 s 超时、以及论文最终得分 0.380868。

### 7.1 配方 A：基线（不启用共享构造）

最干净、依赖最少，适合先把链路跑通。

```bash
export GEMINI_API_KEY=...        # 换成你实际用的 provider

uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator    datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction  datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model        gemini/gemini-2.0-flash \
  --selector     rpucg \
  --num-chains   4 \
  --k-candidates 4 \
  --max-generations 40 \
  --eval-concurrency 8 \
  --output-path  checkpoints/erdos-A
```

要点：
- `--max-generations 40` ⇒ 40 个候选（**不是** 40 个 prompt）。按 §2.2：`L = ceil(40/4/4) = 3` 步/链。
- `--eval-concurrency 8` 要配合 `EVALUATOR_CONCURRENT_PROCESSES=8`（见 §6.5）。
- `--selector rpucg` 需要 `--puct-c` / `--rpucg-gamma`，用默认值 `0.5` / `0.8` 即可。

### 7.2 配方 B：共享构造热启动

在配方 A 基础上加两个东西：

```bash
export EVALUATOR_CONCURRENT_PROCESSES=8

SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json \
uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator    datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction  datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model        <your-gpt-oss-endpoint-model> \
  --api-base     http://127.0.0.1:18000/v1 \
  --llm-backend  vllm_token_forcing \
  --selector     rpucg \
  --num-chains   4 \
  --k-candidates 4 \
  --max-generations 40 \
  --eval-concurrency 8 \
  --include-construction \
  --output-path  checkpoints/erdos-B
```

#### 机制说明（这部分是全文最需要小心的）

共享构造的完整链路：

```
evaluator 调 capture_construction_if_requested(solution)      datasets/erdos/.../evaluator.py:353
   → 写 <eval_dir>/captured_construction.json
   → 框架读回，若 include_construction 为真则存为该链的共享构造   engine/core.py:748-757
   → 下一次评测时通过 SIMPLETES_SHARED_CONSTRUCTION_PATH 传下去  evaluator.py:160-161
   → 仓库根的 sitecustomize.py 自动执行 install_global_from_env()
   → builtins.GLOBAL_BEST_CONSTRUCTION = 解码后的构造           construction.py:190-191
   → 被评测的程序可以读这个全局变量
```

**关键兼容性**：解码器**显式兼容旧 tag**——`construction.py:30-34` 的注释明确写了保留 legacy `__simpleevolve_type__` 就是"so that pre-rename JSON artifacts (e.g. those shipped in `best_results/`) round-trip"。而 `erdos_minimum_overlap_best_construction.json` 用的正是这个旧 tag。所以**那份文件可以直接当种子喂进去，无需转换**。

#### ⚠️ 坑 3：种子会被无声吞掉

`SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH`（`engine/core.py:16`）只在**从零启动时 init program 那一次评测**里被使用（`:496-500`）：

```python
initial_shared_path = os.environ.get(_INITIAL_SHARED_CONSTRUCTION_ENV)
outcomes = await asyncio.gather(*[
    self._evaluate_code(code, shared_construction_path=initial_shared_path)
    for _ in range(repeats)
])
```

紧接着（`:522-526`），如果 `--include-construction` 开着且 init program 这次评测也 capture 了构造：

```python
if self.config.include_construction and outcome.captured_construction_payload is not None:
    self._set_shared_construction_for_all_chains_locked(...)
```

**当前仓库的种子 `init_program.py` 根本不读 `GLOBAL_BEST_CONSTRUCTION`**（它的 `construct_h()` 只有随机噪声）。所以：

1. 你喂进去的那份 0.380868 的解，被 init program 无视；
2. init program 自己产出的那个 `C₅ ≈ 0.507` 的平庸构造被 capture；
3. 该平庸构造**覆盖到所有链**，成为后续演化的起点。

**净效果：你精心准备的种子被静默丢弃了，而且换成了一份更差的。**

#### 让配方 B 真正生效的两种做法

**做法 1（推荐，改动最小）**：把 seed 改造成会读全局变量。在 `init_program.py` 的 EVOLVE-BLOCK 内加一段热启动逻辑，例如：

```python
def construct_h():
    try:
        global GLOBAL_BEST_CONSTRUCTION
        if GLOBAL_BEST_CONSTRUCTION is not None:
            prev_h, _, prev_n = GLOBAL_BEST_CONSTRUCTION[:3]
            prev_h = np.asarray(prev_h, dtype=np.float64).reshape(-1)
            if int(prev_n) == prev_h.size:
                return prev_h.copy(), int(prev_n)
    except Exception:
        pass
    # ... 原来的随机构造作为 fallback
```

这样 init program 自己就会从论文解出发，而且它 capture 的也是这份好构造，链条自洽。

**做法 2（"续跑"模式）**：直接拿论文那份程序当种子：

```bash
--init-program best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best.py
```

那份程序**已经**会读 `GLOBAL_BEST_CONSTRUCTION`，并且有 Paley-599 的 fallback（`erdos_minimum_overlap_best.py:76-110`）。注意它的 EVOLVE-BLOCK 覆盖前 430 行，整条七阶段流水线都是可演化区域。

> ⚠️ 做法 2 的一个实际代价：那份程序自限 `max_time = 1080.0` 秒。而 `--init-eval-repeats` 默认 **16**，意味着启动瞬间会并发起 **16 个各跑 18 分钟**的子进程。第一次跑之前请务必把 `--init-eval-repeats` 降到 1-2，或者先确认机器扛得住。
>
> 同理，无论用哪个配方，只要演化出的程序趋近最优，单次评测就会逼近 1100 s——见 §9。

---

## 8. 预测试与启动前 checklist

### 8.1 零成本静态检查

```bash
# 1) 选择器名单（不加载模型、不联网）
uv run python main.py --list-policies

# 2) 完整 flag 列表
uv run python main.py --help
```

### 8.2 不花钱的启动检查

```bash
# 3) 只验证 LLM 凭据（1 token ping），会真实发一次请求
uv run python main.py ...（完整参数）...
#    如果 preflight 失败会 exit(2) 并打印原因；本地后端未就绪时用 --skip-preflight 绕过

# 4) 打印提示词前 N 行，肉眼确认拼装正确（尤其确认 requirements.txt 那段和共享构造那段）
uv run python main.py ... --debug-prompt-lines 80
```

`--debug-prompt-lines N`（`generator.py:340-346`）会输出前 N 行，是**验证提示词是否符合预期最省事的手段**。建议至少跑一次，重点看：

- 任务指令是否正确嵌入；
- `Available packages from requirements.txt` 那一段是否列出了你实际装了的包（见 §6.7 坑 2）；
- 开了 `--include-construction` 时，`Shared runtime variable available in the evaluated program` 那段是否出现。

### 8.3 推荐的冒烟方式：先做一个"快评测"副本

erdos 的真实评测可能长达 18 分钟，用它做冒烟测试极其昂贵（而且如果 evaluator 有问题，你要等 18 分钟才知道）。

**建议**：复制一份任务目录到临时位置，把 evaluator 的 `TIMEOUT_SECONDS` 调小（比如 30），并把 `init_program` 的构造改得极简单，用它跑 `--max-generations 4`，确认端到端链路（调度 → LLM → 抽取 EVOLVE-BLOCK → 子进程评测 → 提交 → checkpoint 落盘）全部打通，**再**切回真任务。

这样能在几分钟内、几乎零成本地验证：

- LLM 后端和提示词拼装正常；
- EVOLVE-BLOCK 抽取成功（不会出现 `missing_evolve_block_markers`）；
- **evaluator 在目标 Linux 机器上能正常 import 并返回有限分数**（这一步能立刻暴露 `resource` 之类的环境问题）；
- checkpoint 目录和文件都按预期生成。

### 8.4 关于 `main_wizard.py`

交互式启动器，能自动发现任务（glob `datasets/*/*/init_program.{py,rs,cpp}`）、提示模型与预算、最后打印或直接执行命令。**但它有两个限制**：

- 选择器列表是**硬编码**的 6 个名字（`main_wizard.py:39`），与实际的注册表解耦；
- 它**不会**发出 `--puct-c` / `--rpucg-gamma` / `--llm-policy-*` / `--eval-venv` / `--resume` / `--early-stop-score` / `--gzip` / `--save-llm-io` / `--include-construction` / `--skip-preflight` 这些 flag。要加只能靠命令行尾部的额外参数透传。

所以**建议直接用 CLI**（§7 的配方），把 wizard 当成"发现任务名"的便利工具即可。

### 8.5 启动前 checklist

| # | 检查项 | 怎么确认 |
|---|--------|----------|
| 1 | 跑在 **Linux** 上 | `uname`；Windows 上 erdos 必然全 0 分（§3.2） |
| 2 | Python ≥ 3.11 | `python -V` |
| 3 | `uv sync` 已执行，`import numpy, psutil, litellm` 都成功 | 用**跑 main.py 的那个解释器**测（就是评测子进程用的那个） |
| 4 | LLM 凭据可用 | 不加 `--skip-preflight` 跑一次，看是否 exit(2) |
| 5 | 模型名 / `--api-base` 正确 | preflight 面板会回显 |
| 6 | 三个路径存在 | `--init-program` / `--evaluator` / `--instruction`，启动时也会打 WARN |
| 7 | `EVALUATOR_CONCURRENT_PROCESSES` 匹配 `--eval-concurrency` | 否则内存上限不合理（§6.5） |
| 8 | `--eval-timeout`(3000) > `TIMEOUT_SECONDS`(1100) | 保持默认即可 |
| 9 | 预算换算已核对 | 启动横幅的 `prompts/chain=N` 与你的预期一致（§2.2） |
| 10 | `--log-interval` 已按需调整 | 默认 1024 > 默认预算 100 ⇒ 只在结束时存一次盘（§10.3） |
| 11 | 用 `--debug-prompt-lines` 看过一次提示词 | 确认没有坑 2 的误导包列表 |
| 12 | 知道怎么 resume | 记住 instance 目录路径（§10.4） |

---

## 9. 运行预算与时间估算

### 9.1 erdos 的特殊之处：墙钟由**评测**主导，不是 LLM

大多数任务的成本瓶颈是 LLM 调用。**erdos 不是。** 单次评测上限 1100 s，而论文那份解自限 1080 s——也就是说，**一旦演化出接近最优的程序，每一次评测都会实打实烧掉 18 分钟**。

估算公式：

```
墙钟 ≈ (候选总数 / eval_concurrency) × 平均单次评测耗时
```

以默认换算出的 112 个候选为例：

| 平均单次评测耗时 | `--eval-concurrency 4` | `--eval-concurrency 8` | `--eval-concurrency 16` |
|:---:|:---:|:---:|:---:|
| 10 s（早期简单程序） | ~5 min | ~2.5 min | ~1 min |
| 60 s | ~28 min | ~14 min | ~7 min |
| 300 s | ~2.3 h | ~1.2 h | ~35 min |
| **1080 s（接近最优）** | **~8.4 h** | **~4.2 h** | **~2.1 h** |

（40 个候选的话，把上表数值乘 40/112 ≈ 0.36。）

### 9.2 并发是被什么限制的

这一点很容易踩坑。**三件事同时限制并发**：

1. `--eval-concurrency`：评测 worker 的 asyncio 任务数（默认 **4**）——这是最常见的天花板。
2. `--backpressure-multiplier`：默认 **0**，含义是"每条链同时只允许 1 个在途批次"（`policies/base.py:573-584`）。所以**并行批次数 ≈ `num_chains`**，无论你把 `gen_concurrency` 调多高。
3. 每个评测子进程把 `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB/BLIS_NUM_THREADS` 全部钉成 **4**（`evaluator.py:233-238`）——所以每个评测最多吃 4 个线程。

**调参建议**：`eval_concurrency ≈ 可用核数 / 4`，并且同步设置 `EVALUATOR_CONCURRENT_PROCESSES` 为该值。在途候选数的上限是 `num_chains × k_candidates`（默认 4×4 = 16），超过这个数再调 `eval_concurrency` 就没用了——除非同时放宽 `--backpressure-multiplier`。

### 9.3 主要旋钮一览

| 想达到的效果 | 调什么 |
|--------------|--------|
| 更快（用更多机器） | `--eval-concurrency` ↑ + `EVALUATOR_CONCURRENT_PROCESSES` 同步 ↑ |
| 让并发放开超过 `num_chains` | `--backpressure-multiplier` 提到 1 或 2 |
| 更省 LLM 钱 | `--num-inspirations` ↓、`--max-generations` ↓ |
| 到达目标分就停 | `--early-stop-score`（例如 `2.6` 就比论文好一点点） |
| 降低单次评测成本 | 任务侧改 `TIMEOUT_SECONDS`（但这会改变任务语义，谨慎） |

---

## 10. 监控、checkpoint 与 resume

### 10.1 目录布局

```
<output-path>/<YYYY-MM-DD>/instance-<8位hex>/          ← 这就是"instance 目录"
  ├─ run.log                    # stdout 的完整副本（tee logger）
  ├─ shared_constructions/      # 共享构造快照
  └─ db_state_<HHMMSS>/         # ← 每一次 checkpoint 一个子目录
       ├─ best_program.py       # 目前最好解（扩展名跟随 --init-program）
       ├─ metadata.json         # instance id、计数、best_score、gen_id_counter 等
       ├─ config.json           # 完整配置（注意：api_key 不落盘，api_base 会）
       ├─ policy.json           # {"name": ..., "state": ...}
       ├─ reflection.json
       ├─ nodes.json 或 nodes.json.gz   # 全部节点
       ├─ scores_<6位>.csv
       ├─ quantile_plot_<6位>.png
       ├─ failure.json          # 有失败记录时才有
       ├─ elite_history.csv + 图  # 仅 llm_elite
       └─ shared_constructions/
```

### 10.2 ⚠️ 只保留最新一份 checkpoint

每次写 checkpoint 时，**上一份 `db_state_*` 目录会被 `shutil.rmtree` 删掉**（`checkpoint.py:94-96`）。

含义：磁盘占用不会无限增长，但**你没法回滚到中间某个历史状态**。所有写入都是原子的（tempfile + `os.replace`，`checkpoint.py:213-233`），所以不会出现半写状态。

### 10.3 ⚠️ `--log-interval` 的默认值和预算不匹配

```python
# engine/core.py:762
should_ckpt = config.log_interval > 0 and completed_evaluations % config.log_interval == 0
```

`--log-interval` 默认 **1024**，而 `--max-generations` 默认 **100**。也就是说**默认配置下整个运行只会在最后写一次盘**。

如果你打算跑长任务（erdos 上很常见），**强烈建议把 `--log-interval` 调到 8~32**，这样中途崩了也不至于全丢。`--log-interval <= 0` 会完全关闭周期性 checkpoint（只在结束时存）。

DB 面板由 `--db-show-interval`（默认 16）控制，`<= 0` 关闭。

### 10.4 resume

```bash
uv run python main.py --resume checkpoints/<date>/instance-<id>
```

- **必须指向 instance 目录**，不是它的父级 date 目录。也可以直接指向 `db_state_*` 子目录，框架会自动回到上一级。
- checkpoint 目录里必须有 `metadata.json`、`config.json`、`policy.json` 三个文件，以及 `nodes.json` 或 `nodes.json.gz`。
- resume 时会**跳过** init program 的 16 次重复评测（DB 非空就不重新初始化）。
- 加载时会调用 `load_state_dict`，它会**清空 `_batches`**——checkpoint 那一刻在途的批次永远无法完成，它们的子节点会丢失。所以别频繁在长评测中途 kill。
- `--resume` 时其余参数（模型、选择器等）从命令行读，但预算相关的状态从 checkpoint 恢复。

### 10.5 ⚠️ 坑 4：`--save-llm-io` 的默认值不一致

`EngineConfig.save_llm_io` 的 dataclass 默认是 **`True`**（`config.py:158`），但 CLI 的 `--save-llm-io` 是 `action="store_true"`，**CLI 默认 `False`**（`cli.py:251-255`），而 `build_config_from_args` 直接传 `args.save_llm_io`（`config.py:234`）。

**净效果：从命令行跑，默认不保存 LLM 完整输入输出**（checkpoint 会小很多）。

不过 reflection 需要 `node.llm_input`，所以框架内部会强制打开 IO 追踪：`track_io = config.save_llm_io or config.reflection_mode`（`engine/core.py:611`）。而 reflection 默认又是开的——所以实际行为是 IO 会为 reflection 保留，但不会全部落盘。想完整留存就显式加 `--save-llm-io`。

---

## 11. 结果读取与后续探索

### 11.1 取回最好解

```bash
# 最快的方式：checkpoint 里直接就有
cat checkpoints/erdos-A/<date>/instance-<id>/db_state_*/best_program.py
```

这是**已经拼装好的完整程序**（prefix + 演化块 + suffix），可以直接单独运行验证。

### 11.2 从 nodes.json 里做分析

`nodes.json`（或 `--gzip` 时的 `nodes.json.gz`）是全部节点的完整记录，每个节点含 `code` / `metrics` / `score` / `chain_idx` / `parent_ids` / `created_at`。典型的分析切入点：

- 按 `created_at` 排序看演化轨迹；
- 按 `parent_ids` 还原 DAG（这正是 `rpucg` 在做的事）；
- 按 `chain_idx` 分组比较不同链的探索方向。

`metadata.json` 里有 `chain_best_scores`（每链最好分），`scores_<n>.csv` 是分数随评测次数的推进曲线。

### 11.3 独立验证一个解

论文那份构造已经被验证过。如果你想自己复核，核心就是 evaluator 里那几行：

```python
h = np.asarray(h_values, dtype=np.float64)
assert abs(h.sum() - n_points/2) < 1e-9      # 或按比例缩放
assert h.min() >= 0 and h.max() <= 1
dx = 2.0 / n_points
c5 = np.max(np.correlate(h, 1.0 - h, mode="full") * dx)
score = 1.0 / (1e-8 + c5)
```

用 `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json` 里的 `(h, C5, n_points)` 三元组应当复现出 `c5 = 0.38086767582732667`。

### 11.4 后续可探索的旋钮

按"改动从轻到重"排序：

| # | 方向 | 怎么做 | 预期影响 |
|---|------|--------|----------|
| 1 | 换选择器 | `--selector balance / puct / rpucg / llm_*` | 成本低。注意 `rpucg` 会换掉整套提示词结构（§5） |
| 2 | 调 C / K | `--num-chains` / `--k-candidates` | C 大 = 方向多；K 大 = 单步更稳但更贵 |
| 3 | 控制提示词长度 | `--num-inspirations`，或 `--min/max-inspirations-cnt` 做采样 | 直接省 token |
| 4 | 修正 requirements.txt | 裁剪 `datasets/erdos/requirements.txt` | 消除坑 2 的误导，避免模型写出 import 失败的代码 |
| 5 | 开共享构造 | `--include-construction`（+ 按 §7.2 让 seed 会读全局变量） | 让链内最优的构造在链内传播 |
| 6 | **续跑论文最好解** | `--init-program` 换成 `erdos_minimum_overlap_best.py` | 从 0.380868 往上推，但注意 16×1080s 的初始化开销（§7.2） |
| 7 | 改评分形状 | 改 evaluator 的 `combined_score` 公式 | 会改变搜索的梯度信号，谨慎；且不再是论文任务 |
| 8 | 多样本初始化 | `--init-eval-repeats` | 只影响 init program 的取分方式（取 16 次最大值） |

> 第 6 项是最有研究价值的：SimpleTES 的设计意图就是"测试时计算花在真正重要的地方"，而 erdos 这个任务已经被推到 0.380868。用它作为起点继续搜索，是验证框架"能否在已有最优解上继续改进"的天然实验。

---

## 附录 A：完整 flag 速查表

以下全部来自 `simpletes/cli.py` + `simpletes/config.py`，默认值为**从命令行运行时的实际生效值**。

### 必需参数

| flag | 说明 |
|------|------|
| `--init-program` | 种子程序路径。**必须含 EVOLVE-BLOCK marker**，否则 `SystemExit(2)` |
| `--evaluator` | evaluator 模块路径 |
| `--instruction` | 任务指令 `.txt` 路径 |

> 这三个在 argparse 里**不是** `required=True`，而是手工校验（`cli.py:376-381`）。唯一的绕过方式是 `--list-policies`。

### 预算 / 终止

| flag | 类型 | 默认 | 说明 |
|------|------|:---:|------|
| `--max-generations` | int | 100 | **候选数**（非 prompt 数，见 §2.1） |
| `--early-stop-score` | float | None | 达到该分即停 |
| `--num-inspirations` | int | 5 | 每次提示词带几条历史；`0` = 静态模式，**要求 `--num-chains 1`** |
| `--min-inspirations-cnt` | int | None | 与 max 成对使用时启用采样 |
| `--max-inspirations-cnt` | int | None | 同上 |
| `--init-eval-repeats` | int | 16 | init program 并发评测次数，取最大值。**必须 > 0**（`cli.py:384-387`） |

### 并发 / 吞吐

| flag | 类型 | 默认 | 说明 |
|------|------|:---:|------|
| `--eval-concurrency` | int | 4 | 评测 worker 数 |
| `--gen-concurrency` | int | 1 | LLM 生成 worker 数（也是 litellm 的进程池大小） |
| `--backpressure-multiplier` | float | 0 | 每链在途批次上限；`0` = 每链严格 1 批 |
| `--eval-timeout` | float | 3000.0 | 框架侧评测硬超时（必须 > 任务的 `TIMEOUT_SECONDS`） |
| `--eval-venv` | str | None | 评测子进程用的 venv；不设则自动探测 `<task_dir>/venv`，再退回 `sys.executable` |
| `--stream-k-candidates` / `--no-stream-k-candidates` | flag | 流式开启 | k 个候选拆成 k 个独立任务。**两者共享 `dest`，不是互斥组，后者写在前者后面会覆盖** |

### 模型 / LLM

| flag | 类型 | 默认 | 说明 |
|------|------|:---:|------|
| `--llm-backend` | choice | `litellm` | `litellm` \| `vllm_token_forcing`（CLI 默认 None → 归一化为 litellm） |
| `--model` | str | `gemini/gemini-2.0-flash` | LiteLLM `provider/model` 字符串 |
| `--api-base` | str | None | 自定义 base URL |
| `--api-key` | str | None | 覆盖 provider key（**建议用环境变量**） |
| `--temperature` | float | 0.7 | |
| `--max-tokens` | int | 32768 | |
| `--retry` | int | 0 | 传给 litellm 的 `num_retries` |
| `--timeout` | float | 3000 | LLM 请求超时（秒） |
| `--max-total-tokens` | int | None | 总 token 预算，会压缩 completion 上限 |
| `--reasoning-effort` | choice | medium | `low`\|`medium`\|`high`，仅对含 `gpt-oss` 的模型名生效 |
| `--disable-reflection` | flag | 未给（=reflection **开启**） | 关闭 reflection 摘要 |
| `--tokenizer-path` | str | None | 仅 `vllm_token_forcing` |
| `--reasoning-budget` | int | None（CLI） | `vllm_token_forcing` 阶段 1 预算；None = 由 `context_window - response_budget` 自动推 |
| `--response-budget` | int | 16384 | `vllm_token_forcing` 阶段 2 保留 token |
| `--context-window` | int | 49152 | `vllm_token_forcing` 的 vLLM 上下文窗口 |
| `--llm-policy-model` | str | None | LLM 类选择器用的模型，回退 `--model` |
| `--llm-policy-api-base` | str | None | 回退 `--api-base` |
| `--llm-policy-api-key` | str | None | 回退 `--api-key` |
| `--llm-policy-pool-size` | int | None | `llm_elite` 默认 15；`llm_puct`/`llm_rpucg` 默认 20 |

### 选择器 / 策略

| flag | 类型 | 默认 | 说明 |
|------|------|:---:|------|
| `--selector` | str | `balance` | 运行时校验，非法值 `exit(1)` |
| `--num-chains` | int | 4 | C |
| `--k-candidates` | int | 4 | K |
| `--exploitation-ratio` | float | 0.7 | balance |
| `--exploration-ratio` | float | 0.2 | balance |
| `--elite-ratio` | float | 0.2 | balance |
| `--puct-c` | float | 0.5 | puct / rpucg |
| `--rpucg-gamma` | float | 0.8 | rpucg 的值回传衰减 |
| `--elite-selection-strategy` | choice | `linear_rank` | `linear_rank`\|`balance`\|`all`，仅 llm_elite |
| `--include-construction` | flag | 关闭 | 每链共享构造（§7.2） |
| `--debug-prompt-lines` | int | 0 | 打印提示词前 N 行 |

### Checkpoint / IO

| flag | 类型 | 默认 | 说明 |
|------|------|:---:|------|
| `--output-path` | str | `checkpoints` | 输出根目录 |
| `--log-interval` | int | 1024 | 每 N 次评测写一次盘；`<= 0` 关闭 |
| `--db-show-interval` | int | 16 | 每 N 次评测打印 DB 面板；`<= 0` 关闭 |
| `--save-llm-io` | flag | **CLI 默认关闭**（dataclass 默认 True，见 §10.5） | 保存完整 LLM 输入输出 |
| `--gzip` | flag | 关闭 | nodes 文件 gzip 压缩 |
| `--resume` | str | None | instance 目录或 `db_state_*` 目录 |

### 其它

| flag | 说明 |
|------|------|
| `--list-policies` | 打印选择器列表并 `exit(0)` |
| `--skip-preflight` | 跳过启动时的 1-token LLM ping |

### 无 CLI flag 的配置项

- `include_failure_patterns`（默认 `True`，`config.py:171`）——只能改代码。

### 框架读取的环境变量

| 变量 | 作用 |
|------|------|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` … | 由 LiteLLM 读取，**框架代码本身不读** |
| `SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH` | 从零启动时给 init program 用的初始共享构造（§7.2） |
| `SIMPLETES_SHARED_CONSTRUCTION_PATH` | 框架**自己设置**，传给评测子进程 |
| `SIMPLETES_CAPTURE_CONSTRUCTION_PATH` | 框架**自己设置**，evaluator 往里写捕获的构造 |
| `SIMPLETES_SHARED_CONSTRUCTION_MAX_BYTES` | 构造快照上限，默认 4 MiB，下限 1024 |

以及 erdos evaluator 自己读的 `EVALUATOR_TIMEOUT_SECONDS` / `EVALUATOR_CONCURRENT_PROCESSES` / `EVALUATOR_OS_BUFFER_PERCENT`（§6.5）。

---

## 附录 B：源码索引

| 想查什么 | 去哪 |
|----------|------|
| 全部 CLI flag | `simpletes/cli.py:13-364` |
| 配置 dataclass 与默认值 | `simpletes/config.py:111-190` |
| 参数合理性警告 | `simpletes/config.py:291-419` |
| `<task_dir>` 推导 / eval Python 解析 | `simpletes/config.py:50-108` |
| 启动流程 | `main.py:53-92` |
| preflight | `main.py:95-132` |
| 调度循环 | `simpletes/engine/scheduler.py:266` |
| 一次 generation 的预算判断 | `simpletes/engine/scheduler.py:173-228` |
| 节点提交 / 每链构造更新 | `simpletes/engine/core.py:720-785` |
| init program 的 16 次评测 | `simpletes/engine/core.py:490-527` |
| 链预算与 prompt 预算 | `simpletes/policies/base.py:174-237` |
| backpressure 判定 | `simpletes/policies/base.py:573-579`（方法入口 `:555`） |
| batch 收尾与 reflection | `simpletes/policies/base.py:451-529` |
| EVOLVE-BLOCK 抽取 | `simpletes/utils/code_extract.py:58-157` |
| 提示词拼装 | `simpletes/generator.py:242-346` |
| `available_packages` 注入 | `simpletes/generator.py:277-285` |
| 共享构造提示词段 | `simpletes/generator.py:287-296` |
| rpucg 专属提示词路径 | `simpletes/generator.py:303-322` |
| 评测子进程 runner | `simpletes/evaluator.py:77-116` |
| 评测子进程环境 | `simpletes/evaluator.py:156-171` |
| 超时与杀进程 | `simpletes/evaluator.py:213-257` |
| 共享构造编解码 | `simpletes/construction.py:63-122` |
| `sitecustomize` 钩子 | `sitecustomize.py` + `construction.py:190-191` |
| checkpoint 落盘 | `simpletes/engine/checkpoint.py:77-233` |
| checkpoint 加载 / resume | `simpletes/engine/checkpoint.py:264-401` |
| resume 目录解析 | `simpletes/engine/core.py:1009-1025` |
| 任务准备（manifest） | `simpletes/utils/task_prep.py:159-194` |
| erdos 验收逻辑 | `datasets/erdos/erdos_min_overlap/evaluator.py:68-124` |
| erdos 评分 | `datasets/erdos/erdos_min_overlap/evaluator.py:308-377` |
| erdos 种子 | `datasets/erdos/erdos_min_overlap/init_program.py` |
| 论文最好解程序 | `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best.py` |
| 论文最好构造 | `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json` |
| 任务设计规范 | `datasets/README.md` |
| 案例研究 | `assets/case_study/README.md` |
