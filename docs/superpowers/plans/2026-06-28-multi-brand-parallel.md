# 多品牌并行独立评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把单品牌 GEO 评测系统升级为多品牌并行独立评测——`brand_id` 贯穿 questions/tasks/runs/results/scores，各品牌数据隔离，全局「当前品牌」选择器切换，UCloud 预置默认、首屏无感。

**Architecture:** 新建 `brands` 表存多品牌档案；现有 5 张业务表加 `brand_id` 列（默认 'ucloud'）+ 索引，迁移幂等补值。`_BRAND_PROFILE_CACHE` 由单值改为按 brand_id 缓存的 dict；评分重算改为按 `task.brand_id` 取 profile（修正切品牌串口径）。后端新增 `/api/brands` CRUD + current；前端新增 `useCurrentBrand` composable + 顶部选择器，Home 改品牌列表页，各页按当前品牌过滤并订阅切换重载。

**Tech Stack:** FastAPI + aiosqlite（后端）、Vue 3 `<script setup>` + Element Plus + Pinia（前端）、`core/brand_profile.py`（BrandProfile 不变）、Vite 构建。

## Global Constraints

- Windows 控制台默认 GBK；任何打印 emoji/✓ 的 Python 自检脚本顶部必须 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 或用 `io.TextIOWrapper` 兜底（见 `scripts/test_db_migration.py:8-10` 现有模式）。
- 自检脚本统一放 `scripts/test_*.py`，用临时 `tempfile.mkdtemp()` 的 geo.db 跑，不碰真实数据；运行方式 `python scripts/test_xxx.py`，断言失败抛异常 + 打印 `✅ PASS:` 成功。
- DB 迁移必须幂等：`column_exists()` 前置检查（`backend/database.py:348`）→ `ALTER TABLE ADD COLUMN ... DEFAULT 'ucloud'`（SQLite 自动给现有行补默认值）→ `CREATE INDEX IF NOT EXISTS`。
- 字段名 `is_ucloud`（citations/all_cited_urls 布尔标记）保留不动，语义泛化为"是否被测品牌官方引用"——本次不改。
- `core/metrics.py`、`core/brand_profile.py`、`core/analyzer.py` 不改（签名不变，只改调用方传对的 profile）。
- `task_units` 表不加 brand_id（按 run_id 关联，run 已带）。
- 旧 `/api/settings/brand-profile` 保留兜底（GET 返回 current 品牌档案；PUT 转发更新 current 品牌），避免老前端缓存报错。
- 提交信息末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`；在 master 分支上工作时先开新分支。

---

## File Structure

**Create:**
- `backend/routers/brands.py` — 品牌 CRUD + current 路由（prefix `/api/brands`）。
- `frontend/src/composables/useCurrentBrand.js` — 全局当前品牌 reactive 状态 + 切换 + 订阅事件。
- `frontend/src/api/brands.js` — brands API 封装。
- `scripts/test_brands_db.py` — brands 表 + CRUD + current 自检。
- `scripts/test_brand_profile_cache.py` — 缓存按 brand_id 取 + 评分按 task.brand_id 取口径自检。
- `scripts/test_brands_api.py` — `/api/brands` 全链路 TestClient 冒烟。
- `scripts/test_multi_brand_isolation.py` — 两品牌题集/任务/评分隔离 + 切品牌不串口径端到端自检。

**Modify:**
- `backend/database.py` — brands 表 schema + brand_id 列/索引迁移 + 缓存层改造 + brand CRUD + current + 查询过滤 + 写入带 brand_id。
- `backend/app.py` — 注册 brands router + `/api/brands` 加鉴权。
- `backend/models.py` — `BrandCreate`/`BrandUpdate`/`CurrentBrandUpdate` pydantic 模型；`TaskCreate`/`QuestionGenerate` 加可选 `brand_id`。
- `backend/routers/brands.py` — 新增（见上）。
- `backend/routers/questions.py` — list/create/generate 带 brand_id。
- `backend/routers/tasks.py` — list/create 带 brand_id。
- `backend/routers/settings.py` — brand-profile 兜底转发。
- `backend/routers/evaluations.py` — recalculate-scores 用 current_brand_id（无 task 时）。
- `backend/services/task_service.py` — recalculate/create_batch_config 按 task.brand_id 取 profile；config 带 brand_id。
- `backend/services/question_generator.py` — generate_and_replace 绑定 brand_id。
- `frontend/src/App.vue` — 顶部当前品牌选择器。
- `frontend/src/views/Home.vue` — 改品牌列表页。
- `frontend/src/views/Questions.vue` — 按当前品牌过滤 + 生成预填 + 订阅切换。
- `frontend/src/views/TaskList.vue` — 按当前品牌过滤 + 订阅切换。
- `frontend/src/views/Dashboard.vue` — 任务下拉带 brand_id + 订阅切换。
- `frontend/src/views/Settings.vue` — 移除品牌关键词区（迁到品牌编辑）。
- `frontend/src/api/tasks.js` — listTasks/createTask 带 brand_id 可选。

---

## Task 1: brands 表 + brand_id 列迁移

**Files:**
- Modify: `backend/database.py`（SCHEMA_SQL + `_migrate_add_columns` + init_db 预置 ucloud）
- Test: `scripts/test_db_migration.py`（扩展现有断言）

**Interfaces:**
- Produces: `brands` 表存在；`questions`/`tasks`/`evaluation_runs`/`analysis_results`/`geo_scores` 各有 `brand_id` 列（默认 'ucloud'）+ 索引；init_db 后 `brands` 表至少有 1 行（ucloud）；`app_settings.current_brand_id='ucloud'`。

- [ ] **Step 1: 写失败测试（扩展 test_db_migration.py）**

在 `scripts/test_db_migration.py` 的 `main()` 末尾、`print("✅ PASS...")` 之前追加：

```python
        # brands 表 + brand_id 列 + 预置 ucloud
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='brands'")
        assert (await cur.fetchone()) is not None, "brands 表未创建"
        for table in ["questions", "tasks", "evaluation_runs", "analysis_results", "geo_scores"]:
            cur = await conn.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in await cur.fetchall()]
            assert "brand_id" in cols, f"{table}.brand_id 未添加"
        cur = await conn.execute("SELECT COUNT(*) FROM brands")
        assert (await cur.fetchone())[0] >= 1, "brands 表应预置至少 1 行"
        cur = await conn.execute("SELECT id FROM brands WHERE id='ucloud'")
        assert (await cur.fetchone()) is not None, "未预置 ucloud 品牌"
        cur = await conn.execute("SELECT value FROM app_settings WHERE key='current_brand_id'")
        row = await cur.fetchone()
        assert row and row["value"] == "ucloud", f"current_brand_id 应为 ucloud，实得 {row['value'] if row else None}"
        # 现有 questions 行的 brand_id 默认补为 ucloud（init_db 导入默认题后）
        cur = await conn.execute("SELECT DISTINCT brand_id FROM questions")
        bids = [r["brand_id"] for r in await cur.fetchall()]
        assert bids == ["ucloud"] or bids == [], f"questions.brand_id 应默认 ucloud，实得 {bids}"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python scripts/test_db_migration.py`
Expected: FAIL with "brands 表未创建"

- [ ] **Step 3: SCHEMA_SQL 加 brands 表**

在 `backend/database.py` 的 `SCHEMA_SQL` 字符串末尾（`tasks` 表 CREATE 之后、闭合 `"""` 之前）追加：

```sql

CREATE TABLE IF NOT EXISTS brands (
    id                 TEXT PRIMARY KEY,
    brand_name         TEXT NOT NULL,
    company_name       TEXT DEFAULT '',
    website           TEXT DEFAULT '',
    industry          TEXT DEFAULT '',
    brand_profile_json TEXT NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active         INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_brands_active ON brands(is_active);
```

- [ ] **Step 4: _migrate_add_columns 加 brand_id 列 + 索引**

在 `backend/database.py` 的 `_migrate_add_columns(db)` 函数末尾（`idx_ar_task_model_q` 唯一索引 commit 之后）追加：

```python
    # 多品牌：questions/tasks/runs/results/scores 加 brand_id（默认 ucloud）+ 索引
    for table in ["questions", "tasks", "evaluation_runs", "analysis_results", "geo_scores"]:
        if not await column_exists(db, table, "brand_id"):
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN brand_id TEXT DEFAULT 'ucloud'"
            )
            await db.commit()
    await db.execute("CREATE INDEX IF NOT EXISTS idx_questions_brand ON questions(brand_id, is_active)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_brand ON tasks(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_brand ON evaluation_runs(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_results_brand ON analysis_results(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_scores_brand ON geo_scores(brand_id)")
    await db.commit()
```

- [ ] **Step 5: init_db 预置 ucloud + current_brand_id**

在 `backend/database.py` 的 `init_db()` 中，`await refresh_brand_profile_cache()`（约 `:345`）这一行**之前**插入预置逻辑。先把该行改为 `await refresh_brand_cache()`（Task 2 实现该函数；此处先调用，Task 2 落地后可用）。预置块：

```python
        # 预置 ucloud 品牌 + current_brand_id（多品牌迁移：幂等）
        await _ensure_default_brand(db)
```

并在 `_migrate_add_columns` 函数下方新增辅助函数：

```python
async def _ensure_default_brand(db: aiosqlite.Connection):
    """幂等预置 ucloud 品牌 + current_brand_id。已有 brands 行则不覆盖。"""
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    from brand_profile import default_brand_profile

    cur = await db.execute("SELECT COUNT(*) FROM brands")
    n = (await cur.fetchone())[0]
    if n == 0:
        profile = default_brand_profile()
        await db.execute(
            "INSERT OR IGNORE INTO brands (id, brand_name, company_name, website, industry, brand_profile_json, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("ucloud", profile.brand_name, profile.company_name,
             profile.website, profile.industry, profile.to_json())
        )
        await db.commit()
    # current_brand_id 默认 ucloud
    await db.execute(
        "INSERT INTO app_settings (key, value) VALUES ('current_brand_id', 'ucloud') "
        "ON CONFLICT(key) DO NOTHING"
    )
    await db.commit()
```

> 注：`init_db` 原末尾 `await refresh_brand_profile_cache()` 改名为 `await refresh_brand_cache()`，由 Task 2 实现并替换。本 task 先把调用名改对，若 Task 2 尚未落地，临时保留 `refresh_brand_profile_cache` 名亦不影响本 task 测试（测试只查表/列/预置行/current_brand_id，不依赖缓存函数名）。**为避免编译期 NameError，本 task 先保留原 `refresh_brand_profile_cache` 调用名不动，Task 2 再统一改名。** 即 Step 5 只加 `_ensure_default_brand(db)` 调用 + 函数定义，不动 refresh 那行。

- [ ] **Step 6: 运行测试，确认通过**

Run: `python scripts/test_db_migration.py`
Expected: `✅ PASS: 迁移幂等（tasks 表 + task_id/batch_id 列 + 唯一索引）`

- [ ] **Step 7: 提交**

```bash
git add backend/database.py scripts/test_db_migration.py
git commit -m "feat(db): brands 表 + brand_id 贯穿 + 预置 ucloud/current_brand_id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 品牌档案缓存层改造（按 brand_id 缓存）

**Files:**
- Modify: `backend/database.py`（`_BRAND_PROFILE_CACHE`/`get_brand_profile`/`refresh_brand_profile_cache`/`save_brand_profile`/`_active_brand_profile`）
- Test: `scripts/test_brand_profile_cache.py`（新建）

**Interfaces:**
- Produces:
  - `get_brand_profile(brand_id: str | None = None) -> BrandProfile` —— None 时取 current_brand_id
  - `get_brand_profile_by_id(brand_id: str) -> BrandProfile` —— 显式按 id 取（评分用），未命中 fallback default_brand_profile()
  - `refresh_brand_cache() -> None` —— 启动/CRUD 后重载所有 active 品牌到缓存
  - `get_current_brand_id() -> str` / `set_current_brand_id(brand_id) -> None` —— async
- Consumes: Task 1 的 brands 表 + current_brand_id 键。

- [ ] **Step 1: 写失败测试**

新建 `scripts/test_brand_profile_cache.py`：

```python
"""品牌档案缓存层自检：按 brand_id 缓存 + current 切换 + 显式取。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from brand_profile import BrandProfile, derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # current 默认 ucloud
    cur_id = await db.get_current_brand_id()
    assert cur_id == "ucloud", f"current 应为 ucloud，实得 {cur_id}"

    # get_brand_profile() 返回 current(ucloud) 档案
    p = db.get_brand_profile()
    assert p.brand_name == "UCloud", f"默认档案应为 UCloud，实得 {p.brand_name}"

    # 新建第二个品牌 acme 并设为 current
    acme = derive_from_input("Acme云", "阿克米科技", "https://www.acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)
    await db.set_current_brand_id("acme")
    assert await db.get_current_brand_id() == "acme"

    # current 切换后 get_brand_profile() 返回 acme
    p2 = db.get_brand_profile()
    assert p2.brand_name == "Acme云", f"切后应为 Acme云，实得 {p2.brand_name}"

    # 显式按 id 取 ucloud（不依赖 current）
    p3 = db.get_brand_profile_by_id("ucloud")
    assert p3.brand_name == "UCloud", f"显式取 ucloud 应为 UCloud，实得 {p3.brand_name}"

    # 不存在的 id fallback default
    p4 = db.get_brand_profile_by_id("not_exist")
    assert p4.brand_name == "UCloud", "不存在的 brand_id 应 fallback UCloud 默认"

    print("✅ PASS: 品牌档案缓存按 brand_id 取 + current 切换")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python scripts/test_brand_profile_cache.py`
Expected: FAIL with `AttributeError: module 'database' has no attribute 'get_current_brand_id'`（或 `create_brand`）

- [ ] **Step 3: 改造缓存层**

在 `backend/database.py`，把现有的单值缓存块（约 `:23-49`）：

```python
_BRAND_PROFILE_CACHE: Optional[BrandProfile] = None


def _active_brand_profile() -> BrandProfile:
    return _BRAND_PROFILE_CACHE or default_brand_profile()


def get_brand_profile() -> BrandProfile:
    return _active_brand_profile()


async def refresh_brand_profile_cache():
    global _BRAND_PROFILE_CACHE
    saved = await get_setting("brand_profile", "")
    if saved:
        try:
            _BRAND_PROFILE_CACHE = BrandProfile.from_dict(json.loads(saved))
            return
        except (ValueError, TypeError):
            pass
    _BRAND_PROFILE_CACHE = default_brand_profile()
```

替换为：

```python
# 多品牌：按 brand_id 缓存档案；current_brand_id 指向当前选中品牌。
_BRAND_PROFILE_CACHE: Dict[str, BrandProfile] = {}


def _active_brand_profile() -> BrandProfile:
    """同步辅助：返回 current 品牌档案（缓存未就绪时 fallback UCloud 默认）。
    仅供不能 await 的同步循环（如 is_ucloud_related_citation）兜底用，
    主路径请用 get_brand_profile / get_brand_profile_by_id。"""
    return _BRAND_PROFILE_CACHE.get(_sync_current_brand_id()) or default_brand_profile()


def _sync_current_brand_id() -> str:
    """同步读 current_brand_id 缓存值（由 refresh_brand_cache 预填到 _CURRENT_BRAND_ID_SYNC）。"""
    return _CURRENT_BRAND_ID_SYNC or "ucloud"


_CURRENT_BRAND_ID_SYNC: str = "ucloud"


def get_brand_profile(brand_id: Optional[str] = None) -> BrandProfile:
    """取某品牌档案；brand_id 为 None 时取 current_brand_id。
    缓存未命中时 fallback UCloud 默认（不抛异常，保证同步调用安全）。"""
    bid = brand_id or _sync_current_brand_id()
    return _BRAND_PROFILE_CACHE.get(bid) or default_brand_profile()


def get_brand_profile_by_id(brand_id: str) -> BrandProfile:
    """显式按 brand_id 取档案（评分重算用，不依赖 current）。未命中 fallback default。"""
    return _BRAND_PROFILE_CACHE.get(brand_id) or default_brand_profile()


async def get_current_brand_id() -> str:
    """异步读 current_brand_id（app_settings）。"""
    return await get_setting("current_brand_id", "ucloud") or "ucloud"


async def set_current_brand_id(brand_id: str):
    """设 current_brand_id 并同步到 _CURRENT_BRAND_ID_SYNC 缓存。"""
    global _CURRENT_BRAND_ID_SYNC
    await set_setting("current_brand_id", brand_id)
    _CURRENT_BRAND_ID_SYNC = brand_id


async def refresh_brand_cache():
    """启动/品牌 CRUD 后重载所有 active 品牌档案到缓存 + 同步 current_brand_id。"""
    global _CURRENT_BRAND_ID_SYNC
    _BRAND_PROFILE_CACHE.clear()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, brand_profile_json FROM brands WHERE is_active=1")
        rows = await cursor.fetchall()
    finally:
        await db.close()
    for r in rows:
        try:
            _BRAND_PROFILE_CACHE[r["id"]] = BrandProfile.from_dict(json.loads(r["brand_profile_json"]))
        except (ValueError, TypeError):
            pass
    if not _BRAND_PROFILE_CACHE:
        _BRAND_PROFILE_CACHE["ucloud"] = default_brand_profile()
    _CURRENT_BRAND_ID_SYNC = await get_current_brand_id()


# 向后兼容别名（旧调用方仍可用）
async def refresh_brand_profile_cache():
    await refresh_brand_cache()
```

- [ ] **Step 4: 改 save_brand_profile 为 update_brand（按 brand_id 更新 brands 行）**

把 `backend/database.py` 的 `save_brand_profile`（约 `:740`）替换：

```python
async def save_brand_profile(profile: BrandProfile, brand_id: str = None):
    """更新某品牌档案到 brands 表并刷新缓存。
    brand_id 为 None 时更新 current 品牌。同时镜像 brand_keywords 兼容旧接口。"""
    bid = brand_id or await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE brands SET brand_profile_json=?, brand_name=?, company_name=?, website=?, industry=? "
            "WHERE id=?",
            (profile.to_json(), profile.brand_name, profile.company_name,
             profile.website, profile.industry, bid)
        )
        await db.commit()
    finally:
        await db.close()
    await set_setting("brand_keywords", json.dumps(profile.keywords, ensure_ascii=False))
    _BRAND_PROFILE_CACHE[bid] = profile
