# 评测页三级任务架构改造（任务→模型→问题）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/evaluation` 页重构为「任务 → 模型 → 问题」三级任务管理（仅 WebChat 模式范围），服务器负责任务创建/配置/合并/展示，Windows 本地异步执行，支持同任务分批追加与断点续跑。

**Architecture:** 新增 `tasks` 顶层表 + 三表加 `task_id`/`batch_id` 列；`/api/tasks` 路由组取代旧 export/import 端点；前端 `/evaluation` 重构为任务列表→新建向导→任务详情矩阵；本地 runner 消费 v2 配置（每模型独立题区间），结果 JSON 透传 `task_id`/`batch_id`，服务器按 `(task_id, model_key, question_id)` 去重覆盖 + 重算评分。

**Tech Stack:** FastAPI + aiosqlite + Pydantic（后端）；Vue 3 + Element Plus + Pinia（前端）；Playwright + 三级调度引擎 `core/scheduler.py`（本地执行）；pytest 风格自检脚本（无 pytest 依赖，纯 assert + `python -m`）。

## Global Constraints

- 范围**仅 WebChat 模式**。API 评测后端路径（`eval_runner.py` API 分支、`/api/evaluations` POST）**保持现状不动**；前端仅移除 API 入口，不再暴露。
- 历史 API run（`task_id=NULL`）在 Dashboard/History 原样可查，迁移**不改动历史数据**。
- `analysis_results` 去重按 `(task_id, model_key, question_id)`；NULL task_id 行视为互异（历史 API run 不受唯一索引影响）。
- 数据库迁移必须**幂等**：`CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` / `ALTER TABLE ADD COLUMN` 先查 `PRAGMA table_info`。
- 调度器**无状态**，执行期不依赖 `task_id`；`task_id`/`batch_id` 只随结果 JSON 回传，服务器侧归并。
- `.gitignore` 忽略 `data/` 与 `output/`：**禁止**提交 `data/geo.db`（含真实 API key）或 `output/*.json`。
- 不在仓库硬编码任何 API key / 服务密钥。
- 提交规范：每个 Task 末尾一次 commit；commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- 中文界面文案保持与现有页面一致风格。

---

## File Structure

**新增（后端）**
- `backend/routers/tasks.py` — `/api/tasks` 路由组（建任务/列表/详情/删除/建批次下载/导入结果/评分/明细）。
- `backend/services/task_service.py` — Task 领域逻辑：建任务固定题集、建批次生成 v2 配置、导入合并去重、覆盖率矩阵计算、task 维度重算评分。

**新增（前端）**
- `frontend/src/views/TaskList.vue` — 任务列表页（顶层 Task）。
- `frontend/src/views/TaskDetail.vue` — 任务详情页（模型×题覆盖率矩阵 + 批次列表 + 导入入口）。
- `frontend/src/api/tasks.js` — tasks 路由组的 API 客户端函数。

**修改（后端）**
- `backend/database.py` — 加 `tasks` 表 schema + 迁移加列 + task 维度查询函数。
- `backend/models.py` — 加 `Task*` Pydantic 请求模型。
- `backend/app.py` — 注册 tasks router + 鉴权放行/保护配置。
- `backend/routers/evaluations.py` — 删 `export-webchat-config`、`import-results` 两端点（保留 `recalculate-scores`）。
- `backend/routers/results.py` — `scores`/`details` 等路由加可选 `task_id` 参数。

**修改（core / 脚本）**
- `core/scheduler.py` — `EvalScheduler` 加 `per_model_questions` 可选入参，`prepare` 按 per-model 题集展开。
- `scripts/local_webchat_runner.py` — 解析 v2 配置 `units`；`run_local_eval` 支持每模型独立题区间；结果 meta 透传 `task_id`/`batch_id`。

**修改（前端）**
- `frontend/src/views/Evaluation.vue` — 重写为三级任务管理页（嵌入 TaskList + TaskDetail，或作为路由壳）。
- `frontend/src/router/index.js` — 加 `/tasks`、`/tasks/:taskId` 路由。
- `frontend/src/stores/evalProgress.js` — 删 agent 轮询（`startAgentPoll`/`stopAgentPoll`/`agentConnected`）。

**测试**
- `scripts/test_tasks_service.py`（新）— task_service 合并去重/重算/矩阵/迁移幂等自检。
- `scripts/test_scheduler_selfcheck.py`（已有）— 回归验证 per_model_questions 扩展不破坏既有 4 项。

---

### Task 1: 数据库 — tasks 表与 task_id 列迁移

**Files:**
- Modify: `backend/database.py`（SCHEMA_SQL 加 tasks 表；`_migrate_add_columns` 加 task_id/batch_id 列；新增 task 维度查询函数）

**Interfaces:**
- Consumes: `init_db()`、`_migrate_add_columns(db)`、`get_db()`（既有）。
- Produces: 新增 async 函数 `create_task`、`get_task`、`list_tasks`、`delete_task`、`add_task_batch`、`list_task_batches`、`set_batch_status`、`save_task_analysis_result`、`get_task_results`、`get_task_scores`、`delete_task_geo_scores`、`get_task_coverage`、`column_exists`。签名见各 Step。

- [ ] **Step 1: 在 SCHEMA_SQL 末尾追加 tasks 表**

在 `backend/database.py` 的 `SCHEMA_SQL` 字符串中（`task_units` 表与索引之后、闭合 `"""` 之前）追加：

```sql

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    question_ids  TEXT NOT NULL,
    categories    TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'active',
    notes         TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP
);
```

- [ ] **Step 2: 在 `_migrate_add_columns` 末尾加 task_id/batch_id 迁移块**

在 `backend/database.py` 的 `_migrate_add_columns` 函数末尾（最后的 `except Exception: pass` 之后、函数 return 前）追加：

```python
    # tasks 改造：evaluation_runs / analysis_results / geo_scores 加 task_id, batch_id
    for table, cols in [
        ("evaluation_runs", [("task_id", "TEXT"), ("batch_id", "TEXT")]),
        ("analysis_results", [("task_id", "TEXT"), ("batch_id", "TEXT")]),
        ("geo_scores", [("task_id", "TEXT")]),
    ]:
        for col_name, col_type in cols:
            if not await column_exists(db, table, col_name):
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                await db.commit()

    # analysis_results 上 (task_id, model_key, question_id) 唯一索引（NULL task_id 行互异，不受约束）
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ar_task_model_q "
        "ON analysis_results(task_id, model_key, question_id)"
    )
    await db.commit()
```

- [ ] **Step 3: 新增 `column_exists` 辅助函数**

在 `backend/database.py` 中（`_migrate_add_columns` 之前）新增：

```python
async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """判断某列是否已存在（ADD COLUMN 幂等前置检查）。"""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return any(r["name"] == column for r in rows)
```

- [ ] **Step 4: 新增 task 维度查询函数（CRUD）**

在 `backend/database.py` 末尾追加：

