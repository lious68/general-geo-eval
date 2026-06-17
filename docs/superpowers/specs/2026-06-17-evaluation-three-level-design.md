# 评测页三级任务架构改造设计（任务 → 模型 → 问题）

> 日期：2026-06-17
> 范围：仅 WebChat（模拟网页）模式。API 模式整条线移出本次设计范围，保持现状不动。

## Context（为什么做）

上周把评测从 API 调用改为 Playwright Web Chat，最真实还原用户使用方式，但各平台反爬/风控差异大。本周暴露的核心缺口：

- **DeepSeek 等平台对高频请求极敏感**——同一账号短时连续问询超过约 25 次即触发封号。
- **标准基准规模 = 40 题 × 5 模型 = 200 次请求**，链路须零中断，否则错误沿流程累积，破坏最终评测完整性。
- **`/evaluation` 页当前没有三级任务**：执行评测是一次性流程，散装的「下载任务配置」「导入本地 WebChat 结果」两张卡孤立存在，且页面引用了根本不存在的 `python scripts/local_agent.py --server ... --password ...` 提示。整体不符合「任务—模型—问题」的设计逻辑。
- 上周已完成的事（本次复用，不改）：三级调度引擎 `core/scheduler.py`（跨模型交错 + 逐模型限流 + 单题重试 + 封号信号检测与自动退避 + 断点续跑）、`core/task_units.py`（单元状态层）、`core/webchat_policy.py`（逐模型策略与封号信号）、`local_webchat_runner.py` 已接入调度器并支持 `--resume`。

**本次目标**：把网站管理端（服务器）与实际执行端（Windows 本地）按「任务 → 模型 → 问题」解耦并落地——

- 服务器负责任务创建、参数配置、结果合并与展示；
- Windows 客户端异步执行实际评测，不受网站服务/浏览器状态/网络波动影响；
- 数据结构支持灵活追加与分批执行：同任务先跑模型1再补模型2、同模型先跑 1–20 题再补 21–40 题；
- 服务器自动合并多次导入，以任务为最终汇总单位，避免重复执行、结果覆盖或数据错乱。

## 已确认决策

1. **范围**：仅 WebChat（模拟网页）模式。API 模式移出范围，保持现状。
2. **Task 顶层范围**：Task 顶层只统领 WebChat 解耦流程（下载配置 → 本地执行 → 导入）。
3. **合并语义**：Task 有**固定总题集**（创建时拍板，不可改）；同任务下可多次下载配置分别跑不同模型/题区间；导入按 `(task_id, model_key, question_id)` 去重覆盖，多余题进不来。
4. **Task 标识**：`task_id` 在下载配置中下发（同时含 `batch_id`），本地 runner 透传回结果 JSON，导入时服务器按 `task_id` 合并，不新建 run。
5. **评分合并**：每次导入后服务器按当前 Task 全部已入库 analysis_results **重算 geo_scores 并覆盖**。
6. **前端**：`/evaluation` 重构为三级任务管理页（任务列表 → 新建向导 → 任务详情矩阵）。
7. **local_agent.py 提示**：完全移除（脚本本就不存在）。

## 架构

```
┌────────────────── 服务器 (Linux) ──────────────────┐
│  /evaluation 前端（三级任务管理）                     │
│  ├─ 任务列表（顶层 Task）                            │
│  ├─ 新建向导：定总题集 → 挂模型(+题区间) → 下配置     │
│  └─ 任务详情：模型×题覆盖率矩阵 + 批次 + 导入         │
│                                                      │
│  /api/tasks 路由组（取代旧 export/import 端点）       │
│  tasks 表 / evaluation_runs(批次) / analysis_results │
│  geo_scores（task 维度重算）                         │
└──────────────────────────────────────────────────────┘
                       │ 下载 task_config.json (v2)
                       ▼
┌────────────────── 本地 (Windows) ───────────────────┐
│  python scripts/local_webchat_runner.py              │
│    --config task_config.json --headed                │
│  EvalScheduler：交错/限流/重试/封号退避/断点续跑      │
│  按 units（每模型独立题区间）展开                     │
│  → output/<run_id>.json（meta 透传 task_id/batch_id）│
└──────────────────────────────────────────────────────┘
                       │ 上传结果 JSON
                       ▼
            服务器导入 → 按 (task,model,question) 合并
                      → 重算 task 评分 → 矩阵刷新
```

## 数据模型

新增 `tasks` 顶层表；`evaluation_runs` 退化为 Task 下的「执行批次」并加外键；`analysis_results` / `geo_scores` 加 `task_id` 列实现跨批次合并。历史 API run（`task_id=NULL`）原样保留可查，不在本次设计内改动其行为。