```

- [ ] **Step 5: init_db 调用 refresh_brand_cache**

在 `backend/database.py` 的 `init_db()` 末尾，把 `await refresh_brand_profile_cache()` 改为 `await refresh_brand_cache()`（若 Task 1 已保留旧名，此处统一改对）。

- [ ] **Step 6: 运行缓存测试**

Run: `python scripts/test_brand_profile_cache.py`
Expected: `✅ PASS: 品牌档案缓存按 brand_id 取 + current 切换`
（若因 `create_brand` 未定义失败，Task 3 补；本 task 先确认缓存层语法正确——`create_brand` 在 Task 3 落地，故本 task 测试可暂跳过 create 分支，改为只测 get/fallback：把测试里 `create_brand`/`set_current_brand_id` 调用注释，待 Task 3 后取消注释。）

> 实操：本 task 与 Task 3 强耦合（create_brand 在 Task 3）。**合并验证**：本 task 先落地缓存层代码 + 改名，Task 3 落地 create_brand 后再一起跑该测试。即 Step 6 在 Task 3 完成后执行。

- [ ] **Step 7: 运行现有自检防回归**

Run: `python scripts/test_tasks_service.py`
Expected: `✅ PASS: task_service 合并去重 + 矩阵 + 重算`（确认缓存层改造未破坏 task_service，task_service 还用 `db.get_brand_profile()` 现返回 current=ucloud 默认档案，行为不变）

- [ ] **Step 8: 提交**

```bash
git add backend/database.py scripts/test_brand_profile_cache.py
git commit -m "feat(db): 品牌档案缓存按 brand_id 取 + current 切换 + 兼容别名

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: brands CRUD + current DB 函数