```python
# ============================================================
# Task 顶层（三级任务架构：任务 → 模型 → 问题）
# ============================================================

async def create_task(task_id: str, name: str, question_ids: List[str],
                      categories: Optional[List[str]] = None) -> Dict:
    """创建任务（固定总题集，创建时拍板）。"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tasks (id, name, question_ids, categories, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (task_id, name, json.dumps(question_ids),
             json.dumps(categories or []))
        )
        await db.commit()
        return await get_task(task_id)
    finally:
        await db.close()


async def get_task(task_id: str) -> Optional[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        t = dict(row)
        t["question_ids"] = json.loads(t["question_ids"]) if isinstance(t["question_ids"], str) else t["question_ids"]
        t["categories"] = json.loads(t["categories"]) if isinstance(t.get("categories"), str) else (t.get("categories") or [])
        return t
    finally:
        await db.close()


async def list_tasks(limit: int = 100, offset: int = 0) -> List[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for t in rows:
            t["question_ids"] = json.loads(t["question_ids"]) if isinstance(t["question_ids"], str) else t["question_ids"]
            t["categories"] = json.loads(t["categories"]) if isinstance(t.get("categories"), str) else (t.get("categories") or [])
        return rows
    finally:
        await db.close()


async def delete_task(task_id: str):
    """级联删除 task + 其下批次 runs + results + scores。"""
    db = await get_db()
    try:
        # 先删该 task 下的 analysis_results / geo_scores
        await db.execute("DELETE FROM analysis_results WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM geo_scores WHERE task_id=?", (task_id,))
        # 删该 task 下的批次 run（先收 run_id 再删 results）
        cur = await db.execute("SELECT id FROM evaluation_runs WHERE task_id=?", (task_id,))
        run_ids = [r["id"] for r in await cur.fetchall()]
        for rid in run_ids:
            await db.execute("DELETE FROM analysis_results WHERE run_id=?", (rid,))
            await db.execute("DELETE FROM geo_scores WHERE run_id=?", (rid,))
        await db.execute("DELETE FROM evaluation_runs WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.commit()
    finally:
        await db.close()


async def add_task_batch(run_id: str, task_id: str, batch_id: str, name: str,
                         model_keys: List[str], question_ids: List[str],
                         per_model: Dict[str, List[str]], config: Optional[Dict] = None) -> Dict:
    """在 task 下建一个下载批次（evaluation_runs 行，status='config_downloaded'）。"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO evaluation_runs
               (id, name, status, model_keys, question_ids, total_questions, config, mode, task_id, batch_id)
               VALUES (?, ?, 'config_downloaded', ?, ?, ?, ?, 'webchat', ?, ?)""",
            (run_id, name, json.dumps(model_keys), json.dumps(question_ids),
             sum(len(v) for v in per_model.values()), json.dumps(config or {}), task_id, batch_id)
        )
        await db.commit()
        return await get_run(run_id)
    finally:
        await db.close()


async def list_task_batches(task_id: str) -> List[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluation_runs WHERE task_id=? ORDER BY started_at DESC, id DESC",
            (task_id,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["model_keys"] = json.loads(r["model_keys"]) if isinstance(r["model_keys"], str) else r["model_keys"]
            r["question_ids"] = json.loads(r["question_ids"]) if isinstance(r["question_ids"], str) else r["question_ids"]
            r["config"] = json.loads(r["config"]) if isinstance(r.get("config"), str) else (r.get("config") or {})
        return rows
    finally:
        await db.close()


async def set_batch_status(run_id: str, status: str, completed: Optional[int] = None):
    await update_run_status(run_id, status, completed)


async def save_task_analysis_result(task_id: str, batch_id: str, run_id: str, result: Dict):
    """按 (task_id, model_key, question_id) 去重覆盖插入。"""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM analysis_results WHERE task_id=? AND model_key=? AND question_id=?",
            (task_id, result["model_key"], result["question_id"])
        )
        await db.execute(
            """INSERT INTO analysis_results
               (run_id, task_id, batch_id, question_id, model_key, model_name,
                ucloud_mentioned, ucloud_mention_count, ucloud_rank,
                has_citation, citation_count, ucloud_recommended, recommendation_strength,
                sentiment_score, sentiment_label, position_weight, response_length,
                raw_content, competitor_mentions, error_message, citations, all_cited_urls)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, task_id, batch_id, result["question_id"], result["model_key"], result["model_name"],
             int(result["ucloud_mentioned"]), result["ucloud_mention_count"], result.get("ucloud_rank"),
             int(result["has_citation"]), result["citation_count"],
             int(result["ucloud_recommended"]), result["recommendation_strength"],
             result["sentiment_score"], result["sentiment_label"], result["position_weight"],
             result["response_length"], result.get("raw_content", ""),
             json.dumps(result.get("competitor_mentions", {}), ensure_ascii=False),
             result.get("error_message"),
             json.dumps(result.get("citations", []), ensure_ascii=False),
             json.dumps(result.get("all_cited_urls", []), ensure_ascii=False))
        )
        await db.commit()
    finally:
        await db.close()


async def get_task_results(task_id: str, model_key: Optional[str] = None) -> List[Dict]:
    db = await get_db()
    try:
        query = "SELECT * FROM analysis_results WHERE task_id=?"
        params = [task_id]
        if model_key:
            query += " AND model_key=?"
            params.append(model_key)
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_task_scores(task_id: str, category: Optional[str] = None) -> List[Dict]:
    db = await get_db()
    try:
        query = "SELECT * FROM geo_scores WHERE task_id=?"
        params = [task_id]
        if category:
            query += " AND category=?"
            params.append(category)
        else:
            query += " AND category IS NULL"
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def delete_task_geo_scores(task_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM geo_scores WHERE task_id=?", (task_id,))
        await db.commit()
    finally:
        await db.close()


async def save_task_geo_scores(task_id: str, model_key: str, model_name: str,
                               category: Optional[str], scores: Dict):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO geo_scores
               (task_id, run_id, model_key, model_name, category,
                geo_score, coverage_rate, mention_rate, citation_rate,
                recommendation_rate, sentiment_score, avg_rank,
                total_questions, valid_responses)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, model_key, model_name, category,
             scores["geo_score"], scores["coverage_rate"], scores["mention_rate"],
             scores["citation_rate"], scores["recommendation_rate"],
             scores["sentiment_score"], scores["avg_rank"],
             scores["total_questions"], scores["valid_responses"])
        )
        await db.commit()
    finally:
        await db.close()


async def get_task_coverage(task_id: str) -> Dict:
    """返回 {model_key: {question_id: 'done'|'failed'|'missing'}}。
    done=有非空内容行；failed=有 error_message 行；missing=固定题集里没有的。"""
    task = await get_task(task_id)
    if not task:
        return {}
    all_qids = task["question_ids"]
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT model_key, question_id, raw_content, error_message FROM analysis_results WHERE task_id=?",
            (task_id,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    models = sorted({r["model_key"] for r in rows} | set())
    coverage: Dict[str, Dict[str, str]] = {mk: {} for mk in models}
    for r in rows:
        mk, qid = r["model_key"], r["question_id"]
        if r.get("error_message"):
            coverage.setdefault(mk, {})[qid] = "failed"
        elif r.get("raw_content"):
            coverage.setdefault(mk, {})[qid] = "done"
        else:
            coverage.setdefault(mk, {})[qid] = "failed"
    # 标 missing
    for mk in list(coverage.keys()):
        for qid in all_qids:
            coverage[mk].setdefault(qid, "missing")
    return coverage
```

- [ ] **Step 5: 写迁移幂等自检脚本**

Create `scripts/test_db_migration.py`:

```python
"""数据库迁移幂等自检：建 tasks 表 + task_id 列 + 唯一索引，重复运行无副作用。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")

    await db.init_db()
    # 验证 tasks 表存在
    conn = await db.get_db()
    try:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        assert (await cur.fetchone()) is not None, "tasks 表未创建"
        for table, col in [("evaluation_runs", "task_id"), ("evaluation_runs", "batch_id"),
                           ("analysis_results", "task_id"), ("analysis_results", "batch_id"),
                           ("geo_scores", "task_id")]:
            cur = await conn.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in await cur.fetchall()]
            assert col in cols, f"{table}.{col} 未添加"
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_ar_task_model_q'")
        assert (await cur.fetchone()) is not None, "唯一索引未创建"
    finally:
        await conn.close()

    # 幂等：再跑一次 init_db 不报错
    await db.init_db()
    print("✅ PASS: 迁移幂等（tasks 表 + task_id/batch_id 列 + 唯一索引）")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: 运行自检**

Run: `python scripts/test_db_migration.py`
Expected: `✅ PASS: 迁移幂等（tasks 表 + task_id/batch_id 列 + 唯一索引）`

- [ ] **Step 7: Commit**

```bash
git add backend/database.py scripts/test_db_migration.py
git commit -m "feat(db): tasks 顶层表 + task_id/batch_id 列迁移（幂等）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Task 领域服务（建任务/建批次/导入合并/重算/矩阵）

**Files:**
- Create: `backend/services/task_service.py`

**Interfaces:**
- Consumes: `database.create_task`/`get_task`/`list_tasks`/`delete_task`/`add_task_batch`/`list_task_batches`/`set_batch_status`/`save_task_analysis_result`/`get_task_results`/`delete_task_geo_scores`/`save_task_geo_scores`/`get_task_coverage`/`get_questions`（Task 1）；`metrics.MetricsCalculator`；`analyzer.ResponseAnalyzer`（既有）。
- Produces: `create_task_with_questions(task_id, name, categories, question_ids)`、`create_batch_config(task_id, model_keys, per_model_question_ids, delay)` → 返回 v2 配置 dict、`import_batch_results(task_id, data)` → 合并去重 + 重算、`recalculate_task_scores(task_id)`、`build_task_detail(task_id)`。

- [ ] **Step 1: 写 task_service 骨架 + 建任务**

Create `backend/services/task_service.py`:

```python
"""Task 领域服务：任务→模型→问题 三级架构的服务端逻辑。

职责：
  - 建任务（固定总题集）
  - 建下载批次（生成 v2 配置 JSON）
  - 导入本地 runner 结果（按 (task_id,model,question) 去重覆盖 + 重算评分）
  - 构建任务详情（覆盖率矩阵 + 批次列表）
"""
import os
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from metrics import MetricsCalculator


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


async def create_task_with_questions(name: str, question_ids: List[str],
                                     categories: Optional[List[str]] = None) -> Dict:
    """建任务，固定总题集。"""
    task_id = _new_id("task")
    return await db.create_task(task_id, name, question_ids, categories)


async def resolve_question_ids(question_ids: Optional[List[str]],
                               categories: Optional[List[str]]) -> List[str]:
    """从品类或显式 id 解析出固定总题集 id 列表。"""
    questions = await db.get_questions(
        category=categories[0] if categories and len(categories) == 1 else None,
        active_only=True,
    )
    if categories:
        questions = [q for q in questions if q["category"] in categories]
    if question_ids:
        questions = [q for q in questions if q["id"] in question_ids]
    return [q["id"] for q in questions]
```

- [ ] **Step 2: 写建批次 + v2 配置生成**

追加到 `backend/services/task_service.py`：

