# SimpleTES Quickstart — erdos 最小重叠

> 只讲怎么跑。机制细节见 `run_doc.md`。

## 1. 环境

- **Linux**（erdos 的 evaluator 依赖 `resource` / `os.killpg`，Windows 上每次评测都会 0 分）
- Python ≥ 3.11，装依赖：`uv sync`

## 2. 最小启动

```bash
uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator    datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction  datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model <provider/model> \
  --selector rpucg
```

`--model` 用 LiteLLM 的 `provider/model` 格式（如 `gemini/gemini-2.0-flash`）。凭据走环境变量：`export GEMINI_API_KEY=...`（或 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`）。

启动时会做一次 1-token 的 preflight 校验凭据，失败直接退出；本地后端未就绪时加 `--skip-preflight` 绕过。

## 3. 推荐配方

**配方 A（基线）**

```bash
export EVALUATOR_CONCURRENT_PROCESSES=8   # 和 eval-concurrency 对齐

uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator    datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction  datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model gemini/gemini-2.0-flash \
  --selector rpucg \
  --num-chains 4 \
  --k-candidates 4 \
  --max-generations 40 \
  --eval-concurrency 8 \
  --output-path checkpoints/erdos-A
```

**配方 B（共享构造热启动）**

在 A 的基础上：改 seed 让它读 `GLOBAL_BEST_CONSTRUCTION`，并加 `--include-construction`，同时用论文那份解做初始种子：

```bash
SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH=best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best_construction.json \
uv run python main.py \
  --init-program datasets/erdos/erdos_min_overlap/init_program.py \
  --evaluator    datasets/erdos/erdos_min_overlap/evaluator.py \
  --instruction  datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt \
  --model <your-model> \
  --selector rpucg \
  --num-chains 4 \
  --k-candidates 4 \
  --max-generations 40 \
  --eval-concurrency 8 \
  --include-construction \
  --output-path checkpoints/erdos-B
```

> ⚠️ 配方 B 有个坑：`SIMPLETES_INITIAL_SHARED_CONSTRUCTION_PATH` 只喂给 init program 那一次评测，而**当前 seed 不读这个全局变量**，接着又被自己 capture 的差构造覆盖，等于种子被丢掉。要让它生效，得先改 seed 的 EVOLVE-BLOCK 让它读取 `GLOBAL_BEST_CONSTRUCTION`（论文那份解的程序已经会读，可直接拿它当 `--init-program`）。

## 4. 启动前必须知道的三件事

1. **`--max-generations` 计的是候选数，不是 prompt 数。** 真正跑的 prompt 数 ≈ `max-generations / k-candidates`。
2. **单次评测可能长达 18 分钟。** 评测超时上限 1100 s（论文解自限 1080 s）。墙钟由评测主导，不是 LLM。要更快就调大 `--eval-concurrency`（并同步 `EVALUATOR_CONCURRENT_PROCESSES`）。
3. **默认只在结束时存一次盘。** `--log-interval` 默认 1024，大于预算，中途崩了就全丢。长任务请把它调到 8~32。

## 5. 冒烟测试（先别直接跑真任务）

复制任务目录到临时位置，把 evaluator 的 `TIMEOUT_SECONDS` 调成 30，跑 `--max-generations 4`，确认整条链路（LLM → 抽取 EVOLVE-BLOCK → 子进程评测 → 提交 → checkpoint）都通，再切回真任务。

## 6. 结果与续跑

- 最好解在 `checkpoints/erdos-A/<date>/instance-<id>/db_state_*/best_program.py`，可直接运行。
- 论文最好分：`C₅ = 0.380868`（`score ≈ 2.6256`）。
- 想从论文解往上推：把 `--init-program` 换成 `best_results/mathematics_discovery/erdos_minimum_overlap/erdos_minimum_overlap_best.py`，同时把 `--init-eval-repeats` 降到 1（那份程序一次评测 18 分钟，默认会并发跑 16 次）。
- 中断/续跑：`uv run python main.py --resume checkpoints/erdos-A/<date>/instance-<id>`（指向 **instance 目录**）。