```sql
-- 新增：任务顶层（固定总题集，创建时拍板，不可改）
CREATE TABLE IF NOT EXISTS tasks (
  id            TEXT PRIMARY KEY,          -- task_<ts>_<hex>
  name          TEXT NOT NULL,
  question_ids  TEXT NOT NULL,             -- JSON 数组，固定总题集
  categories    TEXT DEFAULT '[]',         -- JSON，创建时品类快照（仅记录）
  status        TEXT DEFAULT 'active',     -- active|archived
  notes         TEXT DEFAULT '',
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP
);

-- evaluation_runs 加两列：WebChat 批次 task_id 指向 task
ALTER TABLE evaluation_runs ADD COLUMN task_id   TEXT;
ALTER TABLE evaluation_runs ADD COLUMN batch_id  TEXT;   -- 下载批次标识

-- analysis_results 加列 + 唯一索引（按 task 去重覆盖）
ALTER TABLE analysis_results ADD COLUMN task_id   TEXT;
ALTER TABLE analysis_results ADD COLUMN batch_id  TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ar_task_model_q
  ON analysis_results(task_id, model_key, question_id);  -- NULL 视为互异，历史 NULL 行不冲突

-- geo_scores 加列（不用唯一索引；每次导入 DELETE WHERE task_id=? + 全量重算插入）
ALTER TABLE geo_scores ADD COLUMN task_id TEXT;
```

**合并 / 去重语义**

- `analysis_results` 按 `(task_id, model_key, question_id)` 去重——同题同模型重导先删后插（事务内），**覆盖不累积**。固定总题集保证多余题进不来。
- `geo_scores` 每次导入后按 task 全量重算并覆盖（DELETE+INSERT），始终反映当前 Task 完整状态。
- 覆盖率矩阵（Task 详情页核心）：由 Task 固定题集 × 各模型，join `analysis_results` 推导每格状态 `done|failed|missing`。**不依赖 `task_units` 表**——那是调度器执行期单元存储，WebChat 在本地跑，服务器不需要它。

**迁移幂等**：SQLite `ADD COLUMN` 需先查 `PRAGMA table_info` 判存；`CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` 天然幂等。不迁移历史数据，旧 run `task_id=NULL` 原样可查。

## API（`/api/tasks` 路由组，取代旧两个端点）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/tasks` | 建任务 `{name, categories\|question_ids}` → 固定题集 → 返回 `task_id` |
| GET | `/api/tasks` | 任务列表（含覆盖率摘要：总格数 / done / missing） |
| GET | `/api/tasks/{task_id}` | 详情：meta + 固定题集 + 模型×题覆盖率矩阵 + 批次列表 |
| DELETE | `/api/tasks/{task_id}` | 级联删 task + 其下 runs/results/scores |
| POST | `/api/tasks/{task_id}/batches` | 建下载批次 `{model_keys, per_model_question_ids, delay}` → 返回 v2 配置 JSON + 建 `evaluation_runs` 批次行（`status='config_downloaded'`） |
| POST | `/api/tasks/{task_id}/import-results` | 上传结果 JSON（meta 带 `task_id`/`batch_id`）→ 按 `(task_id, model_key, question_id)` 合并 → 重算 task 评分 → 批次行置 `completed` |
| GET | `/api/tasks/{task_id}/scores` | task 级评分（全局 + 品类，跨批次） |
| GET | `/api/tasks/{task_id}/details` | task 级 analysis_results（分页，跨批次） |

`/api/results/*` 现有路由加可选 `task_id` query 参数：Dashboard 用 `?task_id=` 查任务级结果。

**清理**：`evaluations.py` 删除 `export-webchat-config`、`import-results` 两个端点（被 `/api/tasks/.../batches`、`/api/tasks/.../import-results` 取代）；保留 `recalculate-scores`（历史 run 兜底）。

### 下载配置 v2（本地 runner 消费，支持每模型独立题区间）

```json
{
  "version": 2,
  "task_id": "task_...",
  "task_name": "...",
  "batch_id": "batch_...",
  "generated_at": "...",
  "total_question_ids": ["q1", "q2", "...", "q40"],
  "units": [
    {"model_key": "deepseek", "question_ids": ["q1", "...", "q20"]},
    {"model_key": "kimi", "question_ids": ["q1", "...", "q40"]}
  ],
  "questions": [ /* units 并集对应的完整题对象 */ ],
  "delay": 8
}
```

### 结果 JSON（本地 runner 产出，meta 透传 task_id/batch_id）

```json
{
  "meta": {"task_id": "task_...", "batch_id": "batch_...", "run_id": "...", "mode": "webchat_local", ...},
  "questions": [ ... ],
  "analysis_results": {"deepseek": [ ... ], "kimi": [ ... ]}
}
```

服务器忽略结果 JSON 中的 `geo_scores`（若有），按 task 全量重算。

## 前端（`/evaluation` = 纯 WebChat 三级任务管理）

**① 任务列表（顶层 = Task）**
- 每行一个 Task：名称 / 总题集数 / 模型数 / 覆盖率（`done/total` 格数）/ 状态。
- 右上「新建任务」按钮。

**② 新建任务向导（三级一次走通）**
- Step 1（定 Task）：任务名 + 选品类或题区间 → **拍板固定总题集** → `POST /api/tasks` 返回 `task_id`。
- Step 2（在 Task 下挂「模型」）：「添加评测模型」，每行选 `model_key` + 该模型要跑的题区间（总题集子集，默认全选）→ `POST /api/tasks/{id}/batches` 建批次并下载 `task_config.json`（内含 `task_id`/`batch_id`/`units`）。
- **Step 2 可重复**：先下模型1 的 1–20 题，后补模型2、或模型1 的 21–40 题——每次独立 batch + 独立配置下载。这是「同任务先模型1 后模型2、同模型分批」的落点。