```python
async def create_batch_config(task_id: str, model_keys: List[str],
                              per_model_question_ids: Dict[str, List[str]],
                              delay: float = 8.0) -> Dict:
    """在 task 下建下载批次，返回 v2 配置 JSON（供前端下载、本地 runner 消费）。

    per_model_question_ids: {model_key: [question_id, ...]}，每模型独立题区间（总题集子集）。
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    total_qids = set(task["question_ids"])

    # 校验每模型题区间都是总题集子集
    for mk, qids in per_model_question_ids.items():
        if mk not in model_keys:
            raise ValueError(f"模型 {mk} 未在 model_keys 中")
        bad = [q for q in qids if q not in total_qids]
        if bad:
            raise ValueError(f"模型 {mk} 的题区间含任务总题集外的题: {bad[:3]}")

    # 取完整题对象（units 并集）
    union_qids = sorted({q for qids in per_model_question_ids.values() for q in qids})
    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in union_qids if qid in q_map]

    batch_id = _new_id("batch")
    run_id = _new_id("run")
    await db.add_task_batch(
        run_id=run_id, task_id=task_id, batch_id=batch_id,
        name=task["name"], model_keys=model_keys,
        question_ids=union_qids,
        per_model=per_model_question_ids,
        config={"delay": delay, "per_model_question_ids": per_model_question_ids},
    )

    config = {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "batch_id": batch_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model_question_ids[mk]} for mk in model_keys],
        "questions": questions,
        "delay": delay,
    }
    return config
```

- [ ] **Step 3: 写导入合并 + 重算评分**

追加到 `backend/services/task_service.py`：

```python
async def import_batch_results(task_id: str, data: Dict) -> Dict:
    """导入本地 runner 结果 JSON，按 (task_id,model,question) 去重覆盖，重算 task 评分。

    data 形如 {"meta": {"task_id","batch_id","run_id",...},
              "questions": [...], "analysis_results": {mk: [result,...]}}
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    meta = data.get("meta") or {}
    batch_id = meta.get("batch_id") or "batch_unknown"
    run_id = meta.get("run_id") or f"run_{batch_id}"

    analysis_results = data.get("analysis_results") or {}
    total_qids = set(task["question_ids"])

    inserted = 0
    for mk, results in analysis_results.items():
        for r in results:
            if r.get("question_id") not in total_qids:
                continue  # 固定题集外的题丢弃
            r["model_key"] = r.get("model_key", mk)
            await db.save_task_analysis_result(task_id, batch_id, run_id, r)
            inserted += 1

    # 重算 task 评分（覆盖）
    await recalculate_task_scores(task_id)

    return {"task_id": task_id, "batch_id": batch_id, "results_inserted": inserted}


async def recalculate_task_scores(task_id: str) -> None:
    """按当前 task 全部 analysis_results 重算 geo_scores 并覆盖。"""
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    await db.delete_task_geo_scores(task_id)

    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    # task 固定题集对应的题对象（用于自然问题过滤与品类）
    task_questions = [q_map[qid] for qid in task["question_ids"] if qid in q_map]

    results = await db.get_task_results(task_id)
    by_model: Dict[str, List[Dict]] = {}
    for r in results:
        by_model.setdefault(r["model_key"], []).append(r)

    calculator = MetricsCalculator()
    for mk, mresults in by_model.items():
        model_name = mresults[0].get("model_name") or mk
        analysis_objects = [_result_to_analysis(r) for r in mresults]
        scores = calculator.calculate_scores(analysis_objects, questions=task_questions)
        await db.save_task_geo_scores(task_id, mk, model_name, None, _scores_to_dict(scores))

        # 品类
        cat_map: Dict[str, List[Dict]] = {}
        for r in mresults:
            q = q_map.get(r["question_id"])
            if q:
                cat_map.setdefault(q["category"], []).append(r)
        for cat, cat_results in cat_map.items():
            cat_questions = [q for q in task_questions if q.get("category") == cat]
            cat_scores = calculator.calculate_scores(
                [_result_to_analysis(r) for r in cat_results], questions=cat_questions
            )
            await db.save_task_geo_scores(task_id, mk, model_name, cat, _scores_to_dict(cat_scores))


def _result_to_analysis(r: Dict):
    from analyzer import AnalysisResult
    return AnalysisResult(
        question_id=r["question_id"], model_key=r["model_key"],
        model_name=r.get("model_name") or r["model_key"],
        ucloud_mentioned=bool(r.get("ucloud_mentioned")),
        ucloud_mention_count=r.get("ucloud_mention_count", 0),
        ucloud_rank=r.get("ucloud_rank"),
        has_citation=bool(r.get("has_citation")),
        citation_count=r.get("citation_count", 0),
        ucloud_recommended=bool(r.get("ucloud_recommended")),
        ucloud_recommendation_strength=r.get("recommendation_strength", "none"),
        sentiment_score=r.get("sentiment_score", 0.5),
        sentiment_label=r.get("sentiment_label", "neutral"),
        position_weight=r.get("position_weight", 0.0),
        response_length=r.get("response_length", 0),
        raw_content=r.get("raw_content", ""),
    )


def _scores_to_dict(s) -> Dict:
    return {
        "geo_score": s.geo_score, "coverage_rate": s.coverage_rate,
        "mention_rate": s.mention_rate, "citation_rate": s.citation_rate,
        "recommendation_rate": s.recommendation_rate, "sentiment_score": s.sentiment_score,
        "avg_rank": s.avg_rank, "total_questions": s.total_questions,
        "valid_responses": s.valid_responses,
    }
```

- [ ] **Step 4: 写任务详情构建**

追加到 `backend/services/task_service.py`：

```python
async def build_task_detail(task_id: str) -> Optional[Dict]:
    task = await db.get_task(task_id)
    if not task:
        return None
    coverage = await db.get_task_coverage(task_id)
    batches = await db.list_task_batches(task_id)
    scores = await db.get_task_scores(task_id)

    all_qids = task["question_ids"]
    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in all_qids if qid in q_map]

    total_cells = len(all_qids) * max(len(coverage), 1)
    done_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "done")
    return {
        "task": task,
        "questions": questions,
        "coverage": coverage,
        "batches": batches,
        "scores": scores,
        "summary": {
            "total_cells": total_cells,
            "done_cells": done_cells,
            "missing_cells": total_cells - done_cells,
            "coverage_rate": round(done_cells / total_cells, 3) if total_cells else 0,
        },
    }


async def build_task_list_summary() -> List[Dict]:
    tasks = await db.list_tasks()
    out = []
    for t in tasks:
        coverage = await db.get_task_coverage(t["id"])
        all_qids = t["question_ids"]
        models = list(coverage.keys())
        total_cells = len(all_qids) * max(len(models), 1)
        done_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "done")
        out.append({
            **t,
            "models": models,
            "total_cells": total_cells,
            "done_cells": done_cells,
            "coverage_rate": round(done_cells / total_cells, 3) if total_cells else 0,
        })
    return out
```

- [ ] **Step 5: 写合并去重自检脚本**

Create `scripts/test_tasks_service.py`:

```python
"""task_service 自检：建任务 → 建批次 → 两次导入合并去重 → 矩阵 + 重算。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from services import task_service


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 插入 4 道测试题
    conn = await db.get_db()
    try:
        for i in range(1, 5):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "品牌词" if i <= 2 else "对比词", "品牌词" if i <= 2 else "对比词",
                 f"问题{i}", "medium")
            )
        await conn.commit()
    finally:
        await conn.close()

    # 1. 建任务（固定总题集 Q1..Q4）
    task = await task_service.create_task_with_questions("T1", ["Q1", "Q2", "Q3", "Q4"])
    task_id = task["id"]

    # 2. 建批次：deepseek 跑 Q1,Q2；kimi 跑 Q1,Q2,Q3
    cfg = await task_service.create_batch_config(
        task_id, ["deepseek", "kimi"],
        {"deepseek": ["Q1", "Q2"], "kimi": ["Q1", "Q2", "Q3"]}, delay=8
    )
    assert cfg["version"] == 2 and cfg["task_id"] == task_id
    assert len(cfg["units"]) == 2
    assert cfg["units"][0]["question_ids"] == ["Q1", "Q2"]

    # 3. 第一次导入：deepseek Q1,Q2 done
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
        "questions": [],
        "analysis_results": {
            "deepseek": [
                _mk("Q1", "deepseek", "UCloud 很好"), _mk("Q2", "deepseek", "UCloud 不错"),
            ]
        }
    })
    detail = await task_service.build_task_detail(task_id)
    assert detail["coverage"]["deepseek"]["Q1"] == "done"
    assert detail["coverage"]["deepseek"].get("Q3") == "missing"
    assert detail["coverage"]["deepseek"].get("Q4") == "missing"

    # 4. 第二次导入：deepseek 重导 Q1（覆盖）+ kimi Q1,Q2,Q3
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": "batch_2", "run_id": "run_2"},
        "questions": [],
        "analysis_results": {
            "deepseek": [_mk("Q1", "deepseek", "UCloud 覆盖更新")],
            "kimi": [_mk("Q1", "kimi", "UCloud"), _mk("Q2", "kimi", "UCloud"), _mk("Q3", "kimi", "UCloud")],
        }
    })
    # 去重覆盖：deepseek Q1 仍只有一条（不累积）
    results = await db.get_task_results(task_id, "deepseek")
    q1_rows = [r for r in results if r["question_id"] == "Q1"]
    assert len(q1_rows) == 1, f"deepseek Q1 应去重为 1 条，实得 {len(q1_rows)}"
    assert q1_rows[0]["raw_content"] == "UCloud 覆盖更新"

    detail = await task_service.build_task_detail(task_id)
    assert detail["coverage"]["kimi"]["Q3"] == "done"
    assert detail["summary"]["done_cells"] == 5  # deepseek Q1,Q2 + kimi Q1,Q2,Q3

    # 5. 评分重算存在
    scores = await db.get_task_scores(task_id)
    assert len(scores) >= 2, f"应有 2 个模型全局评分，实得 {len(scores)}"

    print("✅ PASS: task_service 合并去重 + 矩阵 + 重算")


def _mk(qid, mk, content):
    return {
        "question_id": qid, "model_key": mk, "model_name": mk.upper(),
        "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
        "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
        "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
        "position_weight": 0.5, "response_length": len(content), "raw_content": content,
        "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": [],
    }


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: 运行自检**

Run: `python scripts/test_tasks_service.py`
Expected: `✅ PASS: task_service 合并去重 + 矩阵 + 重算`

- [ ] **Step 7: Commit**

```bash
git add backend/services/task_service.py scripts/test_tasks_service.py
git commit -m "feat(service): task_service 建任务/建批次/导入合并/重算评分

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Pydantic 模型 + /api/tasks 路由组