**Files:**
- Modify: `backend/database.py`（新增 `list_brands`/`get_brand`/`create_brand`/`update_brand`/`delete_brand`/`get_current_brand_id`/`set_current_brand_id`——后两个已在 Task 2 落地）
- Test: `scripts/test_brands_db.py`（新建）

**Interfaces:**
- Produces:
  - `list_brands() -> List[Dict]` —— 返回 [{id, brand_name, company_name, website, industry, created_at, is_active, question_count, task_count}, ...]（含题集数/任务数摘要）
  - `get_brand(brand_id) -> Optional[Dict]` —— 单品牌（含 brand_profile dict）
  - `create_brand(brand_id, profile: BrandProfile) -> Dict` —— 新建（id 冲突抛 ValueError）
  - `update_brand(brand_id, profile) -> None`
  - `delete_brand(brand_id) -> None` —— 软删 is_active=0（若有活跃题集/任务，抛 ValueError 提示先清空）
- Consumes: Task 2 的缓存层。

- [ ] **Step 1: 写失败测试**

新建 `scripts/test_brands_db.py`：

```python
"""brands 表 CRUD + current 自检。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from brand_profile import derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # list 含预置 ucloud
    brands = await db.list_brands()
    assert any(b["id"] == "ucloud" for b in brands), "应预置 ucloud"

    # create acme
    acme = derive_from_input("Acme云", "阿克米科技", "https://www.acme-cloud.cn", "云计算")
    created = await db.create_brand("acme", acme)
    assert created["id"] == "acme" and created["brand_name"] == "Acme云"

    # id 冲突
    try:
        await db.create_brand("acme", acme)
        assert False, "重复 id 应抛 ValueError"
    except ValueError:
        pass

    # get
    b = await db.get_brand("acme")
    assert b and b["brand_profile"]["brand_name"] == "Acme云"

    # update
    acme2 = derive_from_input("Acme云2", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.update_brand("acme", acme2)
    b2 = await db.get_brand("acme")
    assert b2["brand_name"] == "Acme云2"

    # current 切换
    await db.set_current_brand_id("acme")
    assert await db.get_current_brand_id() == "acme"

    # delete：无活跃数据可软删
    await db.delete_brand("acme")
    b3 = await db.get_brand("acme")
    assert b3 is None or b3["is_active"] == 0, "删除后应不可见或 is_active=0"

    # 切回 ucloud
    await db.set_current_brand_id("ucloud")
    print("✅ PASS: brands CRUD + current")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python scripts/test_brands_db.py`
Expected: FAIL with `AttributeError: module 'database' has no attribute 'list_brands'`

- [ ] **Step 3: 实现 CRUD 函数**

在 `backend/database.py` 的 `save_brand_profile` 下方（品牌档案区）新增：

```python
# ============ 品牌库（多品牌） ============

async def list_brands() -> List[Dict]:
    """列出所有 active 品牌，含题集数/任务数摘要。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT b.id, b.brand_name, b.company_name, b.website, b.industry, "
            "b.created_at, b.is_active, "
            "(SELECT COUNT(*) FROM questions WHERE brand_id=b.id AND is_active=1) AS question_count, "
            "(SELECT COUNT(*) FROM tasks WHERE brand_id=b.id AND status='active') AS task_count "
            "FROM brands b WHERE b.is_active=1 ORDER BY b.created_at ASC"
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_brand(brand_id: str) -> Optional[Dict]:
    """取单品牌（含 brand_profile dict）。仅返回 active。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM brands WHERE id=? AND is_active=1", (brand_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        b = dict(row)
        try:
            b["brand_profile"] = json.loads(b["brand_profile_json"])
        except (ValueError, TypeError):
            b["brand_profile"] = {}
        return b
    finally:
        await db.close()


async def create_brand(brand_id: str, profile: BrandProfile) -> Dict:
    """新建品牌。id 冲突抛 ValueError。"""
    db = await get_db()
    try:
        existing = await db.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,))
        if await existing.fetchone():
            raise ValueError(f"品牌 id '{brand_id}' 已存在")
        await db.execute(
            "INSERT INTO brands (id, brand_name, company_name, website, industry, brand_profile_json, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (brand_id, profile.brand_name, profile.company_name,
             profile.website, profile.industry, profile.to_json())
        )
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE[brand_id] = profile
    return {"id": brand_id, "brand_name": profile.brand_name,
            "company_name": profile.company_name, "website": profile.website,
            "industry": profile.industry}


async def update_brand(brand_id: str, profile: BrandProfile):
    """更新品牌档案（重新 derive 后调用）。"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE brands SET brand_name=?, company_name=?, website=?, industry=?, brand_profile_json=? "
            "WHERE id=?",
            (profile.brand_name, profile.company_name, profile.website,
             profile.industry, profile.to_json(), brand_id)
        )
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE[brand_id] = profile


async def delete_brand(brand_id: str):
    """软删品牌（is_active=0）。若有活跃题集/任务，抛 ValueError 提示先清空。
    ucloud 不可删。"""
    if brand_id == "ucloud":
        raise ValueError("ucloud 为预置默认品牌，不可删除")
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM questions WHERE brand_id=? AND is_active=1 LIMIT 1", (brand_id,))
        if await cur.fetchone():
            raise ValueError(f"品牌 '{brand_id}' 仍有活跃题集，请先清空题集再删")
        cur = await db.execute("SELECT 1 FROM tasks WHERE brand_id=? AND status='active' LIMIT 1", (brand_id,))
        if await cur.fetchone():
            raise ValueError(f"品牌 '{brand_id}' 仍有活跃任务，请先删除任务再删")
        await db.execute("UPDATE brands SET is_active=0 WHERE id=?", (brand_id,))
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE.pop(brand_id, None)
```

- [ ] **Step 4: 运行 brands DB 测试**

Run: `python scripts/test_brands_db.py`
Expected: `✅ PASS: brands CRUD + current`

- [ ] **Step 5: 运行 Task 2 缓存测试（解除注释 create 分支后）**

Run: `python scripts/test_brand_profile_cache.py`
Expected: `✅ PASS: 品牌档案缓存按 brand_id 取 + current 切换`

- [ ] **Step 6: 提交**