**③ 任务详情（展开 / 点入）——「模型 × 问题」矩阵**
- 覆盖率矩阵：行 = 各模型，列 = 总题集每一题，格状态 `done|failed|missing`（由 `analysis_results` join 推导）。
- 批次列表：每批次显示 模型 + 题区间 + 下载时间 + 导入状态。
- 导入入口：上传本地 runner 产出的 JSON → `POST /api/tasks/{id}/import-results` → 按 `(task_id, model_key, question_id)` 合并 → 矩阵刷新 + 评分重算。
- 结果查看：矩阵覆盖后「查看结果 →」跳 Dashboard `?task_id=`。

**删除项（前端）**
- API 模式单选与一次性表单、`python scripts/local_agent.py ...` 提示、agent 连接轮询（`evalProgress.js` 的 `startAgentPoll`/`stopAgentPoll`/`agentConnected`）、散装「下载任务配置」「导入本地 WebChat 结果」两张卡。

> 关于 API 模式：后端 API 评测路径（`eval_runner.py` API 分支、`/api/evaluations` POST）**保持现状不动**，本次不删除、不改动；前端仅不再暴露 API 入口。历史 API run（`task_id=NULL`）在 Dashboard / History 原样可查。

## 调度器与本地 runner 演进

**`core/scheduler.py`（最小扩展）**

- `EvalScheduler.__init__` 新增 `per_model_questions: Optional[Dict[str, List[Dict]]]`。`expand_units` 时按它展开（每模型各自题集），缺省退化为 `models × questions`（旧自检 / 既有调用不受影响）。
- 其余（rate-limit / 重试 / 封号退避 / 进度广播）**零改动**。现有 4 项自检继续通过。
- 调度器执行期**不依赖 task_id**——保持无状态、两端共用。`task_units` 表主键不变 `(run_id, model_key, question_id)`，run_id 仍由本地 runner 生成；task_id/batch_id 只随结果 JSON 回传。

**`local_webchat_runner.py`（消费 v2 配置）**

- `--config task_config.json` 解析 v2：`task_id`/`batch_id` 透传到 `_build_output` 的 `meta`，供导入时归并。
- **每模型独立题区间**：v1 是 `model_keys + 全部 question_ids`（所有模型同题集）；v2 的 `units: [{model_key, question_ids}]` 允许每模型只跑自己区间。`run_local_eval` 改为按 `units` 展开调度器 units，而非 `models × all_questions` 笛卡尔积。
- 结果 JSON `meta` 加 `task_id`/`batch_id`；`analysis_results` 每条不强制带 task_id（服务器按 meta 归并）。
- `--resume` 逻辑不变（仍按本地 run_id/manifest/store 续跑）；续跑产出的结果 JSON 同样回填同一 task_id/batch_id。

**`eval_runner.py`**：本次范围内 WebChat 在本地执行，服务器端 eval_runner 的 WebChat 分支不再被触发（前端已无该入口）；保持现状不动以避免破坏既有调度器接入。API 分支亦不动（移出范围）。

## 测试

1. **合并去重**：mock 两次导入同一 Task 不同模型/题区间 → `(task_id, model_key, question_id)` 覆盖不累积；矩阵缺口正确；评分重算后反映并集。
2. **v2 配置 + 每模型题区间**：mock v2 配置跑 2 模型各自不同题 → units 按区间展开；断点续跑仍正确。
3. **调度器回归**：现有 4 项自检（交错 / 限流 / 重试 / 封号 / 续跑）全绿。
4. **迁移幂等**：对已有 `data/geo.db` 跑迁移，历史 run 可查、不报列缺失；重复跑迁移无副作用。

## 关键复用（避免新造轮子）

- `analyzer.ResponseAnalyzer` / `_analysis_to_dict` / `_scores_to_dict` / `_dict_to_analysis` / `_empty_result`（两端各有一份，保持）。
- `save_analysis_result` / `save_geo_scores` / `update_run_status`（database.py，不改签名，新增 task 维度查询）。
- `create_web_chat_client` / `WEBCHAT_SITES` / `validate_auth_cookies`（web_chat_clients.py / web_chat_auth.py，不改）。
- `EvalScheduler` / `SqliteUnitStore` / `MODEL_POLICY` / `classify_signal`（上周新增，本次仅 `EvalScheduler` 加 `per_model_questions`）。

## 正确性根基

- `analysis_results` 唯一性靠 `(task_id, model_key, question_id)`（任务级）/ `(run_id, model_key, question_id)`（历史 run 级）；`geo_scores` 按 task 全量重算——**均不依赖落库顺序**。所以分批交错执行对最终评分零影响。
- 调度器**无状态**：`pick_next(units, model_state)`。「首次跑」与「断点续跑」走同一套代码路径（续跑跳过 done）。进程启动时把所有 `running` reset 为 `pending`，杜绝幽灵单元。