**Files:**
- Modify: `backend/models.py`（加 Task* 模型）
- Create: `backend/routers/tasks.py`
- Modify: `backend/app.py`（注册 router + 鉴权）

**Interfaces:**
- Consumes: `task_service`（Task 2）；`database`（Task 1）。
- Produces: HTTP 路由 `POST/GET /api/tasks`、`GET/DELETE /api/tasks/{id}`、`POST /api/tasks/{id}/batches`、`POST /api/tasks/{id}/import-results`、`GET /api/tasks/{id}/scores`、`GET /api/tasks/{id}/details`。

- [ ] **Step 1: 加 Task Pydantic 模型**

在 `backend/models.py` 的 `# ============ 本地结果导入 ============` 段之前插入：

```python
# ============ 三级任务（任务→模型→问题） ============

class TaskCreate(BaseModel):
    name: str = "GEO评估"
    question_ids: Optional[List[str]] = None
    categories: Optional[List[str]] = None


class BatchCreate(BaseModel):
    model_keys: List[str]
    per_model_question_ids: Dict[str, List[str]]  # {model_key: [qid,...]}
    delay: float = 8.0

```

- [ ] **Step 2: 创建 tasks 路由**

Create `backend/routers/tasks.py`:

```python
"""三级任务路由：任务 → 模型 → 问题（仅 WebChat 模式范围）。"""
import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from routers.auth import require_admin
import models
import database as db
from services import task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("")
async def create_task(req: models.TaskCreate, user=Depends(require_admin)):
    """建任务，固定总题集。"""
    if not req.question_ids and not req.categories:
        raise HTTPException(400, "需提供 question_ids 或 categories 之一")
    qids = await task_service.resolve_question_ids(req.question_ids, req.categories)
    if not qids:
        raise HTTPException(400, "没有可评估的问题")
    task = await task_service.create_task_with_questions(req.name, qids, req.categories)
    return {"success": True, "data": task, "message": f"已创建任务，固定题集 {len(qids)} 题"}


@router.get("")
async def list_tasks():
    """任务列表（含覆盖率摘要）。"""
    items = await task_service.build_task_list_summary()
    return {"success": True, "data": items}


@router.get("/{task_id}")
async def get_task(task_id: str):
    detail = await task_service.build_task_detail(task_id)
    if not detail:
        raise HTTPException(404, "任务不存在")
    return {"success": True, "data": detail}


@router.delete("/{task_id}")
async def delete_task(task_id: str, user=Depends(require_admin)):
    await db.delete_task(task_id)
    return {"success": True}


@router.post("/{task_id}/batches")
async def create_batch(task_id: str, req: models.BatchCreate, user=Depends(require_admin)):
    """建下载批次，返回 v2 配置 JSON（前端下载，本地 runner 消费）。"""
    try:
        config = await task_service.create_batch_config(
            task_id, req.model_keys, req.per_model_question_ids, req.delay
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": config,
            "message": f"已生成批次配置（{len(req.model_keys)} 模型）"}


@router.post("/{task_id}/import-results")
async def import_results(task_id: str, file: UploadFile = File(...),
                         user=Depends(require_admin)):
    """导入本地 runner 结果 JSON，按 (task,model,question) 合并去重 + 重算。"""
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(400, f"JSON 解析失败: {e}")
    try:
        result = await task_service.import_batch_results(task_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": result,
            "message": f"已导入 {result['results_inserted']} 条结果并重算评分"}


@router.get("/{task_id}/scores")
async def get_scores(task_id: str, category: str = None):
    rows = await db.get_task_scores(task_id, category)
    return {"success": True, "data": rows}


@router.get("/{task_id}/details")
async def get_details(task_id: str, model_key: str = None, limit: int = 200, offset: int = 0):
    rows = await db.get_task_results(task_id, model_key)
    rows = rows[offset: offset + limit]
    return {"success": True, "data": rows}
```

- [ ] **Step 3: 注册路由 + 鉴权放行 import**

Modify `backend/app.py`:

把第 18 行
```python
from routers import evaluations, results, questions, settings, auth, webchat
```
改为：
```python
from routers import evaluations, results, questions, settings, auth, webchat, tasks
```

在第 116 行 `app.include_router(webchat.router)` 之后追加：
```python
app.include_router(tasks.router)
```

在 `PUBLIC_PATHS` 列表中删除 `"/api/evaluations/import/",` 这一行（导入已移到 `/api/tasks/{id}/import-results`，受 admin 保护，不再公开）。

在 `PROTECTED_PREFIXES` 列表中追加 `"/api/tasks",`（除 GET 列表/详情/评分外，写操作经 `require_admin`；GET 路由本身在 router 内不强制 admin，沿用现有 evaluations 的「列表/详情公开、写需 admin」约定）。

- [ ] **Step 4: 写路由冒烟自检**

Create `scripts/test_tasks_api.py`:

```python
"""tasks 路由冒烟：用 TestClient 打 POST/GET/batches/import 全链路。"""
import asyncio
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())

    conn = asyncio.run(_seed())
    from fastapi.testclient import TestClient
    # 临时关闭鉴权中间件对 /api/tasks 的拦截：通过 monkeypatch require_admin
    import routers.auth as auth
    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    auth.require_admin = _noop_admin
    # 重新 import tasks 以让其 Depends(require_admin) 拿到 noop
    import importlib, routers.tasks
    importlib.reload(routers.tasks)
    import app as appmod
    importlib.reload(appmod)

    client = TestClient(appmod.app)

    r = client.post("/api/tasks", json={"name": "T", "categories": ["品牌词"]})
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["id"]

    r = client.get("/api/tasks")
    assert r.status_code == 200 and len(r.json()["data"]) == 1

    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1", "Q2"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfg = r.json()["data"]
    assert cfg["version"] == 2 and cfg["task_id"] == task_id

    payload = {"meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
               "questions": [], "analysis_results": {"kimi": [_mk("Q1", "kimi")]}}
    r = client.post(f"/api/tasks/{task_id}/import-results",
                    files={"file": ("r.json", json.dumps(payload).encode(), "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["results_inserted"] == 1

    r = client.get(f"/api/tasks/{task_id}")
    assert r.json()["data"]["coverage"]["kimi"]["Q1"] == "done"

    print("✅ PASS: /api/tasks 全链路冒烟")


async def _seed():
    conn = await db.get_db()
    try:
        for i in range(1, 5):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "品牌词" if i <= 2 else "对比词",
                 "品牌词" if i <= 2 else "对比词", f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


def _mk(qid, mk):
    return {"question_id": qid, "model_key": mk, "model_name": mk.upper(),
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 5, "raw_content": "UCloud",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


if __name__ == "__main__":
    main()
```

> 说明：若环境无 `fastapi[all]` 的 TestClient 依赖（httpx），可改为直接调用 `asyncio.run(task_service.xxx())` 的等价冒烟；本仓库已用 FastAPI，默认带 httpx。若运行报 `ModuleNotFoundError: httpx`，先 `pip install httpx`。

- [ ] **Step 5: 运行冒烟**

Run: `python scripts/test_tasks_api.py`
Expected: `✅ PASS: /api/tasks 全链路冒烟`

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/routers/tasks.py backend/app.py scripts/test_tasks_api.py
git commit -m "feat(api): /api/tasks 路由组（建任务/批次/导入/评分/详情）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 删除旧端点 + results 路由加 task_id

**Files:**
- Modify: `backend/routers/evaluations.py`（删 `export-webchat-config`、`import-results`）
- Modify: `backend/routers/results.py`（`scores`/`details` 加可选 `task_id`）

**Interfaces:**
- Consumes: Task 1 的 task 查询函数。
- Produces: `GET /api/results/{task_id}/scores?task_id=` 形式支持（保留 run_id 兼容历史）。

- [ ] **Step 1: 删除 evaluations.py 的两个旧端点**

在 `backend/routers/evaluations.py` 中删除：
- 整个 `import_local_results` 函数（`@router.post("/import-results")` 装饰器起，到其函数体结束，约 130–250 行）。
- 整个 `export_webchat_config` 函数（`@router.post("/export-webchat-config")` 装饰器起，到函数体结束，约 297–346 行）。