```bash
git add backend/database.py scripts/test_brands_db.py scripts/test_brand_profile_cache.py
git commit -m "feat(db): brands CRUD + current 切换 + 软删校验

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 评分口径修正——按 task.brand_id 取 profile

**Files:**
- Modify: `backend/services/task_service.py`（`recalculate_task_scores` + `create_batch_config`）
- Modify: `backend/routers/evaluations.py`（`recalculate_scores` 用 current）
- Test: `scripts/test_brand_profile_cache.py` 已覆盖缓存；本 task 新增 `scripts/test_task_recalc_brand.py` 验证 task 重算用 task.brand_id 口径。

**Interfaces:**
- Produces: `recalculate_task_scores(task_id)` 用 `db.get_brand_profile_by_id(task.brand_id)`；`create_batch_config` 的 config.brand_profile 来自 task.brand_id；`evaluations.recalculate_scores` 用 `db.get_brand_profile()`（current）。
- Consumes: Task 2 的 `get_brand_profile_by_id`；Task 1 的 tasks.brand_id。

- [ ] **Step 1: 写失败测试**

新建 `scripts/test_task_recalc_brand.py`：

```python
"""评分口径自检：task 重算用 task.brand_id 的 profile，不串 current 品牌。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from services import task_service
from brand_profile import derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 建第二个品牌 acme 并设为 current（制造串口径条件）
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)
    await db.set_current_brand_id("acme")  # current=acme

    # 给 ucloud 品牌建题集 + 任务 + 导入结果（brand_id=ucloud）
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO questions (id, category, question_type, question, difficulty, is_active, brand_id) "
            "VALUES ('Q1','品类词','品类词','便宜的云主机推荐？','medium',1,'ucloud')")
        await conn.commit()
    finally:
        await conn.close()

    # 建任务（brand_id 默认 ucloud）
    task = await task_service.create_task_with_questions("T", ["Q1"])
    task_id = task["id"]
    # 确认 task.brand_id == ucloud
    t = await db.get_task(task_id)
    assert t["brand_id"] == "ucloud", f"task.brand_id 应为 ucloud，实得 {t.get('brand_id')}"

    # 导入 ucloud 题的结果（含 UCloud 提及）
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": "b1", "run_id": "r1"},
        "questions": [],
        "analysis_results": {"deepseek": [{
            "question_id": "Q1", "model_key": "deepseek", "model_name": "DeepSeek",
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 10, "raw_content": "UCloud 海外云主机不错",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": [],
        }]},
    })

    # 此时 current=acme，但 task 属 ucloud。重算应按 ucloud 口径算（提及率=1.0）。
    scores = await db.get_task_scores(task_id)
    assert scores, "应有评分"
    s = next(x for x in scores if x.get("category") is None)
    # ucloud 口径下 Q1 是自然问题（题干不含 UCloud），UCloud 被提及 → coverage_rate=1.0
    assert s["coverage_rate"] == 1.0, f"ucloud 口径下 coverage_rate 应为 1.0，实得 {s['coverage_rate']}"

    print("✅ PASS: task 重算按 task.brand_id 口径（不串 current）")


if __name__ == "__main__":
    asyncio.run(main())
```

> 前置依赖：Task 5/6 需让 `create_task_with_questions`/`import_batch_results` 写入 brand_id。本 task 假定 Task 6 已落地（create_task 带 brand_id）。**执行顺序**：先做 Task 6（查询/写入带 brand_id）再回本 task，或本 task 与 Task 6 合并验证。建议把本 task 排在 Task 6 之后。

- [ ] **Step 2: 改 recalculate_task_scores 按 task.brand_id 取 profile**

在 `backend/services/task_service.py` 的 `recalculate_task_scores`（约 `:238`），把：

```python
    calculator = MetricsCalculator()
    brand_profile = db.get_brand_profile()
```

改为：

```python
    calculator = MetricsCalculator()
    # 多品牌：评分按 task 所属品牌口径算，不依赖全局 current（防切品牌串口径）
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
```

- [ ] **Step 3: 改 create_batch_config 按 task.brand_id 取 profile + config 带 brand_id**

在 `backend/services/task_service.py` 的 `create_batch_config`（约 `:87`），把：

```python
    # 品牌档案随配置透传给本地 runner，保证本地分析口径与服务端一致
    brand_profile = db.get_brand_profile()
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
        "brand_profile": brand_profile.to_dict(),
    }
```

改为：

```python
    # 品牌档案随配置透传给本地 runner，按 task 所属品牌取（多品牌不串口径）
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    config = {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "brand_id": task.get("brand_id") or "ucloud",
        "batch_id": batch_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model_question_ids[mk]} for mk in model_keys],
        "questions": questions,
        "delay": delay,
        "brand_profile": brand_profile.to_dict(),
    }
```

同样在 `get_batch_config`（约 `:151`）的旧批次重建分支与返回 dict 里加 `"brand_id": task.get("brand_id") or "ucloud"`，并改 `brand_profile` 来源为 `db.get_brand_profile_by_id(...)`：

```python
    # 兼容旧批次重建
    return {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "brand_id": task.get("brand_id") or "ucloud",
        "batch_id": batch_id,
        "run_id": b.get("id"),
        "generated_at": b.get("started_at") or datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model.get(mk, [])} for mk in model_keys],
        "questions": questions,
        "delay": cfg.get("delay", 8.0),
        "brand_profile": db.get_brand_profile_by_id(task.get("brand_id") or "ucloud").to_dict(),
    }
```

- [ ] **Step 4: 改 evaluations.recalculate_scores 用 current（无 task 的裸 run）**

`backend/routers/evaluations.py:157` 已是 `brand_profile = db.get_brand_profile()`（取 current）。裸 run 重算属当前品牌，语义正确，**保持不变**。仅加注释说明：

```python
    # 裸 run（非 task）重算：按当前品牌口径（无 task.brand_id 可依）
    brand_profile = db.get_brand_profile()
```

- [ ] **Step 5: 运行口径测试（需 Task 6 先落地 create_task 带 brand_id）**

Run: `python scripts/test_task_recalc_brand.py`
Expected: `✅ PASS: task 重算按 task.brand_id 口径（不串 current）`

- [ ] **Step 6: 运行现有 task_service 自检防回归**

Run: `python scripts/test_tasks_service.py`
Expected: `✅ PASS: task_service 合并去重 + 矩阵 + 重算`（默认 brand_id=ucloud，口径不变）

- [ ] **Step 7: 提交**

```bash
git add backend/services/task_service.py backend/routers/evaluations.py scripts/test_task_recalc_brand.py
git commit -m "fix(metrics): 评分按 task.brand_id 取 profile，切品牌不串口径 + config 带 brand_id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: questions/tasks 查询过滤 + 写入带 brand_id

**Files:**
- Modify: `backend/database.py`（`get_questions`/`list_tasks`/`create_task`/`add_task_batch`/`save_task_analysis_result`/`save_task_geo_scores`/`upsert_question`/`deactivate_all_questions`）
- Test: 扩展 `scripts/test_tasks_service.py` + 新增 `scripts/test_questions_brand.py`

**Interfaces:**
- Produces: 所有列表查询支持 `brand_id` 过滤参数（默认 current；显式传查指定）；所有写入带 brand_id。
- Consumes: Task 1 的 brand_id 列。

- [ ] **Step 1: 写失败测试**

新建 `scripts/test_questions_brand.py`：

```python
"""questions brand_id 隔离自检：题集按品牌过滤 + 软删按品牌。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from brand_profile import derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 建 acme 品牌
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)

    # ucloud 插 2 题，acme 插 1 题
    await db.upsert_question({"id": "u_q1", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    await db.upsert_question({"id": "u_q2", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    await db.upsert_question({"id": "a_q1", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="acme")

    # 按 ucloud 过滤：只见 2 题
    u_qs = await db.get_questions(brand_id="ucloud")
    u_ids = {q["id"] for q in u_qs}
    assert u_ids == {"u_q1", "u_q2"}, f"ucloud 应见 2 题，实得 {u_ids}"

    # 按 acme 过滤：只见 1 题
    a_qs = await db.get_questions(brand_id="acme")
    assert {q["id"] for q in a_qs} == {"a_q1"}, "acme 应见 1 题"

    # deactivate_all_questions 按 brand_id 软删（只软删 ucloud）
    await db.deactivate_all_questions(brand_id="ucloud")
    u_active = await db.get_questions(brand_id="ucloud")
    assert u_active == [], "ucloud 软删后应无 active 题"
    a_active = await db.get_questions(brand_id="acme")
    assert len(a_active) == 1, "acme 题不应被 ucloud 软删影响"

    print("✅ PASS: questions brand_id 隔离")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python scripts/test_questions_brand.py`
Expected: FAIL（`upsert_question` 不接受 brand_id 参数 / `get_questions` 不接受 brand_id）

- [ ] **Step 3: 改 get_questions 加 brand_id 过滤**

`backend/database.py` 的 `get_questions`（约 `:679`）改为：

```python
async def get_questions(category: str = None, question_type: str = None,
                       active_only: bool = True, brand_id: str = None) -> List[Dict]:
    """获取问题列表。brand_id 为 None 时取 current 品牌。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        query = "SELECT * FROM questions WHERE brand_id=?"
        params = [brand_id]
        if active_only:
            query += " AND is_active=1"
        if category:
            query += " AND category=?"
            params.append(category)
        if question_type:
            query += " AND question_type=?"
            params.append(question_type)
        query += " ORDER BY id"
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
```

- [ ] **Step 4: 改 upsert_question 带 brand_id**

`backend/database.py` 的 `upsert_question`（约 `:702`）改为：

```python
async def upsert_question(q: Dict, brand_id: str = None):
    """新增或更新问题。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO questions (id, category, question_type, question, tags, difficulty, is_active, brand_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(id) DO UPDATE SET
               category=excluded.category, question_type=excluded.question_type,
               question=excluded.question, tags=excluded.tags, difficulty=excluded.difficulty,
               brand_id=excluded.brand_id""",
            (q["id"], q["category"], q["question_type"], q["question"],
             json.dumps(q.get("tags", []), ensure_ascii=False), q.get("difficulty", "medium"), brand_id)
        )
        await db.commit()
    finally:
        await db.close()
```

- [ ] **Step 5: 改 deactivate_all_questions 按 brand_id**

`backend/database.py` 的 `deactivate_all_questions`（约 `:730`）改为：

```python
async def deactivate_all_questions(brand_id: str = None):
    """把某品牌的全部问题置为 inactive（生成新题集前清场）。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute("UPDATE questions SET is_active=0 WHERE brand_id=?", (brand_id,))
        await db.commit()
    finally:
        await db.close()
```

- [ ] **Step 6: 改 list_tasks/create_task/add_task_batch/save_* 带 brand_id**

`list_tasks`（约 `:1062`）加 brand_id 过滤：

```python
async def list_tasks(limit: int = 100, offset: int = 0, brand_id: str = None) -> List[Dict]:
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE brand_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (brand_id, limit, offset)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for t in rows:
            t["question_ids"] = json.loads(t["question_ids"]) if isinstance(t["question_ids"], str) else t["question_ids"]
            t["categories"] = json.loads(t["categories"]) if isinstance(t.get("categories"), str) else (t.get("categories") or [])
        return rows
    finally:
        await db.close()
```

`create_task`（约 `:1030`）加 brand_id 参数：

```python
async def create_task(task_id: str, name: str, question_ids: List[str],
                      categories: Optional[List[str]] = None, brand_id: str = None) -> Dict:
    """创建任务（固定总题集，创建时拍板）。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tasks (id, name, question_ids, categories, status, brand_id) "
            "VALUES (?, ?, ?, ?, 'active', ?)",
            (task_id, name, json.dumps(question_ids),
             json.dumps(categories or []), brand_id)
        )
        await db.commit()
        return await get_task(task_id)
    finally:
        await db.close()
```

`add_task_batch`（约 `:1098`）加 brand_id（取 task 的 brand_id）：

```python
async def add_task_batch(run_id: str, task_id: str, batch_id: str, name: str,
                         model_keys: List[str], question_ids: List[str],
                         per_model: Dict[str, List[str]], config: Optional[Dict] = None) -> Dict:
    """在 task 下建一个下载批次。brand_id 取 task.brand_id。"""
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO evaluation_runs
               (id, name, status, model_keys, question_ids, total_questions, config, mode, task_id, batch_id, brand_id)
               VALUES (?, ?, 'config_downloaded', ?, ?, ?, ?, 'webchat', ?, ?, ?)""",
            (run_id, name, json.dumps(model_keys), json.dumps(question_ids),
             sum(len(v) for v in per_model.values()), json.dumps(config or {}), task_id, batch_id, brand_id)
        )
        await db.commit()
        return await get_run(run_id)
    finally:
        await db.close()
```

`save_task_analysis_result`（约 `:1171`）：在 INSERT 列表加 `brand_id`。取 task.brand_id：

```python
async def save_task_analysis_result(task_id: str, batch_id: str, run_id: str, result: Dict):
    """按 (task_id, model_key, question_id) 去重覆盖插入。"""
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
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
                raw_content, competitor_mentions, error_message, citations, all_cited_urls, brand_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, task_id, batch_id, result["question_id"], result["model_key"], result["model_name"],
             int(result["ucloud_mentioned"]), result["ucloud_mention_count"], result.get("ucloud_rank"),
             int(result["has_citation"]), result["citation_count"],
             int(result["ucloud_recommended"]), result["recommendation_strength"],
             result["sentiment_score"], result["sentiment_label"], result["position_weight"],
             result["response_length"], result.get("raw_content", ""),
             json.dumps(result.get("competitor_mentions", {}), ensure_ascii=False),
             result.get("error_message"),
             json.dumps(result.get("citations", []), ensure_ascii=False),
             json.dumps(result.get("all_cited_urls", []), ensure_ascii=False), brand_id)
        )
        await db.commit()
    finally:
        await db.close()
```

`save_task_geo_scores`（约 `:1321`）加 brand_id：

```python
async def save_task_geo_scores(task_id: str, model_key: str, model_name: str,
                               category: Optional[str], scores: Dict):
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO geo_scores
               (task_id, run_id, model_key, model_name, category,
                geo_score, coverage_rate, mention_rate, citation_rate,
                recommendation_rate, sentiment_score, avg_rank,
                total_questions, valid_responses, brand_id)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, model_key, model_name, category,
             scores["geo_score"], scores["coverage_rate"], scores["mention_rate"],
             scores["citation_rate"], scores["recommendation_rate"],
             scores["sentiment_score"], scores["avg_rank"],
             scores["total_questions"], scores["valid_responses"], brand_id)
        )
        await db.commit()
    finally:
        await db.close()
```

- [ ] **Step 7: 改 task_service.create_task_with_questions 透传 brand_id**

`backend/services/task_service.py` 的 `create_task_with_questions`（约 `:66`）：

```python
async def create_task_with_questions(name: str, question_ids: List[str],
                                     categories: Optional[List[str]] = None,
                                     brand_id: str = None) -> Dict:
    """建任务，固定总题集。brand_id 默认 current。"""
    task_id = _new_id("task")
    return await db.create_task(task_id, name, question_ids, categories, brand_id=brand_id)
```

`resolve_question_ids`（约 `:73`）加 brand_id 透传：

```python
async def resolve_question_ids(question_ids: Optional[List[str]],
                               categories: Optional[List[str]],
                               brand_id: str = None) -> List[str]:
    """从品类或显式 id 解析出固定总题集 id 列表。brand_id 默认 current。"""
    questions = await db.get_questions(
        category=categories[0] if categories and len(categories) == 1 else None,
        active_only=True, brand_id=brand_id,
    )
    if categories:
        questions = [q for q in questions if q["category"] in categories]
    if question_ids:
        questions = [q for q in questions if q["id"] in question_ids]
    return [q["id"] for q in questions]
```

- [ ] **Step 8: 运行 questions 隔离测试**

Run: `python scripts/test_questions_brand.py`
Expected: `✅ PASS: questions brand_id 隔离`

- [ ] **Step 9: 运行现有自检防回归**

Run: `python scripts/test_tasks_service.py && python scripts/test_tasks_api.py`
Expected: 两个都 `✅ PASS`（默认 brand_id=ucloud，行为不变）

- [ ] **Step 10: 提交**

```bash
git add backend/database.py backend/services/task_service.py scripts/test_questions_brand.py
git commit -m "feat(db): questions/tasks/runs/results/scores 查询过滤 + 写入带 brand_id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: brands 路由 + questions/tasks 路由带 brand_id

**Files:**
- Create: `backend/routers/brands.py`
- Modify: `backend/app.py`（注册 router + 鉴权）、`backend/models.py`（BrandCreate/Update/Current + TaskCreate/QuestionGenerate 加 brand_id）、`backend/routers/questions.py`、`backend/routers/tasks.py`、`backend/routers/settings.py`（兜底）、`backend/services/question_generator.py`
- Test: `scripts/test_brands_api.py`（新建）

**Interfaces:**
- Produces: `/api/brands` CRUD + `/api/brands/current` GET/PUT；questions/tasks 路由支持 brand_id；task_config 带 brand_id（Task 4 已加）；旧 brand-profile 兜底。
- Consumes: Task 3 的 db CRUD；Task 5 的查询过滤。

- [ ] **Step 1: 写失败测试**

新建 `scripts/test_brands_api.py`：

```python
"""/api/brands 全链路冒烟 + questions/tasks 按品牌过滤。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())

    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/brands", "/api/questions", "/api/tasks"]
    from routers.auth import require_admin
    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 列出含 ucloud
    r = client.get("/api/brands")
    assert r.status_code == 200
    assert any(b["id"] == "ucloud" for b in r.json()["data"])

    # 新建 acme
    r = client.post("/api/brands", json={"brand_id": "acme", "brand_name": "Acme云",
        "company_name": "阿克米", "website": "https://acme-cloud.cn", "industry": "云计算"})
    assert r.status_code == 200, r.text

    # 设为 current
    r = client.put("/api/brands/current", json={"brand_id": "acme"})
    assert r.status_code == 200
    r = client.get("/api/brands/current")
    assert r.json()["data"]["id"] == "acme"

    # 切到 acme 后建题 + 任务，应属 acme
    client.post("/api/questions", json={"id": "a1", "category": "c", "question_type": "品类词",
        "question": "q", "tags": [], "difficulty": "medium"})
    r = client.get("/api/questions")
    ids = {q["id"] for q in r.json()["data"]}
    assert "a1" in ids and all(i == "a1" or False for i in ids) or "a1" in ids, "acme 应见 a1"

    # 切回 ucloud，应不见 a1
    client.put("/api/brands/current", json={"brand_id": "ucloud"})
    r = client.get("/api/questions")
    assert "a1" not in {q["id"] for q in r.json()["data"]}, "ucloud 不应见 acme 的题"

    print("✅ PASS: /api/brands + questions 按品牌隔离")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python scripts/test_brands_api.py`
Expected: FAIL（`/api/brands` 路由不存在 → 404）

- [ ] **Step 3: 加 pydantic 模型**

`backend/models.py` 在品牌档案区追加：

```python
class BrandCreate(BaseModel):
    brand_id: str  # slug
    brand_name: str
    company_name: str = ""
    website: str = ""
    industry: str = ""


class BrandUpdate(BaseModel):
    brand_name: str
    company_name: str = ""
    website: str = ""
    industry: str = ""


class CurrentBrandUpdate(BaseModel):
    brand_id: str
```

并把 `TaskCreate`、`QuestionGenerate` 加可选 brand_id：

```python
class TaskCreate(BaseModel):
    name: str = "GEO评估"
    question_ids: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    brand_id: Optional[str] = None  # None=当前品牌


class QuestionGenerate(BaseModel):
    brand_name: str
    company_name: str = ""
    website: str = ""
    industry: str = ""
    model_key: str = "deepseek"
    scenario_count: Optional[int] = None
    brand_id: Optional[str] = None  # None=当前品牌
```

- [ ] **Step 4: 创建 brands 路由**

新建 `backend/routers/brands.py`：

```python
"""品牌库路由：多品牌 CRUD + 当前品牌切换。"""
import sys
import os
from fastapi import APIRouter, HTTPException, Depends
from routers.auth import require_admin
import models
import database as db

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from brand_profile import derive_from_input, default_brand_profile

router = APIRouter(prefix="/api/brands", tags=["brands"])


def _slugify(s: str) -> str:
    """品牌名 → slug：小写、非字母数字下划线转下划线。"""
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    return s.strip("_") or "brand"


@router.get("")
async def list_brands():
    items = await db.list_brands()
    return {"success": True, "data": items}


@router.post("")
async def create_brand(req: models.BrandCreate, user=Depends(require_admin)):
    brand_id = req.brand_id or _slugify(req.brand_name)
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    try:
        created = await db.create_brand(brand_id, profile)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": created,
            "message": f"已创建品牌「{profile.brand_name}」({brand_id})"}


@router.get("/current")
async def get_current_brand():
    bid = await db.get_current_brand_id()
    b = await db.get_brand(bid)
    if not b:
        # current 指向已删品牌时回退 ucloud
        await db.set_current_brand_id("ucloud")
        b = await db.get_brand("ucloud")
    return {"success": True, "data": b}


@router.put("/current")
async def set_current_brand(req: models.CurrentBrandUpdate, user=Depends(require_admin)):
    b = await db.get_brand(req.brand_id)
    if not b:
        raise HTTPException(404, f"品牌 {req.brand_id} 不存在")
    await db.set_current_brand_id(req.brand_id)
    return {"success": True, "data": b, "message": f"已切换到品牌「{b['brand_name']}」"}


@router.get("/{brand_id}")
async def get_brand(brand_id: str):
    b = await db.get_brand(brand_id)
    if not b:
        raise HTTPException(404, "品牌不存在")
    return {"success": True, "data": b}


@router.put("/{brand_id}")
async def update_brand(brand_id: str, req: models.BrandUpdate, user=Depends(require_admin)):
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    if not await db.get_brand(brand_id):
        raise HTTPException(404, "品牌不存在")
    await db.update_brand(brand_id, profile)
    return {"success": True, "data": {"id": brand_id, **profile.to_dict()},
            "message": f"已更新品牌「{profile.brand_name}」"}


@router.delete("/{brand_id}")
async def delete_brand(brand_id: str, user=Depends(require_admin)):
    try:
        await db.delete_brand(brand_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "message": f"已删除品牌 {brand_id}"}
```

- [ ] **Step 5: app.py 注册 brands router + 鉴权**

`backend/app.py`：import 加 `brands`：

```python
from routers import evaluations, results, questions, settings, auth, webchat, tasks, batches, brands
```

`PROTECTED_PREFIXES` 加 `"/api/brands"`。注册：

```python
app.include_router(brands.router)
```

- [ ] **Step 6: questions 路由带 brand_id**

`backend/routers/questions.py` 的 `list_questions` 加 brand_id query：

```python
@router.get("")
async def list_questions(category: str = None, question_type: str = None,
                         active_only: bool = True, brand_id: str = None):
    """列出问题。brand_id 默认 current。"""
    questions = await db.get_questions(category, question_type, active_only, brand_id=brand_id)
    for q in questions:
        try:
            q["tags"] = json.loads(q["tags"]) if isinstance(q["tags"], str) else q["tags"]
        except Exception:
            q["tags"] = []
    return {"success": True, "data": questions}
```

`create_question` 用 current：

```python
@router.post("")
async def create_question(q: models.QuestionCreate, user=Depends(require_admin)):
    """新增问题（归属当前品牌）"""
    await db.upsert_question(q.dict())
    return {"success": True}
```

- [ ] **Step 7: questions/generate 绑定 brand_id**

`backend/routers/questions.py` 的 `generate_questions` 透传：

```python
    result = await generate_and_replace(
        brand_name=req.brand_name,
        company_name=req.company_name,
        website=req.website,
        industry=req.industry,
        model_key=req.model_key,
        scenario_count=req.scenario_count,
        brand_id=req.brand_id,
    )
```

`backend/services/question_generator.py` 的 `generate_and_replace` 加 brand_id 参数：

```python
async def generate_and_replace(brand_name: str, company_name: str = "", website: str = "",
                               industry: str = "", model_key: str = "deepseek",
                               scenario_count: Optional[int] = None,
                               brand_id: str = None) -> Dict:
    """生成题集 → 替换该品牌激活题集 → 同步该品牌档案。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await db.get_current_brand_id()
    result = await generate_questions(brand_name, company_name, website, industry, model_key, scenario_count)

    # 1. 同步该品牌档案（分析口径与题集品牌一致）
    profile = derive_from_input(brand_name, company_name, website, industry)
    await db.update_brand(brand_id, profile)

    # 2. 清场（仅该品牌）+ 写入新题
    await db.deactivate_all_questions(brand_id=brand_id)
    idx = 0
    for it in result["questions"]:
        idx += 1
        qid = f"{brand_id}_{idx:03d}"  # 带 brand 前缀避免跨品牌 id 冲突
        await db.upsert_question({
            "id": qid, "category": it["category"], "question_type": it["question_type"],
            "question": it["question"], "tags": it["tags"], "difficulty": "medium",
        }, brand_id=brand_id)

    return {
        "generated": len(result["questions"]),
        "scenarios": len(result["scenarios"]),
        "scenario_names": result["scenarios"],
        "raw_counts": result["raw_counts"],
        "model_key": result["model_key"],
        "model_name": result["model_name"],
        "brand_profile": profile.to_dict(),
        "brand_id": brand_id,
    }
```

- [ ] **Step 8: tasks 路由带 brand_id**

`backend/routers/tasks.py` 的 `create_task` 透传 brand_id：

```python
@router.post("")
async def create_task(req: models.TaskCreate, user=Depends(require_admin)):
    """建任务，固定总题集。仅传 name 时默认全部题。brand_id 默认 current。"""
    qids = await task_service.resolve_question_ids(req.question_ids, req.categories, brand_id=req.brand_id)
    if not qids:
        raise HTTPException(400, "没有可评估的问题")
    task = await task_service.create_task_with_questions(req.name, qids, req.categories, brand_id=req.brand_id)
    return {"success": True, "data": task, "message": f"已创建任务，固定题集 {len(qids)} 题"}
```

`list_tasks` 不用改（`build_task_list_summary` 内部 `db.list_tasks()` 已默认 current 过滤——见 Task 5）。

- [ ] **Step 9: settings brand-profile 兜底转发**

`backend/routers/settings.py` 的 `get_brand_profile` 与 `update_brand_profile` 改为转发到当前品牌：

```python
@router.get("/brand-profile")
async def get_brand_profile():
    """兜底：返回当前品牌档案（兼容旧前端）。新前端用 /api/brands/current。"""
    bid = await db.get_current_brand_id()
    b = await db.get_brand(bid)
    if not b:
        return {"success": True, "data": {"configured": False, **default_brand_profile().to_dict()}}
    return {"success": True, "data": {"configured": True, **b["brand_profile"]}}


@router.put("/brand-profile")
async def update_brand_profile(req: models.BrandProfileUpdate, user=Depends(require_admin)):
    """兜底：更新当前品牌档案。新前端用 PUT /api/brands/{id}。"""
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    bid = await db.get_current_brand_id()
    if not await db.get_brand(bid):
        await db.create_brand(bid, profile)  # 兜底新建
    else:
        await db.update_brand(bid, profile)
    return {"success": True, "data": profile.to_dict(),
            "message": f"已更新当前品牌档案：{profile.brand_name}（{profile.industry or '未填行业'}）"}
```

- [ ] **Step 10: 运行 brands API 测试**

Run: `python scripts/test_brands_api.py`
Expected: `✅ PASS: /api/brands + questions 按品牌隔离`

- [ ] **Step 11: 运行全部现有自检防回归**

Run: `python scripts/test_db_migration.py && python scripts/test_tasks_service.py && python scripts/test_tasks_api.py && python scripts/test_questions_brand.py && python scripts/test_brands_db.py`
Expected: 全部 `✅ PASS`

- [ ] **Step 12: 提交**

```bash
git add backend/routers/brands.py backend/app.py backend/models.py backend/routers/questions.py backend/routers/tasks.py backend/routers/settings.py backend/services/question_generator.py scripts/test_brands_api.py
git commit -m "feat(api): /api/brands CRUD + current + questions/tasks 带 brand_id + 旧接口兜底

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 口径修正测试落地（依赖 Task 4+6）

**Files:**
- Test: `scripts/test_task_recalc_brand.py`（Task 4 已写，此时 Task 5/6 落地后可跑通）

- [ ] **Step 1: 运行口径测试**

Run: `python scripts/test_task_recalc_brand.py`
Expected: `✅ PASS: task 重算按 task.brand_id 口径（不串 current）`

- [ ] **Step 2: 运行多品牌隔离端到端测试**

新建 `scripts/test_multi_brand_isolation.py`：

```python
"""多品牌并行隔离端到端：两品牌题集/任务/评分互不污染 + 切品牌不串口径。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from services import task_service
from brand_profile import derive_from_input


def _mk(qid, mk, content):
    return {"question_id": qid, "model_key": mk, "model_name": mk.upper(),
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": len(content), "raw_content": content,
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 建 acme 品牌
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)

    # ucloud 题集 + 任务 + 导入
    await db.upsert_question({"id": "u_q1", "category": "品类词", "question_type": "品类词",
        "question": "便宜的云主机推荐？", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    u_task = await task_service.create_task_with_questions("UT", ["u_q1"], brand_id="ucloud")
    await task_service.import_batch_results(u_task["id"], {
        "meta": {"task_id": u_task["id"], "batch_id": "ub", "run_id": "ur"},
        "questions": [], "analysis_results": {"deepseek": [_mk("u_q1", "deepseek", "UCloud 不错")]}
    })

    # acme 题集 + 任务 + 导入（题干不含 Acme，回答含 Acme云）
    await db.upsert_question({"id": "a_q1", "category": "品类词", "question_type": "品类词",
        "question": "便宜的云主机推荐？", "tags": [], "difficulty": "medium"}, brand_id="acme")
    a_task = await task_service.create_task_with_questions("AT", ["a_q1"], brand_id="acme")
    await task_service.import_batch_results(a_task["id"], {
        "meta": {"task_id": a_task["id"], "batch_id": "ab", "run_id": "ar"},
        "questions": [], "analysis_results": {"deepseek": [
            {**_mk("a_q1", "deepseek", "Acme云 不错"), "ucloud_mentioned": True}
        ]}
    })

    # 切到 acme（current=acme），重算 ucloud 任务：应用 ucloud 口径
    await db.set_current_brand_id("acme")
    await task_service.recalculate_task_scores(u_task["id"])
    u_scores = await db.get_task_scores(u_task["id"])
    us = next(x for x in u_scores if x.get("category") is None)
    assert us["coverage_rate"] == 1.0, f"ucloud 任务应按 ucloud 口径 coverage=1.0，实得 {us['coverage_rate']}"

    # acme 任务：按 acme 口径（题干不含 Acme，回答含 Acme云 → coverage=1.0）
    await task_service.recalculate_task_scores(a_task["id"])
    a_scores = await db.get_task_scores(a_task["id"])
    asr = next(x for x in a_scores if x.get("category") is None)
    assert asr["coverage_rate"] == 1.0, f"acme 任务应按 acme 口径 coverage=1.0，实得 {asr['coverage_rate']}"

    # 隔离：ucloud 任务列表不含 acme 任务
    await db.set_current_brand_id("ucloud")
    u_tasks = await db.list_tasks()
    assert all(t["id"] != a_task["id"] for t in u_tasks), "ucloud 任务列表不应含 acme 任务"
    await db.set_current_brand_id("acme")
    a_tasks = await db.list_tasks()
    assert all(t["id"] != u_task["id"] for t in a_tasks), "acme 任务列表不应含 ucloud 任务"

    print("✅ PASS: 多品牌并行隔离 + 口径不串")


if __name__ == "__main__":
    asyncio.run(main())
```

Run: `python scripts/test_multi_brand_isolation.py`
Expected: `✅ PASS: 多品牌并行隔离 + 口径不串`

- [ ] **Step 3: 提交**

```bash
git add scripts/test_task_recalc_brand.py scripts/test_multi_brand_isolation.py
git commit -m "test: 多品牌隔离 + 口径不串端到端自检

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 前端 useCurrentBrand composable + brands API

**Files:**
- Create: `frontend/src/composables/useCurrentBrand.js`、`frontend/src/api/brands.js`
- Test: 手动 `npm run build` 通过（前端无单测框架，靠 build + 手动验证）

**Interfaces:**
- Produces: `useCurrentBrand()` 返回 `{ currentBrand, brands, setCurrentBrand(id), onBrandChanged(cb), offBrandChanged(cb), refresh() }`。

- [ ] **Step 1: 写 brands API 封装**

新建 `frontend/src/api/brands.js`：

```javascript
import { apiFetch } from '../composables/useWebSocket'

export function listBrands() {
  return apiFetch('/brands')
}

export function createBrand({ brand_id, brand_name, company_name, website, industry }) {
  return apiFetch('/brands', {
    method: 'POST',
    body: JSON.stringify({ brand_id, brand_name, company_name, website, industry }),
  })
}

export function updateBrand(brandId, { brand_name, company_name, website, industry }) {
  return apiFetch(`/brands/${brandId}`, {
    method: 'POST',
    body: JSON.stringify({ brand_name, company_name, website, industry }), // 注意 PUT
  }).catch(() => apiFetch(`/brands/${brandId}`, {
    method: 'PUT',
    body: JSON.stringify({ brand_name, company_name, website, industry }),
  }))
}

export function deleteBrand(brandId) {
  return apiFetch(`/brands/${brandId}`, { method: 'DELETE' })
}

export function getCurrentBrand() {
  return apiFetch('/brands/current')
}

export function setCurrentBrand(brandId) {
  return apiFetch('/brands/current', {
    method: 'PUT',
    body: JSON.stringify({ brand_id: brandId }),
  })
}
```

> 修正：`updateBrand` 直接用 PUT，去掉 catch 兜底。最终：

```javascript
export function updateBrand(brandId, { brand_name, company_name, website, industry }) {
  return apiFetch(`/brands/${brandId}`, {
    method: 'PUT',
    body: JSON.stringify({ brand_name, company_name, website, industry }),
  })
}
```

- [ ] **Step 2: 写 useCurrentBrand composable**

新建 `frontend/src/composables/useCurrentBrand.js`：

```javascript
import { ref } from 'vue'
import { listBrands, getCurrentBrand, setCurrentBrand } from '../api/brands'

// 全局单例（模块级 ref，跨组件共享）
const currentBrand = ref(null)        // { id, brand_name, ... }
const brands = ref([])                // [{id, brand_name, ...}]
const loading = ref(false)

// 品牌切换事件订阅（各页 reload 用）
const listeners = new Set()
function emitBrandChanged() {
  listeners.forEach(cb => { try { cb(currentBrand.value) } catch (e) { console.error(e) } })
}

export function onBrandChanged(cb) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useCurrentBrand() {
  async function refresh() {
    loading.value = true
    try {
      const [list, cur] = await Promise.all([listBrands(), getCurrentBrand()])
      brands.value = list.data || []
      currentBrand.value = cur.data || null
    } catch (e) {
      console.error('load brands error:', e)
    } finally {
      loading.value = false
    }
  }

  async function setCurrent(id) {
    if (!id) return
    try {
      const res = await setCurrentBrand(id)
      currentBrand.value = res.data || currentBrand.value
      emitBrandChanged()  // 通知各页重载
    } catch (e) {
      console.error('set current brand error:', e)
    }
  }

  return { currentBrand, brands, loading, refresh, setCurrent, onBrandChanged }
}
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built` 无报错

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/brands.js frontend/src/composables/useCurrentBrand.js
git commit -m "feat(fe): useCurrentBrand composable + brands API 封装

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: App.vue 顶部品牌选择器

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 加品牌选择器到侧边栏 logo 下方**

`frontend/src/App.vue` template 的 `.logo` div 之后、`el-menu` 之前插入：

```html
      <!-- 全局当前品牌选择器 -->
      <div class="brand-selector">
        <el-select v-model="currentBrandId" placeholder="选择品牌" size="small"
                   :loading="brandLoading" @change="onSwitchBrand" style="width:100%">
          <el-option v-for="b in brands" :key="b.id" :label="b.brand_name + (b.id === 'ucloud' ? ' (默认)' : '')"
                     :value="b.id" />
        </el-select>
      </div>
```

- [ ] **Step 2: script 引入 composable**

`App.vue` `<script setup>` 加：

```javascript
import { useCurrentBrand } from './composables/useCurrentBrand'
const { currentBrand, brands, loading: brandLoading, refresh: refreshBrands, setCurrent } = useCurrentBrand()
const currentBrandId = ref('')
watch(currentBrand, (b) => { currentBrandId.value = b?.id || '' })
async function onSwitchBrand(id) {
  await setCurrent(id)
}
```

`onMounted` 里加 `refreshBrands()`：

```javascript
onMounted(() => {
  if (getToken()) {
    evalStore.recoverRunningEval()
    refreshBrands()
  }
})
```

- [ ] **Step 3: 加样式**

`App.vue` `<style>` 加：

```css
.brand-selector { padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.1); }
.brand-selector :deep(.el-select) { --el-fill-color-blank: rgba(255,255,255,0.08); }
.brand-selector :deep(.el-select__wrapper) { background: rgba(255,255,255,0.08); box-shadow: none; }
.brand-selector :deep(.el-select__placeholder), .brand-selector :deep(.el-select__selected-item) { color: #fff; }
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built`

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.vue
git commit -m "feat(fe): 侧边栏顶部当前品牌选择器

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Home.vue 改品牌列表页

**Files:**
- Modify: `frontend/src/views/Home.vue`（整体重写为品牌列表）

- [ ] **Step 1: 重写 Home.vue 为品牌列表**

`frontend/src/views/Home.vue` 整体替换为：

```vue
<template>
  <div class="home">
    <h2 class="page-title"><el-icon><Aim /></el-icon> 品牌管理</h2>
    <el-card v-loading="loading">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">被测品牌列表（点「设为当前」切换评测空间）</span>
        <el-button v-if="isAdmin()" type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建品牌</el-button>
      </div>
      <el-table :data="brands" stripe>
        <el-table-column prop="brand_name" label="品牌名" min-width="120" />
        <el-table-column prop="company_name" label="公司名" min-width="120" />
        <el-table-column prop="industry" label="行业" width="100" />
        <el-table-column prop="website" label="官网" min-width="180" />
        <el-table-column label="题集数" width="80">
          <template #default="{ row }">{{ row.question_count || 0 }}</template>
        </el-table-column>
        <el-table-column label="任务数" width="80">
          <template #default="{ row }">{{ row.task_count || 0 }}</template>
        </el-table-column>
        <el-table-column label="当前" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.id === currentId" type="success" size="small">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" :disabled="row.id === currentId" @click="onSetCurrent(row)">设为当前</el-button>
            <el-button v-if="isAdmin()" size="small" link type="primary" @click="openEdit(row)">编辑档案</el-button>
            <el-button v-if="isAdmin() && row.id !== 'ucloud'" size="small" link type="danger" @click="onDel(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑品牌对话框 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑品牌档案' : '新建品牌'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="品牌ID" v-if="!editing">
          <el-input v-model="form.brand_id" placeholder="如 acme（小写英文，留空则按品牌名生成）" />
        </el-form-item>
        <el-form-item label="品牌名" required>
          <el-input v-model="form.brand_name" placeholder="如 UCloud、Acme云" />
        </el-form-item>
        <el-form-item label="公司名">
          <el-input v-model="form.company_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="网站" required>
          <el-input v-model="form.website" placeholder="如 https://www.ucloud.cn" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如 云计算" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">{{ editing ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAdmin } from '../composables/useWebSocket'
import { useCurrentBrand } from '../composables/useCurrentBrand'
import { createBrand, updateBrand, deleteBrand } from '../api/brands'

const { brands, currentBrand, loading, refresh, setCurrent } = useCurrentBrand()
const currentId = computed(() => currentBrand.value?.id || '')
const dialog = ref(false)
const editing = ref(null)
const saving = ref(false)
const form = ref({ brand_id: '', brand_name: '', company_name: '', website: '', industry: '' })

async function onSetCurrent(row) {
  await setCurrent(row.id)
  ElMessage.success(`已切换到品牌「${row.brand_name}」`)
}

function openCreate() {
  editing.value = null
  form.value = { brand_id: '', brand_name: '', company_name: '', website: '', industry: '' }
  dialog.value = true
}

function openEdit(row) {
  editing.value = row
  form.value = { brand_id: row.id, brand_name: row.brand_name, company_name: row.company_name, website: row.website, industry: row.industry }
  dialog.value = true
}

async function onSave() {
  if (!form.value.brand_name.trim() || !form.value.website.trim()) {
    ElMessage.warning('品牌名和网站为必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateBrand(editing.value.id, form.value)
      ElMessage.success('品牌档案已更新')
    } else {
      await createBrand(form.value)
      ElMessage.success('品牌已创建')
    }
    dialog.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(e.message || e)
  } finally {
    saving.value = false
  }
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除品牌「${row.brand_name}」？需先清空其题集与任务。`, '删除', { type: 'warning' })
  try {
    await deleteBrand(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch (e) {
    ElMessage.error(e.message || e)
  }
}

onMounted(refresh)
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
</style>
```

- [ ] **Step 2: 改 App.vue 侧边栏菜单文案**

`App.vue` 的首页菜单项 `品牌设置` 改为 `品牌管理`：

```html
        <el-menu-item index="/">
          <el-icon><Aim /></el-icon>
          <span>品牌管理</span>
        </el-menu-item>
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built`

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Home.vue frontend/src/App.vue
git commit -m "feat(fe): Home 改品牌列表页（增删改 + 设为当前）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: Questions/TaskList/Dashboard 按当前品牌过滤 + 订阅切换

**Files:**
- Modify: `frontend/src/views/Questions.vue`、`frontend/src/views/TaskList.vue`、`frontend/src/views/Dashboard.vue`、`frontend/src/api/tasks.js`

- [ ] **Step 1: tasks.js 的 listTasks/createTask 透传 brand_id（可选）**

`frontend/src/api/tasks.js`：

```javascript
export function listTasks(brandId = null) {
  const q = brandId ? `?brand_id=${encodeURIComponent(brandId)}` : ''
  return apiFetch(`/tasks${q}`)
}

export function createTask({ name, categories, question_ids, brand_id }) {
  return apiFetch('/tasks', {
    method: 'POST',
    body: JSON.stringify({ name, categories: categories || null, question_ids: question_ids || null, brand_id: brand_id || null }),
  })
}
```

> 后端 `list_tasks` 默认已按 current 过滤，前端不传 brand_id 即可（current 由后端读）。`listTasks()` 透传参数仅备显式查他品牌用。日常调用不变。

- [ ] **Step 2: Questions.vue 订阅切换重载 + 生成预填当前品牌**

`frontend/src/views/Questions.vue` `<script setup>` 加：

```javascript
import { useCurrentBrand, onBrandChanged } from '../composables/useCurrentBrand'
const { currentBrand } = useCurrentBrand()

// 品牌切换时重载题集
let unsubBrand = null
onMounted(() => {
  loadQuestions()
  unsubBrand = onBrandChanged(() => loadQuestions())
})
onBeforeUnmount(() => { if (unsubBrand) unsubBrand() })
```

（替换原 `onMounted(loadQuestions)`）

`openGenerateDialog` 用当前品牌预填（不再手填）：

```javascript
async function openGenerateDialog() {
  try {
    const d = currentBrand.value || {}
    genForm.value = {
      brand_name: d.brand_name || '',
      company_name: d.company_name || '',
      website: d.website || '',
      industry: d.industry || '',
      brand_id: d.id || null,
      model_key: genForm.value.model_key || 'deepseek',
      scenario_count: 0,
    }
  } catch (e) { /* ignore */ }
  // ...（保留原加载 genModels 逻辑）
```

`import` 加 `onBeforeUnmount`：`import { ref, computed, onMounted, onBeforeUnmount } from 'vue'`

- [ ] **Step 3: TaskList.vue 订阅切换重载**

`frontend/src/views/TaskList.vue` `<script setup>` 改 `onMounted` + 加订阅：

```javascript
import { useCurrentBrand, onBrandChanged } from '../composables/useCurrentBrand'
const { currentBrand } = useCurrentBrand()
let unsubBrand = null

onMounted(async () => {
  await load()
  unsubBrand = onBrandChanged(() => load())
})
onBeforeUnmount(() => { stopPolling(); if (unsubBrand) unsubBrand() })
```

（原 `onBeforeUnmount(() => { stopPolling() })` 合并）

- [ ] **Step 4: Dashboard.vue 订阅切换重载**

`frontend/src/views/Dashboard.vue` `<script setup>` 的 watch 块附近加品牌切换订阅。`onMounted(loadData)` 改为：

```javascript
import { useCurrentBrand, onBrandChanged } from '../composables/useCurrentBrand'
const { currentBrand } = useCurrentBrand()
let unsubBrand = null

onMounted(() => {
  loadData()
  unsubBrand = onBrandChanged(() => {
    // 切品牌：清掉当前选中任务，重新挑默认
    selectedTaskId.value = ''
    scores.value = []; charts.value = {}; latestRun.value = null
    router.replace({ path: '/dashboard' }).catch(() => {})
    loadData()
  })
})
onBeforeUnmount(() => { if (unsubBrand) unsubBrand() })
```

（需 import `onBeforeUnmount`；若已有则不重复）

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built`

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/tasks.js frontend/src/views/Questions.vue frontend/src/views/TaskList.vue frontend/src/views/Dashboard.vue
git commit -m "feat(fe): Questions/TaskList/Dashboard 按当前品牌过滤 + 订阅切换重载

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: Settings 清理 + 本地 runner config brand_id 验证

**Files:**
- Modify: `frontend/src/views/Settings.vue`（移除品牌关键词区——若有）；Verify: `scripts/test_runner_v2_config.py`

- [ ] **Step 1: 确认 Settings 无品牌关键词区需移除**

Read `frontend/src/views/Settings.vue`，确认其只有 ModelVerse/模型Key/权重/用户管理（无品牌关键词编辑区——当前 Settings.vue 确无品牌区，品牌在 Home）。若发现品牌关键词区则移除。当前实现无需改动，本 step 为确认。

- [ ] **Step 2: 扩展 runner v2 config 测试验证 brand_id 字段**

Read `scripts/test_runner_v2_config.py`，在断言 config 的地方加：

```python
    assert cfg.get("brand_id") == "ucloud", f"config 应带 brand_id=ucloud，实得 {cfg.get('brand_id')}"
    assert "brand_profile" in cfg, "config 应带 brand_profile"
```

（具体插入位置：在现有 `assert cfg["version"] == 2` 附近）

Run: `python scripts/test_runner_v2_config.py`
Expected: `✅ PASS`（含 brand_id 断言）

- [ ] **Step 3: 构建前端**

Run: `cd frontend && npm run build`
Expected: `✓ built`

- [ ] **Step 4: 全量自检回归**

Run:
```
python scripts/test_db_migration.py
python scripts/test_tasks_service.py
python scripts/test_tasks_api.py
python scripts/test_questions_brand.py
python scripts/test_brands_db.py
python scripts/test_brand_profile_cache.py
python scripts/test_brands_api.py
python scripts/test_task_recalc_brand.py
python scripts/test_multi_brand_isolation.py
python scripts/test_runner_v2_config.py
```
Expected: 全部 `✅ PASS`

- [ ] **Step 5: 提交**

```bash
git add scripts/test_runner_v2_config.py
git commit -m "test: runner v2 config 验证 brand_id 字段 + 全量回归

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 部署与手动验证（非 task，实施完成后执行）

- 在真实 geo.db 上启动后端：确认迁移幂等（brands 表预置 ucloud、各表 brand_id=ucloud、current_brand_id=ucloud、现有任务/题集/评分全部可见）。
- 前端 build + 部署到 Linux 117.50.195.148（`/opt/general-geo-eval`）：`npm run build` → `systemctl restart geo-eval`。
- 手动验证：
  1. UCloud 无感：首屏 Home=品牌列表且 current=ucloud；Questions/TaskList/Dashboard 与改造前一致。
  2. 多品牌并行：新建 Acme → 切到 Acme → Questions 空 → AI 生成（绑定 Acme）→ 建任务/加批次 → 导入 → 仪表盘只看 Acme。切回 UCloud → UCloud 数据不受影响。
  3. 口径：切到 Acme 时对 UCloud 老任务点重算 → 用 UCloud 口径（不串）。

## Self-Review 记录

- **Spec 覆盖**：brands 表（Task1）✓；缓存层（Task2）✓；CRUD（Task3）✓；口径修正（Task4/7）✓；查询过滤+写入（Task5）✓；brands 路由+questions/tasks（Task6）✓；兜底（Task6 Step9）✓；前端 composable+选择器（Task8/9）✓；Home 品牌列表（Task10）✓；Questions/TaskList/Dashboard 过滤+订阅（Task11）✓；Settings 清理（Task12）✓；runner config brand_id（Task4+12）✓。
- **占位符**：无 TBD/TODO；每步有代码或确切命令。
- **类型一致**：`get_brand_profile_by_id`、`get_current_brand_id`、`set_current_brand_id`、`create_brand`/`update_brand`/`delete_brand`/`list_brands`/`get_brand` 在 DB（Task2/3）与路由（Task6）与前端 API（Task8）签名一致；`useCurrentBrand` 返回 `{currentBrand, brands, loading, refresh, setCurrent, onBrandChanged}` 在 Task8/9/10/11 引用一致。