同时删除因此变成未使用的 import：`UploadFile, File, Form` 从第 2 行的 fastapi import 中移除（保留 `APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Depends`）。

- [ ] **Step 2: results.py scores/details 加 task_id 支持**

打开 `backend/routers/results.py`，找到 `GET /{run_id}/scores` 与 `GET /{run_id}/details` 两个路由。为每个加可选 query 参数 `task_id: Optional[str] = None`，并在函数体内：

```python
# 在函数开头
if task_id:
    rows = await db.get_task_scores(task_id, category)  # scores 路由
    # 或 results 路由：
    # rows = await db.get_task_results(task_id, model_key)
    return {"success": True, "data": rows}
```

具体：在 `scores` 路由签名加 `task_id: Optional[str] = None`，函数体首部插入上述 `if task_id:` 分支（调用 `db.get_task_scores`）；`details` 路由同理调用 `db.get_task_results`。保留原有 run_id 逻辑作为 else 分支不动。

确认 `results.py` 顶部已 `from typing import Optional`（若无则加）。

- [ ] **Step 3: 冒烟回归**

Run: `python scripts/test_tasks_api.py`（应仍 PASS，因为旧端点删除不影响新链路）
Expected: `✅ PASS: /api/tasks 全链路冒烟`

另确认旧端点已删：
Run: `python -c "import sys; sys.path.insert(0,'backend'); import routers.evaluations as e; print([r.path for r in e.router.routes])"`
Expected: 输出中**不再包含** `/import-results` 与 `/export-webchat-config`。

- [ ] **Step 4: Commit**

```bash
git add backend/routers/evaluations.py backend/routers/results.py
git commit -m "refactor(api): 删除旧 export/import 端点，results 路由加 task_id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 调度器支持每模型独立题区间

**Files:**
- Modify: `core/scheduler.py`（`EvalScheduler.__init__` 加 `per_model_questions`；`prepare` 按它展开）

**Interfaces:**
- Consumes: `SqliteUnitStore.expand_units`（既有，签名 `expand_units(run_id, models, question_ids, model_names)`）。
- Produces: `EvalScheduler(..., per_model_questions=Optional[Dict[str, List[Dict]]])`——缺省退化为 `models × questions`，旧行为不变。

- [ ] **Step 1: 加 per_model_questions 入参**

在 `core/scheduler.py` 的 `EvalScheduler.__init__` 签名（约 143–153 行）末尾参数加：

```python
        per_model_questions: Optional[Dict[str, List[Dict]]] = None,
```

在 `__init__` 函数体内 `self.extra_policy = extra_policy or {}` 之后追加：

```python
        # 每模型独立题区间（v2 配置 units）。缺省 = 所有模型共享 questions（旧行为）。
        self.per_model_questions = per_model_questions
        if per_model_questions:
            # 限流器需覆盖所有出现过的模型
            extra_models = [mk for mk in per_model_questions if mk not in self.models]
            for mk in extra_models:
                self.models.append(mk)
                self.limiters[mk] = RateLimiter(mk, self._policy_for(mk))
            # 题序：所有模型题集的并集
            seen = {}
            for q in questions:
                seen.setdefault(q["id"], q)
            for mk, qs in per_model_questions.items():
                for q in qs:
                    seen.setdefault(q["id"], q)
            self._q_order = {qid: i for i, qid in enumerate(sorted(seen.keys()))}
        else:
            self._q_order = {q["id"]: i for i, q in enumerate(questions)}
```

并删除原 `__init__` 末尾那两行（已被上面分支取代）：
```python
        self._q_order = {q["id"]: i for i, q in enumerate(questions)}
        self._total = 0
```
改为在分支后补一行 `self._total = 0`。

- [ ] **Step 2: 改 prepare 按每模型题集展开**

把 `prepare` 方法（约 181–189 行）改为：

```python
    async def prepare(self) -> None:
        """展开单元（幂等）+ 重置残留 running。每模型按各自题区间展开。"""
        model_names = {mk: self._model_name(mk) for mk in self.models}
        if self.per_model_questions:
            total = 0
            for mk in self.models:
                qs = self.per_model_questions.get(mk, self.questions)
                total += self.store.expand_units(
                    self.run_id, [mk], [q["id"] for q in qs],
                    {mk: model_names.get(mk, mk)}
                )
            self._total = total
        else:
            self._total = self.store.expand_units(
                self.run_id, self.models, [q["id"] for q in self.questions], model_names
            )
        reset = self.store.reset_stale_running(self.run_id)
        logger.info(f"[SCHED {self.run_id}] prepared {self._total} units"
                    f"({len(self.models)} models), reset {reset} stale running")
```

并把 `_model_worker` 内 `q_text = {q["id"]: q["question"] for q in self.questions}` 改为按每模型题集：

```python
            # 预读该模型的问题文本（每模型题区间）
            if self.per_model_questions:
                qs = self.per_model_questions.get(model_key, self.questions)
            else:
                qs = self.questions
            q_text = {q["id"]: q["question"] for q in qs}
```

- [ ] **Step 3: 加 per_model_questions 自检到既有自检脚本**

在 `scripts/test_scheduler_selfcheck.py` 的 `main()` 末尾（`print("\n🎉 全部自检通过")` 之前）追加：

```python
    # ── 5. 每模型独立题区间 ──
    s = SqliteUnitStore(os.path.join(tmp, "permodel.db"))
    models5 = ["a", "b"]
    qs5 = make_questions(4)
    reg = {m: MockClient(m, {}, []) for m in models5}
    pmq = {"a": [qs5[0], qs5[1], qs5[3]],  # a 跑 Q1,Q2,Q4
           "b": [qs5[1], qs5[2]]}           # b 跑 Q2,Q3
    async def m5():
        await EvalScheduler("runP", models5, qs5, s, make_factory(reg),
                            extra_policy=fast_policy(models5),
                            per_model_questions=pmq).run()
    asyncio.run(m5())
    # a 应 done Q1,Q2,Q4；b 应 done Q2,Q3
    a_done = {u.question_id for u in s.list_units("runP", "done") if u.model_key == "a"}
    b_done = {u.question_id for u in s.list_units("runP", "done") if u.model_key == "b"}
    assert a_done == {"Q1", "Q2", "Q4"}, a_done
    assert b_done == {"Q2", "Q3"}, b_done
    assert s.counts("runP")["done"] == 5, s.counts("runP")
    print("✅ PASS: 每模型独立题区间（per_model_questions）")
```

- [ ] **Step 4: 运行既有自检回归**

Run: `python scripts/test_scheduler_selfcheck.py`
Expected: 5 项全 PASS，末尾 `🎉 全部自检通过`（含新增的「每模型独立题区间」）。

- [ ] **Step 5: Commit**

```bash
git add core/scheduler.py scripts/test_scheduler_selfcheck.py
git commit -m "feat(scheduler): EvalScheduler 支持 per_model_questions 每模型独立题区间

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 本地 runner 消费 v2 配置 + 结果透传 task_id

**Files:**
- Modify: `scripts/local_webchat_runner.py`（`run_local_eval` 加 `per_model_questions`/`task_meta` 参数；`_build_output` 透传；main 解析 v2 `units`）

**Interfaces:**
- Consumes: `EvalScheduler(per_model_questions=...)`（Task 5）。
- Produces: 结果 JSON `meta` 含 `task_id`/`batch_id`/`run_id`；`--config task_config.json` 接受 v2 `units`。

- [ ] **Step 1: _build_output 透传 task_meta**

把 `scripts/local_webchat_runner.py` 的 `_build_output`（约 194–214 行）签名与 meta 改为：

```python
def _build_output(run_id, model_keys, questions, all_results, geo_scores,
                  task_meta=None) -> Dict:
    fixed_geo_scores = {}
    for mk, scores_by_cat in geo_scores.items():
        fixed_geo_scores[mk] = {}
        for cat, scores in scores_by_cat.items():
            cat_key = cat if cat is not None else "__GLOBAL__"
            fixed_geo_scores[mk][cat_key] = scores
    meta = {
        "generated_at": datetime.now().isoformat(),
        "mode": "webchat_local",
        "run_id": run_id,
        "model_keys": model_keys,
        "total_questions": len(questions),
        "total_results": sum(len(v) for v in all_results.values()),
    }
    if task_meta:
        meta.update(task_meta)  # 透传 task_id / batch_id
    return {
        "meta": meta,
        "questions": questions,
        "analysis_results": {mk: all_results[mk] for mk in model_keys},
        "geo_scores": fixed_geo_scores,
    }
```

- [ ] **Step 2: run_local_eval 加 per_model_questions + task_meta 参数**

把 `run_local_eval` 签名（约 223–232 行）改为加两个可选参数：

```python
async def run_local_eval(
    model_keys: List[str],
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    delay: float = 8.0,
    output_path: str = "local_results.json",
    questions: Optional[List[Dict]] = None,
    run_id: Optional[str] = None,
    resume: bool = False,
    name: str = "GEO评估",
    per_model_questions: Optional[Dict[str, List[Dict]]] = None,
    task_meta: Optional[Dict] = None,
):
```

在函数内 `scheduler = EvalScheduler(...)` 处（约 348–352 行）传入 `per_model_questions`：

```python
    scheduler = EvalScheduler(
        run_id=run_id, models=model_keys, questions=questions, store=store,
        client_factory=client_factory, on_unit_done=on_unit_done, on_progress=on_progress,
        extra_policy=extra_policy,
        per_model_questions=per_model_questions,
    )
    await scheduler.run()
```

并把两处 `_build_output(...)` 调用（`_dump_partial` 内约 303 行、末尾约 388 行）都加 `task_meta=task_meta`：

```python
        out = _build_output(run_id, model_keys, questions, all_results, {}, task_meta=task_meta)
```
```python
    output = _build_output(run_id, model_keys, questions, all_results, geo_scores, task_meta=task_meta)
```

并在 `_save_manifest` 调用处（搜索 `_save_manifest(`）追加 `task_meta` 持久化：先改 `_save_manifest` 签名加 `task_meta=None`，写进 manifest dict；`_load_manifest` 读回时返回（续跑时透传）。具体——把 `_save_manifest` 改为：

```python
def _save_manifest(run_id: str, name: str, model_keys: List[str],
                   questions: List[Dict], delay: float, output_path: str,
                   task_meta: Optional[Dict] = None) -> str:
    os.makedirs(LOCAL_RUNS_DIR, exist_ok=True)
    path = os.path.join(LOCAL_RUNS_DIR, f"{run_id}.manifest.json")
    manifest = {
        "run_id": run_id, "name": name, "model_keys": model_keys,
        "delay": delay, "output_path": output_path, "questions": questions,
        "task_meta": task_meta or {},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path
```

在续跑恢复块（约 241–251 行）补：

```python
        task_meta = manifest.get("task_meta") or None
```

- [ ] **Step 3: main() 解析 v2 配置 units**

把 `main()` 中 `if args.config:` 块（约 517–542 行）替换为支持 v2（保留 v1 兼容回退）：

```python
    per_model_questions = None
    task_meta = None
    if args.config:
        print(f"  📥 从配置文件加载: {args.config}")
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)

        delay = config.get("delay", config.get("task", {}).get("delay", delay))
        preloaded_questions = config.get("questions")
        question_ids = config.get("question_ids")
        categories = config.get("categories")
        task_name = config.get("task_name") or config.get("task", {}).get("name", "GEO评估")

        if config.get("version") == 2 or "units" in config:
            # v2：每模型独立题区间
            units = config.get("units", [])
            model_keys = [u["model_key"] for u in units]
            q_map_cfg = {q["id"]: q for q in (preloaded_questions or [])}
            per_model_questions = {
                u["model_key"]: [q_map_cfg[qid] for qid in u["question_ids"] if qid in q_map_cfg]
                for u in units
            }
            # 缺题对象时退化为最小 dict（仅 id）
            for mk, qs in per_model_questions.items():
                if not qs:
                    per_model_questions[mk] = [{"id": qid, "question": qid, "category": "",
                                                "question_type": "", "tags": [], "difficulty": "medium"}
                                               for qid in next(u["question_ids"] for u in units if u["model_key"] == mk)]
            task_meta = {"task_id": config.get("task_id"), "batch_id": config.get("batch_id")}
            print(f"  任务(v2): {task_name} | task_id={task_meta['task_id']} | batch_id={task_meta['batch_id']}")
            print(f"  模型: {', '.join(model_keys)} | 单元: {sum(len(v) for v in per_model_questions.values())}")
        else:
            # v1 兼容
            model_keys = config["task"]["model_keys"]
            task_name = config["task"].get("name", "GEO评估")

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in task_name)
            output_path = f"output/webchat_{safe_name}_{timestamp}.json"
        print()
    else:
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"output/webchat_results_{timestamp}.json"
        if args.inline_questions:
            texts = args.inline_questions.split("||")
            preloaded_questions = [
                {"id": f"test_{i+1}", "category": "test", "question_type": "direct",
                 "question": t.strip(), "tags": [], "difficulty": "medium"}
                for i, t in enumerate(texts) if t.strip()
            ]
            print(f"  📝 使用内联问题: {len(preloaded_questions)} 个")
        elif args.questions != "all":
            if "," in args.questions:
                question_ids = args.questions.split(",")
            else:
                categories = [args.questions]
```

并把末尾 `asyncio.run(run_local_eval(...))` 调用（约 564–572 行）加两参数：

```python
    asyncio.run(run_local_eval(
        model_keys=model_keys,
        question_ids=question_ids,
        categories=categories,
        delay=delay,
        output_path=output_path,
        questions=preloaded_questions,
        name=task_name,
        per_model_questions=per_model_questions,
        task_meta=task_meta,
    ))
```

- [ ] **Step 4: 手动语法校验**

Run: `python -c "import ast; ast.parse(open('scripts/local_webchat_runner.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: v2 配置解析冒烟（mock，不真跑浏览器）**

Create `scripts/test_runner_v2_config.py`:

```python
"""v2 配置解析冒烟：构造 v2 配置，验证 main 解析出 per_model_questions + task_meta。
不跑浏览器，只验解析路径（monkeypatch run_local_eval）。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import local_webchat_runner as R


def main():
    cfg = {
        "version": 2, "task_id": "task_x", "task_name": "T", "batch_id": "batch_y",
        "run_id": "run_z", "delay": 8,
        "units": [{"model_key": "kimi", "question_ids": ["Q1", "Q2"]},
                  {"model_key": "deepseek", "question_ids": ["Q1"]}],
        "questions": [{"id": "Q1", "question": "q1", "category": "c", "question_type": "t",
                       "tags": [], "difficulty": "medium"},
                      {"id": "Q2", "question": "q2", "category": "c", "question_type": "t",
                       "tags": [], "difficulty": "medium"}],
    }
    cfg_path = os.path.join(tempfile.mkdtemp(), "task.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    captured = {}
    async def fake_run(**kw):
        captured.update(kw)
    R.run_local_eval = fake_run
    sys.argv = ["runner", "--config", cfg_path, "--headed"]
    R.main()

    assert captured.get("per_model_questions") is not None, "v2 未解析出 per_model_questions"
    assert set(captured["per_model_questions"].keys()) == {"kimi", "deepseek"}
    assert captured["per_model_questions"]["kimi"][0]["id"] == "Q1"
    assert captured["task_meta"] == {"task_id": "task_x", "batch_id": "batch_y"}
    print("✅ PASS: v2 配置解析（per_model_questions + task_meta 透传）")


if __name__ == "__main__":
    main()
```

Run: `python scripts/test_runner_v2_config.py`
Expected: `✅ PASS: v2 配置解析（per_model_questions + task_meta 透传）`

- [ ] **Step 6: Commit**

```bash
git add scripts/local_webchat_runner.py scripts/test_runner_v2_config.py
git commit -m "feat(runner): 本地 runner 消费 v2 配置（units 每模型题区间）+ 透传 task_id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 前端 API 客户端 + 路由

**Files:**
- Create: `frontend/src/api/tasks.js`
- Modify: `frontend/src/router/index.js`（加 `/tasks`、`/tasks/:taskId`）

**Interfaces:**
- Consumes: `/api/tasks` 路由（Task 3）；`apiFetch`（既有 `composables/useWebSocket`）。
- Produces: `createTask`/`listTasks`/`getTask`/`deleteTask`/`createBatch`/`importResults`/`getTaskScores`/`getTaskDetails` JS 函数。

- [ ] **Step 1: 创建 tasks API 客户端**

Create `frontend/src/api/tasks.js`:

```javascript
import { apiFetch } from '../composables/useWebSocket'

export function listTasks() {
  return apiFetch('/tasks')
}

export function createTask({ name, categories, question_ids }) {
  return apiFetch('/tasks', {
    method: 'POST',
    body: JSON.stringify({ name, categories: categories || null, question_ids: question_ids || null }),
  })
}

export function getTask(taskId) {
  return apiFetch(`/tasks/${taskId}`)
}

export function deleteTask(taskId) {
  return apiFetch(`/tasks/${taskId}`, { method: 'DELETE' })
}

export function createBatch(taskId, { model_keys, per_model_question_ids, delay }) {
  return apiFetch(`/tasks/${taskId}/batches`, {
    method: 'POST',
    body: JSON.stringify({ model_keys, per_model_question_ids, delay }),
  })
}

export function importResults(taskId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch(`/tasks/${taskId}/import-results`, { method: 'POST', body: formData })
}

export function getTaskScores(taskId, category = null) {
  const q = category ? `?category=${encodeURIComponent(category)}` : ''
  return apiFetch(`/tasks/${taskId}/scores${q}`)
}

export function getTaskDetails(taskId, modelKey = null) {
  const q = modelKey ? `?model_key=${encodeURIComponent(modelKey)}` : ''
  return apiFetch(`/tasks/${taskId}/details${q}`)
}
```

- [ ] **Step 2: 加路由**

Modify `frontend/src/router/index.js`，在 `routes` 数组中 `/evaluation` 行之后追加：

```javascript
  { path: '/tasks', name: 'TaskList', component: () => import('../views/TaskList.vue') },
  { path: '/tasks/:taskId', name: 'TaskDetail', component: () => import('../views/TaskDetail.vue') },
```

- [ ] **Step 3: 构建校验**

Run: `cd frontend && npm run build`
Expected: 构建成功（TaskList.vue/TaskDetail.vue 此时还未创建——若构建报缺文件，先在下一步 Task 8 创建空壳再回来；本 Step 可与 Task 8 合并校验）。

> 注：路由懒加载指向的组件必须存在，否则 build 失败。若想分步，可先把 Task 8 的两个 `.vue` 空壳建好再 build。本计划把 build 校验放在 Task 8 末尾统一做。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/tasks.js frontend/src/router/index.js
git commit -m "feat(frontend): tasks API 客户端 + /tasks 路由

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 前端 TaskList + TaskDetail 页

**Files:**
- Create: `frontend/src/views/TaskList.vue`
- Create: `frontend/src/views/TaskDetail.vue`

**Interfaces:**
- Consumes: `api/tasks.js`（Task 7）；Element Plus；`/questions/categories`、`/webchat/auth/status`（既有）。
- Produces: 任务列表页（新建向导）+ 任务详情页（矩阵+批次+导入）。

- [ ] **Step 1: 创建 TaskList.vue**

Create `frontend/src/views/TaskList.vue`:

```vue
<template>
  <div class="task-list">
    <h2 class="page-title">🚀 执行评测（任务 → 模型 → 问题）</h2>

    <el-card>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">任务列表</span>
        <el-button v-if="isAdmin()" type="primary" @click="openWizard">
          <el-icon><Plus /></el-icon> 新建任务
        </el-button>
      </div>
      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column prop="name" label="任务名" min-width="160" />
        <el-table-column label="模型">
          <template #default="{ row }">
            <el-tag v-for="m in row.models" :key="m" size="small" style="margin:2px">{{ m }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ (row.question_ids||[]).length }}</template>
        </el-table-column>
        <el-table-column label="覆盖率" width="160">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.coverage_rate||0)*100)" :status="row.coverage_rate>=1?'success':''" />
            <span style="font-size:12px;color:#999">{{ row.done_cells }}/{{ row.total_cells }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status==='active'?'success':'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="isAdmin()" size="small" type="danger" plain @click="onDel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建向导 -->
    <el-dialog v-model="wizard" title="新建任务" width="640px">
      <el-steps :active="step" finish-status="success" align-center>
        <el-step title="定任务总题集" />
        <el-step title="挂模型 + 题区间" />
      </el-steps>

      <div v-if="step===0" style="margin-top:20px">
        <el-form label-width="100px">
          <el-form-item label="任务名">
            <el-input v-model="form.name" placeholder="GEO评估" />
          </el-form-item>
          <el-form-item label="品类筛选">
            <el-select v-model="form.categories" multiple placeholder="全部品类" style="width:100%">
              <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>

      <div v-if="step===1" style="margin-top:20px">
        <el-alert type="info" :closable="false" style="margin-bottom:12px">
          任务总题集已固定为 {{ totalQids.length }} 题。下面添加本次要下载的模型与题区间（可后续再补）。
        </el-alert>
        <div v-for="(row, i) in batchRows" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
          <el-select v-model="row.model_key" placeholder="选模型" style="width:160px">
            <el-option v-for="m in readyModels" :key="m.key" :label="m.name" :value="m.key" :disabled="batchRows.some((r,j)=>j!==i&&r.model_key===m.key)" />
          </el-select>
          <el-select v-model="row.question_ids" multiple placeholder="题区间（默认全选）" style="flex:1">
            <el-option v-for="qid in totalQids" :key="qid" :label="qid" :value="qid" />
          </el-select>
          <el-button type="danger" link @click="batchRows.splice(i,1)">删</el-button>
        </div>
        <el-button size="small" @click="batchRows.push({model_key:'',question_ids:[]})">+ 添加模型</el-button>
        <el-form-item label="请求间隔" label-width="100px" style="margin-top:12px">
          <el-slider v-model="form.delay" :min="3" :max="15" :step="1" show-input />
        </el-form-item>
      </div>

      <template #footer>
        <el-button v-if="step>0" @click="step--">上一步</el-button>
        <el-button v-if="step===0" type="primary" @click="createTaskStep">下一步</el-button>
        <el-button v-if="step===1" type="success" @click="downloadBatch">下载任务配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch, isAdmin } from '../composables/useWebSocket'
import { listTasks, createTask, deleteTask, createBatch } from '../api/tasks'

const tasks = ref([])
const loading = ref(false)
const wizard = ref(false)
const step = ref(0)
const categories = ref([])
const models = ref([])
const webchatStatus = ref({})
const form = ref({ name: 'GEO评估', categories: [], delay: 8 })
const totalQids = ref([])
const createdTaskId = ref('')
const batchRows = ref([{ model_key: '', question_ids: [] }])

const readyModels = ref([])
const displayModels = ref([])

async function load() {
  loading.value = true
  try {
    const res = await listTasks()
    tasks.value = res.data || []
  } finally { loading.value = false }
}

async function openWizard() {
  step.value = 0
  form.value = { name: 'GEO评估', categories: [], delay: 8 }
  totalQids.value = []
  createdTaskId.value = ''
  batchRows.value = [{ model_key: '', question_ids: [] }]
  if (!categories.value.length) await loadConfig()
  wizard.value = true
}

async function loadConfig() {
  const [mRes, cRes, wsRes] = await Promise.all([
    apiFetch('/settings/models'),
    apiFetch('/questions/categories'),
    apiFetch('/webchat/auth/status'),
  ])
  models.value = (mRes.data && (mRes.data.models || mRes.data)) || []
  categories.value = cRes.data || []
  webchatStatus.value = wsRes.data || {}
  displayModels.value = models.value.map(m => {
    const ws = webchatStatus.value[m.key] || {}
    return { ...m, webchat_status: ws.has_auth ? 'ready' : 'no_auth' }
  })
  readyModels.value = displayModels.value.filter(m => m.webchat_status === 'ready')
}

async function createTaskStep() {
  const res = await createTask({ name: form.value.name, categories: form.value.categories.length ? form.value.categories : null })
  if (!res?.success) return ElMessage.error(res?.detail || '建任务失败')
  createdTaskId.value = res.data.id
  totalQids.value = res.data.question_ids || []
  step.value = 1
  if (!readyModels.value.length) await loadConfig()
  ElMessage.success(`任务已创建，总题集 ${totalQids.value.length} 题`)
}

async function downloadBatch() {
  const rows = batchRows.value.filter(r => r.model_key)
  if (!rows.length) return ElMessage.warning('请至少添加一个模型')
  const per_model = {}
  for (const r of rows) per_model[r.model_key] = r.question_ids.length ? r.question_ids : [...totalQids.value]
  const res = await createBatch(createdTaskId.value, { model_keys: Object.keys(per_model), per_model_question_ids: per_model, delay: form.value.delay })
  if (!res?.success) return ElMessage.error(res?.detail || '生成配置失败')
  const cfg = res.data
  const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `task_${form.value.name}_${cfg.batch_id}.json`
  document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
  ElMessage.success('任务配置已下载，请在本机运行 local_webchat_runner.py --config 该文件')
  wizard.value = false
  await load()
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.name}」及全部结果？`, '删除', { type: 'warning' })
  await deleteTask(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(async () => { await load(); await loadConfig() })
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
```

- [ ] **Step 2: 创建 TaskDetail.vue**

Create `frontend/src/views/TaskDetail.vue`:

```vue
<template>
  <div class="task-detail">
    <el-page-header @back="$router.push('/tasks')" style="margin-bottom:16px">
      <template #content>{{ detail?.task?.name }} — 任务详情</template>
    </el-page-header>

    <el-card v-if="detail" v-loading="loading">
      <div style="display:flex;gap:24px;margin-bottom:16px;flex-wrap:wrap">
        <el-statistic title="总格数" :value="detail.summary.total_cells" />
        <el-statistic title="已完成" :value="detail.summary.done_cells" />
        <el-statistic title="缺失" :value="detail.summary.missing_cells" />
        <div style="min-width:200px">
          <div style="font-size:12px;color:#999;margin-bottom:4px">覆盖率</div>
          <el-progress :percentage="Math.round(detail.summary.coverage_rate*100)" />
        </div>
        <el-button v-if="isAdmin()" type="success" @click="importDialog=true">
          <el-icon><Upload /></el-icon> 导入结果
        </el-button>
        <el-button v-if="detail.summary.coverage_rate>0" type="primary" @click="viewResult">
          <el-icon><DataAnalysis /></el-icon> 查看结果
        </el-button>
      </div>

      <!-- 覆盖率矩阵 -->
      <div style="overflow:auto">
        <table class="matrix">
          <thead>
            <tr>
              <th>模型 \\ 问题</th>
              <th v-for="q in detail.questions" :key="q.id" :title="q.question">{{ q.id }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="mk in Object.keys(detail.coverage)" :key="mk">
              <td class="row-head">{{ mk }}</td>
              <td v-for="q in detail.questions" :key="q.id"
                  :class="cellClass(detail.coverage[mk][q.id])"
                  :title="`${mk} / ${q.id}: ${detail.coverage[mk][q.id]||'missing'}`">
                {{ cellMark(detail.coverage[mk][q.id]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 批次列表 -->
      <h4 style="margin-top:20px">下载批次</h4>
      <el-table :data="detail.batches" size="small">
        <el-table-column prop="batch_id" label="批次ID" min-width="200" />
        <el-table-column label="模型">
          <template #default="{ row }">{{ (row.model_keys||[]).join(', ') }}</template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ (row.question_ids||[]).length }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column prop="id" label="run_id" min-width="200" />
      </el-table>
    </el-card>

    <!-- 导入对话框 -->
    <el-dialog v-model="importDialog" title="导入本地 runner 结果" width="480px">
      <el-upload drag :auto-upload="false" :on-change="onFile" accept=".json" :limit="1">
        <div style="padding:20px"><p style="color:#999">拖入 local_webchat_runner 产出的 .json</p></div>
      </el-upload>
      <div v-if="file" style="margin-top:12px">{{ file.name }}</div>
      <template #footer>
        <el-button type="primary" :loading="importing" :disabled="!file" @click="doImport">上传并合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { isAdmin } from '../composables/useWebSocket'
import { getTask, importResults } from '../api/tasks'

const route = useRoute()
const router = useRouter()
const detail = ref(null)
const loading = ref(false)
const importDialog = ref(false)
const file = ref(null)
const importing = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await getTask(route.params.taskId)
    if (res?.success) detail.value = res.data
    else ElMessage.error('任务不存在')
  } finally { loading.value = false }
}

function cellClass(s) {
  return { done: s === 'done', failed: s === 'failed', missing: !s || s === 'missing' }
}
function cellMark(s) {
  return s === 'done' ? '✓' : s === 'failed' ? '✗' : '·'
}
function onFile(f) { file.value = f.raw }
async function doImport() {
  importing.value = true
  try {
    const res = await importResults(route.params.taskId, file.value)
    if (!res?.success) return ElMessage.error(res?.detail || '导入失败')
    ElMessage.success(res.message)
    importDialog.value = false; file.value = null
    await load()
  } finally { importing.value = false }
}
function viewResult() {
  router.push({ path: '/dashboard', query: { task_id: route.params.taskId } })
}
onMounted(load)
</script>

<style scoped>
.matrix { border-collapse: collapse; font-size: 12px; }
.matrix th, .matrix td { border: 1px solid #ebeef5; padding: 4px 6px; text-align: center; min-width: 44px; }
.matrix th { background: #f5f7fa; }
.matrix td.row-head { background: #f5f7fa; font-weight: 600; position: sticky; left: 0; }
.matrix td.done { background: #d1fae5; color: #065f46; }
.matrix td.failed { background: #fee2e2; color: #991b1b; }
.matrix td.missing { background: #f3f4f6; color: #9ca3af; }
</style>
```

- [ ] **Step 3: 构建校验**

Run: `cd frontend && npm run build`
Expected: 构建成功，无报错。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/TaskList.vue frontend/src/views/TaskDetail.vue
git commit -m "feat(frontend): TaskList + TaskDetail 三级任务管理页

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 重写 Evaluation.vue 为任务管理入口 + 清理 agent 轮询

**Files:**
- Modify: `frontend/src/views/Evaluation.vue`（重写为跳转/嵌入任务页）
- Modify: `frontend/src/stores/evalProgress.js`（删 agent 轮询）
- Modify: `frontend/src/router/index.js`（`/evaluation` 改指向 TaskList 或重定向 `/tasks`）

**Interfaces:**
- Consumes: Task 7/8。
- Produces: `/evaluation` 即三级任务管理入口；无 `local_agent.py` 提示、无 agent 轮询。

- [ ] **Step 1: 重写 Evaluation.vue 为壳（直接复用 TaskList）**

把 `frontend/src/views/Evaluation.vue` 整体替换为：

```vue
<template>
  <TaskList />
</template>

<script setup>
import TaskList from './TaskList.vue'
</script>
```

- [ ] **Step 2: 清理 evalProgress.js 的 agent 轮询**

在 `frontend/src/stores/evalProgress.js` 中删除：`agentConnected` 相关 ref、`startAgentPoll`、`stopAgentPoll` 函数及其所有调用点（`Evaluation.vue` 原 `onModeChange` 里的 `evalStore.startAgentPoll()/stopAgentPoll()` 已随 Evaluation.vue 重写消失；store 内若有定义则一并删）。

> 若 store 中 `agentConnected` 被其他视图引用，grep 确认无引用后删除。保留 `startEval`/`connectWS`/心跳逻辑（API 模式仍由后端保留，前端虽不暴露入口但 store 不必删 startEval，避免破坏历史 run 的 WebSocket 恢复）。

- [ ] **Step 3: 全局 grep 确认无 local_agent 残留**

Run: `cd frontend && grep -rn "local_agent" src/ || echo "无残留"`
Expected: `无残留`

Run: `cd frontend && grep -rn "agentConnected\|startAgentPoll\|stopAgentPoll" src/ || echo "无残留"`
Expected: `无残留`

- [ ] **Step 4: 构建校验**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/Evaluation.vue frontend/src/stores/evalProgress.js
git commit -m "refactor(frontend): /evaluation 重构为三级任务入口，清理 local_agent/agent 轮询

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Dashboard 支持 task_id 查询 + 端到端验证

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`（识别 `?task_id=` 路由参数，调 `/api/results`/scores 时带 `task_id`）
- Verify: 全链路自检 + 迁移幂等回归

**Interfaces:**
- Consumes: Task 4 的 `results` task_id 支持；`api/tasks.js`。
- Produces: Dashboard 可用 `?task_id=` 展示任务级结果。

- [ ] **Step 1: Dashboard 识别 task_id**

打开 `frontend/src/views/Dashboard.vue`，找到读取 `run_id`（来自 `route.query.run_id`）的地方，补 `task_id`：

```javascript
const route = useRoute()
const runId = ref(route.query.run_id || '')
const taskId = ref(route.query.task_id || '')
```

把所有 `apiFetch('/results/${runId}/scores')` 与 `/results/${runId}/details` 调用改为：

```javascript
const scope = taskId.value
  ? { task_id: taskId.value }
  : { run_id: runId.value }
// scores:
apiFetch(`/results/${scope.run_id || '0'}/scores?task_id=${encodeURIComponent(scope.task_id || '')}`)
// details 同理
```

> 具体改法依 Dashboard.vue 现有取数函数而定：核心是「有 task_id 就在 query 带 task_id，后端 results 路由优先走 task 分支」。run_id 为占位 `'0'` 仅作 path 段，后端在有 task_id 时忽略 run_id。

- [ ] **Step 2: 全链路自检回归**

依次运行：
```bash
python scripts/test_db_migration.py
python scripts/test_tasks_service.py
python scripts/test_tasks_api.py
python scripts/test_runner_v2_config.py
python scripts/test_scheduler_selfcheck.py
```
Expected: 全部 PASS。

- [ ] **Step 3: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功。

- [ ] **Step 4: 手动端到端（小规模，需本机已配 webchat auth）**

```bash
# 1. 启动后端
cd backend && python -m uvicorn app:app --port 8000 &
# 2. 浏览器开 http://localhost:8000/evaluation → 新建任务 → 选 1 个已登录模型 + 2 题 → 下载配置
# 3. 本地跑：
python scripts/local_webchat_runner.py --config <下载的json> --headed
# 4. 在任务详情页「导入结果」上传产出 json → 矩阵刷新、评分出现
# 5. 「查看结果」跳 Dashboard 看任务级结果
```
Expected: 矩阵 done 格出现、导入后覆盖率上升、Dashboard 显示评分。

> 若本机无 webchat auth，可用 `scripts/test_tasks_api.py` 的合成数据替代真跑：手动构造一个结果 JSON（meta 带 task_id/batch_id）走导入验证矩阵与 Dashboard。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "feat(frontend): Dashboard 支持 ?task_id= 展示任务级结果

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review Checklist（plan 作者自检，已完成）

**1. Spec coverage:**
- tasks 顶层表 + task_id/batch_id 列 + 唯一索引 → Task 1 ✓
- 合并去重覆盖 + 重算评分 → Task 2 (import_batch_results / recalculate_task_scores) ✓
- /api/tasks 路由组 + v2 配置 + 结果 JSON 契约 → Task 3 ✓
- 删旧端点 + results task_id → Task 4 ✓
- 调度器 per_model_questions → Task 5 ✓
- runner v2 units + 透传 → Task 6 ✓
- 前端三级页（列表/向导/矩阵/批次/导入）→ Task 7/8 ✓
- 删 local_agent 提示 + agent 轮询 → Task 9 ✓
- Dashboard task_id → Task 10 ✓
- 迁移幂等 → Task 1 Step 5 ✓
- 调度器回归 → Task 5 Step 4 ✓

**2. Placeholder scan:** 无 TODO/TBD；每个 code step 含完整代码。Dashboard.vue Step 1 的取数改法因未读全文用「核心是…」描述 + 给出 scope 模式代码，属可执行指引（非 placeholder），执行时按现有函数套用。

**3. Type consistency:** `per_model_questions: Dict[str, List[Dict]]` 在 Task 5（scheduler）与 Task 6（runner）一致；`task_meta` dict 在 Task 6 `_build_output`/`_save_manifest`/main 一致；`save_task_analysis_result(task_id, batch_id, run_id, result)` 签名在 Task 1 定义、Task 2 调用一致；`create_batch_config(task_id, model_keys, per_model_question_ids, delay)` 在 Task 2 定义、Task 3 调用一致；前端 `createBatch(taskId, {model_keys, per_model_question_ids, delay})` 与后端 `BatchCreate` 字段一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-17-evaluation-three-level.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
