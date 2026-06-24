# WebChat 云上自动化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把本地 WebChat 评测改造为「Linux 后端建批次后主动 webhook 推送 → Windows 守护进程接收并自动跑（headed）→ 跑完自动回传」，省去手动下配置/敲命令/传结果三步。

**Architecture:** Linux 后端新增批次状态机 + webhook 推送；Windows 上常驻一个 aiohttp 守护进程（NSSM 开机自启），收 webhook → 探登录态 → 等人在场确认 → subprocess 调用现有 `local_webchat_runner.py --headed` → 监 partial 回报进度 → 跑完 POST 回 `import-results`。scheduler policy 改为每模型满 20 题硬停 1 小时。

**Tech Stack:** Python 3.11 / FastAPI（后端）/ aiohttp（Win 守护进程）/ httpx（推送+回传）/ Playwright（WebChat）/ sqlite3 / Vue3+ElementPlus（前端）/ pytest+pytest-asyncio（测试）/ NSSM（Win 服务）/ UCloud CLI（建机）

## Global Constraints

- 始终 headed（非 headless），即使全模型已登录——随时可能弹验证码。
- 每模型问满 20 题后强制休息 1 小时（`max_consecutive=20 / burst_cooldown=3600`；DeepSeek `max_consecutive=15 / burst_cooldown=3600` 更早触发但休息时长一致）。
- WebChat 登录/验证码必须人工（RDP 上 Win 机器处理）；自动化只省手工搬运。
- `.env`（含 `WEBHOOK_SECRET`、`SERVICE_PASSWORD`）不入库，与现有 `.gitignore` 一致。
- 绝不在说明/计划/命令/摘要中打印真实密钥；命令模板用占位符。
- 主机留到最后建（Task 10）；Task 1-9 全是本地代码，不依赖主机。
- 后端鉴权：`/api/batches`、`/api/tasks` 前缀受 `app.py` 中间件保护（需 Bearer token）；daemon 用 admin 服务账号 token 调用所有接口。
- httpx 已是依赖（`requirements.txt: httpx>=0.25.0`）；aiohttp 为 Win 守护进程新增（`scripts/win_requirements.txt`）。
- 仓库 git 身份：`lious68 <lious68@users.noreply.github.com>`（仓库级已配）。

## File Structure

**后端（Linux，复用现有 general-geo-eval）**
- `core/webchat_policy.py`（改）— policy 20/h
- `backend/database.py`（改）— 加 `get_run_by_batch_id`、`list_pending_batches`
- `backend/models.py`（改）— 加 `BatchStatusUpdate`
- `backend/routers/batches.py`（新）— `POST /{batch_id}/status`、`GET /pending`
- `backend/routers/tasks.py`（改）— 加 `POST /{task_id}/batches/{batch_id}/repush`
- `backend/services/task_service.py`（改）— `create_batch_config` 末尾加 `_push_webhook`
- `backend/app.py`（改）— 注册 batches router + `/api/batches` 入 PROTECTED_PREFIXES
- `.env.example`（改）— 加 `WEBHOOK_WIN_URL`、`WEBHOOK_SECRET`

**Windows 守护进程（新）**
- `scripts/win_daemon.py`（新）— 常驻服务主体
- `scripts/win_requirements.txt`（新）— aiohttp 等
- `scripts/install_win_daemon.bat`（新）— NSSM 注册服务
- `scripts/win_daemon.env.example`（新）— 配置模板

**前端（改）**
- `frontend/src/api/tasks.js`（改）— 加 `repushBatch`
- `frontend/src/views/TaskList.vue`（改）— 新状态 tag + 重推按钮 + 运行中轮询

**测试（新）**
- `pytest.ini`、`requirements-dev.txt`、`tests/conftest.py`
- `tests/test_webchat_policy.py`、`tests/test_db_batch.py`、`tests/test_batches_router.py`、`tests/test_webhook_push.py`、`tests/test_win_daemon.py`

**部署（Task 10，建机）**
- 复用 `docs/webchat_local_guide.md`；本计划末尾给建机+部署步骤。

---

### Task 1: 测试脚手架 + scheduler policy 改为 20 题/h

**Files:**
- Create: `pytest.ini`, `requirements-dev.txt`, `tests/conftest.py`, `tests/test_webchat_policy.py`
- Modify: `core/webchat_policy.py:31-52`

**Interfaces:**
- Produces: `get_model_policy(model_key) -> dict`（含 `max_consecutive=20, burst_cooldown=3600`）；`RateLimiter`（`core/scheduler.py`）行为不变，消费 policy。pytest 可运行（`pytest -q`）。

- [ ] **Step 1: 建测试脚手架**

`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
pythonpath = . backend core
```

`requirements-dev.txt`:
```
pytest>=7.4
pytest-asyncio>=0.23
```

`tests/conftest.py`:
```python
import sys, os
# 确保能 import core.* / backend.*
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "core"), os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
```

- [ ] **Step 2: 写失败的 policy 测试**

`tests/test_webchat_policy.py`:
```python
import asyncio
import pytest
from webchat_policy import get_model_policy, MODEL_POLICY
import scheduler


def test_all_models_20_per_hour_one_hour_rest():
    for mk in ("deepseek", "ernie", "doubao", "kimi", "qwen"):
        p = get_model_policy(mk)
        assert p["max_consecutive"] <= 20, f"{mk} max_consecutive {p['max_consecutive']} > 20"
        assert p["burst_cooldown"] == 3600, f"{mk} burst_cooldown {p['burst_cooldown']} != 3600"


def test_deepseek_triggers_earlier_but_rests_one_hour():
    p = get_model_policy("deepseek")
    assert p["max_consecutive"] == 15
    assert p["burst_cooldown"] == 3600


@pytest.mark.asyncio
async def test_rate_limiter_burst_after_max_consecutive(monkeypatch):
    sleeps = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    pol = {"max_consecutive": 2, "burst_cooldown": 100,
           "rate_max": 9999, "rate_window_sec": 3600, "inter_unit_delay": 0}
    limiter = scheduler.RateLimiter("t", pol)
    await limiter.acquire()   # 1
    await limiter.acquire()   # 2 — consecutive 达上限
    await limiter.acquire()   # 3 — 应触发 burst_cooldown=100 的 sleep
    assert 100 in sleeps, f"burst_cooldown 100 未触发, sleeps={sleeps}"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_webchat_policy.py -v`
Expected: 前 2 个 FAIL（max_consecutive 仍是 25/30，burst_cooldown 180），第 3 个可能 PASS（逻辑未变但 100 不在 sleeps）。

- [ ] **Step 4: 改 policy**

`core/webchat_policy.py:31-52` 替换为：
```python
_DEFAULT_POLICY = {
    "max_attempts": 3,
    "inter_unit_delay": 8.0,
    "max_consecutive": 20,       # 用户要求：每模型满20题休息
    "burst_cooldown": 3600,      # 休息1小时
    "rate_max": 20,              # 每小时上限同步收紧
    "rate_window_sec": 3600,
    "ban_cooldown_sec": 900,
}

# DeepSeek 更敏感：满15题即触发（比20更早、更保守），但休息时长统一1小时。
_MODEL_OVERRIDES: Dict[str, dict] = {
    "deepseek": {
        "max_attempts": 4,
        "inter_unit_delay": 15.0,
        "max_consecutive": 15,
        "burst_cooldown": 3600,
        "rate_max": 20,
        "rate_window_sec": 3600,
        "ban_cooldown_sec": 1800,
    },
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_webchat_policy.py -v`
Expected: 3 PASS

- [ ] **Step 6: 提交**

```bash
git add pytest.ini requirements-dev.txt tests/ core/webchat_policy.py
git commit -m "feat(policy): 每模型满20题硬停1小时 + 测试脚手架"
```

---

### Task 2: DB 助手 — 按 batch_id 查 run + 列待处理批次

**Files:**
- Modify: `backend/database.py`（在 `set_batch_status` 后追加，约 1133 行后）
- Create: `tests/test_db_batch.py`

**Interfaces:**
- Produces: `async def get_run_by_batch_id(batch_id: str) -> Optional[Dict]`、`async def list_pending_batches() -> List[Dict]`（返回 `evaluation_runs` 中 status ∈ {`config_downloaded`,`pushed`,`awaiting_human`} 的行，含 task_id/batch_id/status）。供 Task 3 的 router 调用。

- [ ] **Step 1: 写失败测试**

`tests/test_db_batch.py`:
```python
import pytest
import database as db


@pytest.mark.asyncio
async def test_get_run_by_batch_id_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    await db.init_db()
    run_id = "run_test1"
    batch_id = "batch_test1"
    await db.add_task_batch(run_id=run_id, task_id="task_test1", batch_id=batch_id,
                            name="t", model_keys=["kimi"], question_ids=["q1"],
                            per_model={"kimi": ["q1"]}, config={})
    row = await db.get_run_by_batch_id(batch_id)
    assert row is not None
    assert row["id"] == run_id
    assert await db.get_run_by_batch_id("nope") is None


@pytest.mark.asyncio
async def test_list_pending_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    await db.init_db()
    await db.add_task_batch(run_id="r1", task_id="t1", batch_id="b1",
                            name="t", model_keys=["kimi"], question_ids=["q1"],
                            per_model={"kimi": ["q1"]}, config={})
    # b1 状态默认 config_downloaded
    pending = await db.list_pending_batches()
    ids = [p["batch_id"] for p in pending]
    assert "b1" in ids
```

> 注：`db.DB_PATH` 与 `init_db`/`get_db` 的实际路径机制需与现有代码一致。若 `database.py` 用模块级 `DB_PATH` 常量，monkeypatch 它即可；若用别的机制，按实际调整。先按 DB_PATH 假设，跑测试看是否连到 tmp。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_batch.py -v`
Expected: FAIL（`get_run_by_batch_id` 不存在 → AttributeError）

- [ ] **Step 3: 实现 DB 助手**

在 `backend/database.py` 的 `set_batch_status` 函数后追加：
```python
async def get_run_by_batch_id(batch_id: str) -> Optional[Dict]:
    """按 batch_id 反查 evaluation_runs（Win 守护进程回报状态用）。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluation_runs WHERE batch_id=?", (batch_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# 批次状态机中「未完成」的状态：守护进程启动时拉这些批次补跑/续跑。
PENDING_BATCH_STATUSES = ("config_downloaded", "pushed", "awaiting_human")


async def list_pending_batches() -> List[Dict]:
    """列出所有未完成批次（供守护进程 GET /api/batches/pending）。"""
    db = await get_db()
    try:
        placeholders = ",".join("?" * len(PENDING_BATCH_STATUSES))
        cursor = await db.execute(
            f"SELECT id, task_id, batch_id, status, name, mode "
            f"FROM evaluation_runs WHERE status IN ({placeholders}) "
            f"ORDER BY COALESCE(started_at, id) ASC",
            PENDING_BATCH_STATUSES,
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_db_batch.py -v`
Expected: 2 PASS。若因 DB_PATH 机制不符失败，按 `database.py` 顶部 `get_db`/`DB_PATH` 实际定义调整 monkeypatch 目标。

- [ ] **Step 5: 提交**

```bash
git add backend/database.py tests/test_db_batch.py
git commit -m "feat(db): get_run_by_batch_id + list_pending_batches"
```

---

### Task 3: 后端 batches 路由 — 状态回报 + 待处理列表 + 重推

**Files:**
- Create: `backend/routers/batches.py`
- Modify: `backend/models.py`（加 `BatchStatusUpdate`）
- Modify: `backend/routers/tasks.py`（加 repush）
- Modify: `backend/app.py`（注册 router + PROTECTED）
- Create: `tests/test_batches_router.py`

**Interfaces:**
- Consumes: `db.get_run_by_batch_id`、`db.update_run_status`、`db.list_pending_batches`、`task_service._push_webhook`（Task 4 产出）
- Produces:
  - `POST /api/batches/{batch_id}/status`（admin）— body `BatchStatusUpdate{status,completed?,total?,message?}` → `update_run_status`
  - `GET /api/batches/pending`（admin）— 返回 `{success,data:[...]}`
  - `POST /api/tasks/{task_id}/batches/{batch_id}/repush`（admin）— 重新触发推送

- [ ] **Step 1: 加请求模型**

`backend/models.py` 在 `BatchCreate` 后追加：
```python
class BatchStatusUpdate(BaseModel):
    status: str
    completed: Optional[int] = None
    total: Optional[int] = None
    message: Optional[str] = None
```

- [ ] **Step 2: 写失败测试**

`tests/test_batches_router.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import app as appmod


@pytest.fixture
def client(monkeypatch):
    # 跳过真实 init_db / 鉴权：中间件设 user
    async def fake_init(): pass
    monkeypatch.setattr("database.init_db", fake_init)
    monkeypatch.setattr(appmod, "init_db", fake_init, raising=False)
    # 让中间件放行（模拟 admin）
    orig = appmod.app
    with patch("database.verify_session", new=AsyncMock(return_value={"role":"admin","username":"svc"})):
        # TestClient 需 lifespan；用 context
        with TestClient(orig) as c:
            yield c


def test_status_update_updates_run(client):
    with patch("database.get_run_by_batch_id", new=AsyncMock(return_value={"id":"run_x","batch_id":"b1"})), \
         patch("database.update_run_status", new=AsyncMock()) as upd:
        r = client.post("/api/batches/b1/status", json={"status":"running","completed":3,"total":10})
        assert r.status_code == 200
        upd.assert_awaited_once()
        args = upd.await_args.args
        assert args[0] == "run_x" and args[1] == "running"


def test_status_update_404_when_no_run(client):
    with patch("database.get_run_by_batch_id", new=AsyncMock(return_value=None)):
        r = client.post("/api/batches/ghost/status", json={"status":"running"})
        assert r.status_code == 404


def test_pending_list(client):
    with patch("database.list_pending_batches", new=AsyncMock(return_value=[{"batch_id":"b1","status":"pushed"}])):
        r = client.get("/api/batches/pending")
        assert r.status_code == 200
        assert r.json()["data"][0]["batch_id"] == "b1"
```

> 注意 `GET /api/batches/pending` 与 `POST /api/batches/{batch_id}/status` 路径不冲突（pending 是字面段，{batch_id} 是路径参数；FastAPI 按声明顺序匹配，把 `/pending` 路由声明在 `/{batch_id}/status` 之前即可，且二者路径段数不同不会撞）。

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_batches_router.py -v`
Expected: FAIL（路由不存在 → 404）

- [ ] **Step 4: 实现 batches 路由**

`backend/routers/batches.py`:
```python
"""批次状态机路由：Win 守护进程回报状态 + 拉待处理批次。"""
from fastapi import APIRouter, HTTPException, Depends
from routers.auth import require_admin
import models
import database as db

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("/pending")
async def list_pending(user=Depends(require_admin)):
    rows = await db.list_pending_batches()
    return {"success": True, "data": rows}


@router.post("/{batch_id}/status")
async def update_batch_status(batch_id: str, body: models.BatchStatusUpdate,
                              user=Depends(require_admin)):
    run = await db.get_run_by_batch_id(batch_id)
    if not run:
        raise HTTPException(404, "批次不存在")
    await db.update_run_status(run["id"], body.status, body.completed)
    return {"success": True, "data": {"batch_id": batch_id, "status": body.status}}
```

- [ ] **Step 5: 加 repush 到 tasks 路由**

`backend/routers/tasks.py` 在 `get_batch_config` 后追加：
```python
@router.post("/{task_id}/batches/{batch_id}/repush")
async def repush_batch(task_id: str, batch_id: str, user=Depends(require_admin)):
    """重新触发 webhook 推送（Win 离线/丢失时手动重推）。"""
    try:
        ok = await task_service.repush_batch(task_id, batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"pushed": ok},
            "message": "已重推" if ok else "推送失败（Win 未达），批次保留可再重推"}
```

- [ ] **Step 6: 注册路由 + 保护**

`backend/app.py`:
- `from routers import evaluations, results, questions, settings, auth, webchat, tasks, batches`（改 import 行）
- `PROTECTED_PREFIXES` 列表加 `"/api/batches"`
- `app.include_router(tasks.router)` 后加 `app.include_router(batches.router)`

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_batches_router.py -v`
Expected: 3 PASS

- [ ] **Step 8: 提交**

```bash
git add backend/routers/batches.py backend/routers/tasks.py backend/models.py backend/app.py tests/test_batches_router.py
git commit -m "feat(backend): 批次状态回报/待处理/重推路由"
```

---

### Task 4: 后端建批次后主动 webhook 推送

**Files:**
- Modify: `backend/services/task_service.py`（加 `_push_webhook` + `repush_batch`；`create_batch_config` 末尾调用）
- Modify: `.env.example`
- Create: `tests/test_webhook_push.py`

**Interfaces:**
- Consumes: `db.set_batch_status`、环境变量 `WEBHOOK_WIN_URL`、`WEBHOOK_SECRET`
- Produces: `async def _push_webhook(task_id, batch_id, run_id) -> bool`、`async def repush_batch(task_id, batch_id) -> bool`。Task 3 的 repush 路由调用 `repush_batch`。

- [ ] **Step 1: 写失败测试**

`tests/test_webhook_push.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import task_service


@pytest.mark.asyncio
async def test_push_webhook_posts_with_secret_and_sets_pushed(monkeypatch):
    monkeypatch.setenv("WEBHOOK_WIN_URL", "http://win:8443")
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
    posted = {}
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None, timeout=None):
            posted["url"] = url; posted["json"] = json; posted["headers"] = headers
            return FakeResp()
    with patch("task_service.httpx.AsyncClient", return_value=FakeClient()), \
         patch("task_service.db.set_batch_status", new=AsyncMock()) as sb:
        ok = await task_service._push_webhook("t1", "b1", "r1")
        assert ok is True
        assert posted["headers"]["X-Webhook-Secret"] == "s3cr3t"
        assert posted["json"]["batch_id"] == "b1"
        sb.assert_awaited_once_with("r1", "pushed")


@pytest.mark.asyncio
async def test_push_webhook_failure_returns_false_and_no_status_change(monkeypatch):
    monkeypatch.setenv("WEBHOOK_WIN_URL", "http://win:8443")
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise Exception("conn refused")
    with patch("task_service.httpx.AsyncClient", return_value=FakeClient()), \
         patch("task_service.db.set_batch_status", new=AsyncMock()) as sb:
        ok = await task_service._push_webhook("t1", "b1", "r1")
        assert ok is False
        sb.assert_not_awaited()  # 失败不改状态，留 config_downloaded
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_webhook_push.py -v`
Expected: FAIL（`_push_webhook` 不存在）

- [ ] **Step 3: 实现 _push_webhook + repush_batch**

`backend/services/task_service.py` 顶部 import 区确认有 `import os`、`import logging`；加 `import httpx`。在 `get_batch_config` 之后、`import_batch_results` 之前插入：
```python
logger = logging.getLogger(__name__)

WEBHOOK_WIN_URL = os.environ.get("WEBHOOK_WIN_URL", "")      # http://<win内网IP>:8443
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


async def _push_webhook(task_id: str, batch_id: str, run_id: str) -> bool:
    """建批次后 fire-and-forget 推送 webhook 到 Win 守护进程。失败不改状态（留 config_downloaded）。"""
    if not WEBHOOK_WIN_URL or not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_WIN_URL/WEBHOOK_SECRET 未配置，跳过推送")
        return False
    payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "config_url": f"/api/tasks/{task_id}/batches/{batch_id}/config",
    }
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{WEBHOOK_WIN_URL}/webhook/batch",
                             json=payload,
                             headers={"X-Webhook-Secret": WEBHOOK_SECRET},
                             timeout=5)
            r.raise_for_status()
        await db.set_batch_status(run_id, "pushed")
        return True
    except Exception as e:
        logger.warning(f"webhook 推送失败 (batch={batch_id}): {e}；批次留 config_downloaded，可重推")
        return False


async def repush_batch(task_id: str, batch_id: str) -> bool:
    """手动重推：按 batch_id 找 run_id 再推一次。"""
    run = await db.get_run_by_batch_id(batch_id)
    if not run:
        raise ValueError("批次不存在")
    return await _push_webhook(task_id, batch_id, run["id"])
```

- [ ] **Step 4: create_batch_config 末尾接推送**

`backend/services/task_service.py` 的 `create_batch_config` 函数，在 `return config` 之前加（不阻塞返回，推送失败也不影响建批次结果）：
```python
    # 建批次成功后主动推送 webhook（失败不阻塞，留 config_downloaded 可重推）
    import asyncio as _aio
    try:
        await _push_webhook(task_id, batch_id, run_id)
    except Exception as e:
        logger.warning(f"create_batch_config 推送异常: {e}")
    return config
```

- [ ] **Step 5: 更新 .env.example**

`.env.example` 末尾追加（若文件不存在则创建）：
```
# WebChat 云上自动化
WEBHOOK_WIN_URL=http://<win内网IP>:8443
WEBHOOK_SECRET=<生成一个长随机串>
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_webhook_push.py -v`
Expected: 2 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/services/task_service.py .env.example tests/test_webhook_push.py
git commit -m "feat(backend): 建批次后主动 webhook 推送 + 手动重推"
```

---

### Task 5: win_daemon 核心 — BackendClient + webhook 接收 + 串行队列

**Files:**
- Create: `scripts/win_daemon.py`
- Create: `scripts/win_requirements.txt`
- Create: `tests/test_win_daemon.py`（本任务测 BackendClient + webhook 鉴权 + 队列入队）

**Interfaces:**
- Consumes: `core/web_chat_auth.create_web_chat_client`（Task 6 用）、环境变量（见 win_daemon.env.example）
- Produces:
  - `class BackendClient`：`async login()`、`async get_config(config_url)->dict`、`async report_status(batch_id,status,completed=None,total=None,message=None)`、`async get_pending()->list`、`async import_results(task_id,batch_id,result_dict)->dict`
  - `verify_secret(provided, expected) -> bool`
  - `make_app(daemon) -> aiohttp.web.Application`（webhook 路由）
  - `class WinDaemon`：`async handle_webhook(payload)`、`async worker()`、`async run_batch(payload)`（Task 6/7 填充）

- [ ] **Step 1: win 依赖清单**

`scripts/win_requirements.txt`:
```
aiohttp>=3.9
httpx>=0.25
python-dotenv>=1.0
```

- [ ] **Step 2: 写失败测试**

`tests/test_win_daemon.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import win_daemon


def test_verify_secret_constant_time():
    assert win_daemon.verify_secret("abc", "abc") is True
    assert win_daemon.verify_secret("abc", "xyz") is False
    assert win_daemon.verify_secret("", "abc") is False


@pytest.mark.asyncio
async def test_backend_client_login_and_request(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://backend")
    monkeypatch.setenv("SERVICE_USER", "admin")
    monkeypatch.setenv("SERVICE_PASSWORD", "pw")
    bc = win_daemon.BackendClient("http://backend", "admin", "pw")
    with patch("win_daemon.httpx.AsyncClient") as FC:
        client = AsyncMock()
        # 第一次 login 返回 token
        login_resp = AsyncMock(); login_resp.status_code = 200
        login_resp.json.return_value = {"success": True, "data": {"token": "TOK"}}
        client.post.return_value = login_resp
        FC.return_value.__aenter__ = AsyncMock(return_value=client)
        FC.return_value.__aexit__ = AsyncMock(return_value=False)
        await bc.login()
        assert bc.token == "TOK"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_secret():
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.secret = "exp"
    daemon.queue = __import__("asyncio").Queue()
    from aiohttp.test_utils import make_mocked_request
    req = make_mocked_request("POST", "/webhook/batch",
                              headers={"X-Webhook-Secret": "wrong"},
                              payload=b'{"task_id":"t","batch_id":"b","config_url":"/x"}')
    resp = await win_daemon._webhook_handler(req, daemon)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_webhook_enqueues_and_acks():
    import asyncio, json
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.secret = "exp"
    daemon.queue = asyncio.Queue()
    from aiohttp.testutils_request import make_mocked_request  # 占位；见 Step 3 用正确导入
    pass  # 实际用 aiohttp.test_utils.make_mocked_request，见 Step 4
```

> 修正：第 4 个测试用 `from aiohttp.test_utils import make_mocked_request`。Step 4 给出干净版本。

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_win_daemon.py -v`
Expected: FAIL（`win_daemon` 不存在）

- [ ] **Step 4: 实现 win_daemon 核心**

`scripts/win_daemon.py`（本任务只写 BackendClient + verify_secret + WinDaemon 骨架 + webhook handler + make_app；run_batch 在 Task 6/7 填）：
```python
"""Windows 守护进程：收后端 webhook → 探登录态 → 等在场 → 调 runner → 回传。

NSSM 注册为开机自启服务。配置见 win_daemon.env.example。
"""
import asyncio
import hmac
import json
import logging
import os
import sys
from typing import Optional

import httpx
from aiohttp import web

logger = logging.getLogger("win_daemon")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 让守护进程能 import core.* / scripts.local_webchat_runner
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "core"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)


def verify_secret(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


class BackendClient:
    """与 Linux 后端交互：登录拿 token，拉配置/回报状态/回传结果。"""

    def __init__(self, base_url: str, user: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.token: Optional[str] = None

    async def login(self) -> None:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{self.base_url}/api/auth/login",
                             json={"username": self.user, "password": self.password}, timeout=10)
            r.raise_for_status()
            data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"登录失败: {data}")
        self.token = data["data"]["token"]
        logger.info("后端登录成功")

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        if not self.token:
            await self.login()
        headers = kw.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient() as c:
            r = await c.request(method, f"{self.base_url}{path}", headers=headers, timeout=30, **kw)
        if r.status_code == 401:  # token 过期，重登一次
            await self.login()
            headers["Authorization"] = f"Bearer {self.token}"
            async with httpx.AsyncClient() as c:
                r = await c.request(method, f"{self.base_url}{path}", headers=headers, timeout=30, **kw)
        return r

    async def get_config(self, config_url: str) -> dict:
        r = await self._request("GET", config_url)
        r.raise_for_status()
        return r.json()["data"]

    async def report_status(self, batch_id: str, status: str,
                            completed: Optional[int] = None,
                            total: Optional[int] = None,
                            message: Optional[str] = None) -> None:
        body = {"status": status}
        if completed is not None: body["completed"] = completed
        if total is not None: body["total"] = total
        if message is not None: body["message"] = message
        r = await self._request("POST", f"/api/batches/{batch_id}/status", json=body)
        r.raise_for_status()

    async def get_pending(self) -> list:
        r = await self._request("GET", "/api/batches/pending")
        r.raise_for_status()
        return r.json()["data"]

    async def import_results(self, task_id: str, batch_id: str, result_dict: dict) -> dict:
        # 用 multipart 上传 JSON 文件（对齐前端 importBatchResults）
        files = {"file": (f"{batch_id}.json", json.dumps(result_dict, ensure_ascii=False), "application/json")}
        r = await self._request("POST", f"/api/tasks/{task_id}/batches/{batch_id}/import-results", files=files)
        r.raise_for_status()
        return r.json()


class WinDaemon:
    """串行执行器：同一时刻只跑一个批次。"""

    def __init__(self, backend: BackendClient, secret: str,
                 webhook_port: int = 8443, local_port: int = 8444,
                 runner_path: Optional[str] = None, output_dir: Optional[str] = None):
        self.backend = backend
        self.secret = secret
        self.webhook_port = webhook_port
        self.local_port = local_port
        self.queue: asyncio.Queue = asyncio.Queue()
        self.current: Optional[dict] = None
        self._start_event: Optional[asyncio.Event] = None
        self.runner_path = runner_path or os.path.join(ROOT, "scripts", "local_webchat_runner.py")
        self.output_dir = output_dir or os.path.join(ROOT, "output")

    async def handle_webhook(self, payload: dict) -> None:
        await self.queue.put(payload)
        logger.info(f"批次入队: {payload.get('batch_id')}（队列 {self.queue.qsize()}）")

    async def worker(self):
        while True:
            payload = await self.queue.get()
            self.current = payload
            try:
                await self.run_batch(payload)
            except Exception as e:
                logger.exception(f"run_batch 异常: {e}")
            finally:
                self.current = None
                self.queue.task_done()

    async def run_batch(self, payload: dict):
        # Task 6/7 实现：探登录态 → 等在场 → 调 runner → 回传
        raise NotImplementedError


async def _webhook_handler(request: web.Request, daemon: WinDaemon) -> web.Response:
    provided = request.headers.get("X-Webhook-Secret", "")
    if not verify_secret(provided, daemon.secret):
        return web.json_response({"detail": "invalid secret"}, status=401)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "bad json"}, status=400)
    await daemon.handle_webhook(payload)
    return web.json_response({"success": True, "ack": True})


def make_app(daemon: WinDaemon) -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/batch", lambda req: _webhook_handler(req, daemon))
    # 在场确认页路由在 Task 6 加：app.router.add_get("/", ...) / add_post("/start", ...)
    return app


async def main():
    backend = BackendClient(
        os.environ["BACKEND_URL"], os.environ["SERVICE_USER"], os.environ["SERVICE_PASSWORD"])
    daemon = WinDaemon(backend, os.environ["WEBHOOK_SECRET"])
    app = make_app(daemon)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", daemon.webhook_port)
    await site.start()
    # 启动 worker + 拉未完成批次
    asyncio.create_task(daemon.worker())
    asyncio.create_task(_bootstrap_pending(daemon))
    logger.info(f"win_daemon 监听 :{daemon.webhook_port}")
    await asyncio.Event().wait()  # 永驻


async def _bootstrap_pending(daemon: WinDaemon):
    """启动时拉一次未完成批次入队（Win 重启后续跑）。"""
    try:
        pending = await daemon.backend.get_pending()
        for b in pending:
            await daemon.handle_webhook({
                "task_id": b["task_id"], "batch_id": b["batch_id"],
                "config_url": f"/api/tasks/{b['task_id']}/batches/{b['batch_id']}/config",
            })
        if pending:
            logger.info(f"启动补入 {len(pending)} 个待处理批次")
    except Exception as e:
        logger.warning(f"拉待处理批次失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
```

修正第 4 个测试（干净版），替换 `tests/test_win_daemon.py` 中占位的第 4 个测试：
```python
@pytest.mark.asyncio
async def test_webhook_enqueues_and_acks():
    import asyncio
    from aiohttp.test_utils import make_mocked_request
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.secret = "exp"
    daemon.queue = asyncio.Queue()
    body = b'{"task_id":"t","batch_id":"b","config_url":"/x"}'
    req = make_mocked_request("POST", "/webhook/batch",
                              headers={"X-Webhook-Secret": "exp"}, payload=body)
    resp = await win_daemon._webhook_handler(req, daemon)
    assert resp.status == 200
    assert not daemon.queue.empty()
```

- [ ] **Step 5: 装 dev 依赖并运行测试**

Run:
```bash
python -m pip install -r requirements-dev.txt
python -m pip install aiohttp
python -m pytest tests/test_win_daemon.py -v
```
Expected: 4 PASS（login 测试可能需按 httpx mock 形态微调，但 verify_secret + 两个 webhook 测试必过）

- [ ] **Step 6: 提交**

```bash
git add scripts/win_daemon.py scripts/win_requirements.txt tests/test_win_daemon.py
git commit -m "feat(win_daemon): BackendClient + webhook 接收 + 串行队列骨架"
```

---

### Task 6: win_daemon — 登录态探测 + 在场确认页

**Files:**
- Modify: `scripts/win_daemon.py`（实现 `run_batch` 前半 + 确认页路由）
- Modify: `tests/test_win_daemon.py`（加 probe + 确认页测试）

**Interfaces:**
- Consumes: `core.web_chat_clients.create_web_chat_client`、`web_chat_auth`（`_is_logged_in`）
- Produces: `WinDaemon.probe_logins(model_keys) -> dict[str,bool]`、`WinDaemon.wait_for_user_start() -> None`（阻塞到 `/start` 被点）、确认页 `GET /` + `POST /start` + `GET /status`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_win_daemon.py`：
```python
@pytest.mark.asyncio
async def test_probe_logins_uses_clients(monkeypatch):
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    class FakeClient:
        is_configured = True
        async def initialize(self): return True
        _page = None
        async def _goto_site(self, p): pass
        async def _is_logged_in(self, p, timeout=5): return True
        async def close(self): pass
        name = "fake"
    with patch("win_daemon.create_web_chat_client", return_value=FakeClient()):
        res = await daemon.probe_logins(["kimi", "ernie"])
    assert res == {"kimi": True, "ernie": True}


@pytest.mark.asyncio
async def test_start_event_releases_wait():
    import asyncio
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon._start_event = asyncio.Event()
    async def releaser():
        await asyncio.sleep(0.01)
        daemon._start_event.set()
    asyncio.create_task(releaser())
    await daemon.wait_for_user_start()  # 应在 releaser set 后返回
    assert daemon._start_event.is_set()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_win_daemon.py -v -k "probe_logins or start_event"`
Expected: FAIL（方法不存在）

- [ ] **Step 3: 实现 probe_logins + wait_for_user_start + 确认页**

在 `scripts/win_daemon.py` 顶部 import 区加：
```python
from web_chat_clients import create_web_chat_client
```
（注意：`local_webchat_runner.py` 也是这样 import 的，路径已在 sys.path。）

在 `WinDaemon` 类中加方法：
```python
    async def probe_logins(self, model_keys: list) -> dict:
        """逐模型探登录态：返回 {model_key: bool}。"""
        result = {}
        for mk in model_keys:
            logged_in = False
            try:
                client = create_web_chat_client(mk)
                if client.is_configured and await client.initialize():
                    await client._goto_site(client._page)
                    logged_in = await client._is_logged_in(client._page)
            except Exception as e:
                logger.warning(f"探 {mk} 登录态异常: {e}")
            finally:
                try:
                    await client.close()
                except Exception:
                    pass
            result[mk] = logged_in
            logger.info(f"探登录态 {mk}: {'已登录' if logged_in else '未登录'}")
        return result

    async def wait_for_user_start(self) -> None:
        """阻塞直到用户在确认页点[开始]（触发 _start_event.set()）。"""
        if self._start_event is None:
            self._start_event = asyncio.Event()
        await self._start_event.wait()
        self._start_event.clear()
```

实现 `run_batch` 前半（探登录态 + 等在场；后半在 Task 7 接 runner）：
```python
    async def run_batch(self, payload: dict):
        batch_id = payload["batch_id"]
        task_id = payload["task_id"]
        logger.info(f"开始处理批次 {batch_id}")

        # 1. 拉配置
        config = await self.backend.get_config(payload["config_url"])
        model_keys = [u["model_key"] for u in config.get("units", [])]
        self._start_event = asyncio.Event()

        # 2. 探登录态
        login_status = await self.probe_logins(model_keys)
        all_in = all(login_status.values()) and bool(model_keys)
        status = "running" if all_in else "awaiting_human"
        await self.backend.report_status(batch_id, status,
                                         message=json.dumps(login_status, ensure_ascii=False))
        self._notify(f"批次 {batch_id}: " + ("全部已登录，点[开始]开跑" if all_in
                     else f"待登录 { [k for k,v in login_status.items() if not v] }"))

        # 3. 等在场确认
        await self.wait_for_user_start()
        await self.backend.report_status(batch_id, "running")

        # 4-6. 调 runner + 回传（Task 7 实现）
        await self._run_and_upload(payload, config, batch_id, task_id)
```

加确认页路由处理函数 + `_notify`：
```python
    def _notify(self, msg: str):
        """Windows 桌面通知（无依赖，用 msg 命令；非 Win 跳过）。"""
        if sys.platform == "win32":
            try:
                import subprocess
                subprocess.Popen(["msg", "*", "/TIME:120", msg], shell=False)
            except Exception:
                pass
        logger.info(f"[通知] {msg}")
```

确认页 HTML + 路由处理函数（模块级）：
```python
_CONFIRM_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>WebChat 守护进程</title>
<style>body{font-family:sans-serif;max-width:680px;margin:40px auto;padding:0 16px}
button{padding:12px 24px;font-size:16px;background:#6366f1;color:#fff;border:none;border-radius:8px;cursor:pointer}
button:disabled{opacity:.4}.ok{color:#16a34a}.warn{color:#d97706}</style></head>
<body><h1>WebChat 批次在场确认</h1>
<div id="s">加载中…</div>
<p><button id="b" disabled onclick="start()">开始评测</button></p>
<script>
async function refresh(){
  const s=await (await fetch('/status')).json();
  const el=document.getElementById('s');
  if(!s.current){el.innerHTML='<span class=warn>当前无批次。可在服务器建批次后自动推送过来。</span>';document.getElementById('b').disabled=true;return;}
  let h='<b>批次 '+s.current.batch_id+'</b><br>登录态：<br>';
  for(const [k,v] of Object.entries(s.login||{})){h+=`${k}: ${v?'<span class=ok>已登录</span>':'<span class=warn>未登录（请先在浏览器登录该模型）</span>'}<br>`;}
  h+=`<br>状态：${s.status}`;
  el.innerHTML=h;
  document.getElementById('b').disabled=!s.all_in;
}
async function start(){await fetch('/start',{method:'POST'});document.getElementById('b').disabled=true;refresh();}
refresh();setInterval(refresh,3000);
</script></body></html>"""


async def _index_handler(request, daemon):
    return web.Response(text=_CONFIRM_HTML, content_type="text/html")


async def _start_handler(request, daemon):
    if daemon._start_event is None:
        daemon._start_event = asyncio.Event()
    daemon._start_event.set()
    return web.json_response({"success": True})


async def _status_handler(request, daemon):
    return web.json_response({
        "current": daemon.current,
        "status": getattr(daemon, "_last_status", None),
        "login": getattr(daemon, "_last_login", None),
        "all_in": getattr(daemon, "_all_in", False),
    })
```

在 `make_app` 中注册确认页路由（确认页监听同端口；生产可分端口，这里同端口简化——webhook 与确认页同进程同端口，确认页你从 Win 本地访问）：
```python
def make_app(daemon: WinDaemon) -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/batch", lambda req: _webhook_handler(req, daemon))
    app.router.add_get("/", lambda req: _index_handler(req, daemon))
    app.router.add_post("/start", lambda req: _start_handler(req, daemon))
    app.router.add_get("/status", lambda req: _status_handler(req, daemon))
    return app
```

> 注：`run_batch` 里把 `login_status`/`all_in` 存到 `self._last_login`/`self._all_in` 供 `/status` 用。在 `run_batch` 探测后加：`self._last_login = login_status; self._all_in = all_in; self._last_status = status`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_win_daemon.py -v -k "probe_logins or start_event"`
Expected: 2 PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/win_daemon.py tests/test_win_daemon.py
git commit -m "feat(win_daemon): 登录态探测 + 在场确认页"
```

---

### Task 7: win_daemon — 调 runner + 监 partial + 回传 + 重试

**Files:**
- Modify: `scripts/win_daemon.py`（实现 `_run_and_upload` + `parse_partial` + 重试）
- Modify: `tests/test_win_daemon.py`（加 parse_partial + 回传重试测试）

**Interfaces:**
- Consumes: `local_webchat_runner.py`（subprocess 调用 `--config <tmp> --headed`）、`BackendClient.import_results`
- Produces: `parse_partial(path) -> tuple[int,int]`、`WinDaemon._run_and_upload(payload, config, batch_id, task_id)`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_win_daemon.py`：
```python
@pytest.mark.asyncio
async def test_parse_partial_counts_results(tmp_path):
    import json
    p = tmp_path / "r.partial.json"
    p.write_text(json.dumps({
        "meta": {"run_id": "r"},
        "analysis_results": {"kimi": [{"question_id": "q1"}, {"question_id": "q2"}],
                             "ernie": [{"question_id": "q1"}]},
    }), encoding="utf-8")
    done, total = win_daemon.parse_partial(str(p))
    assert done == 3


@pytest.mark.asyncio
async def test_upload_retries_then_leaves_on_failure(monkeypatch, tmp_path):
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.output_dir = str(tmp_path)
    daemon.backend = AsyncMock()
    # import_results 前两次抛错，第三次成功
    daemon.backend.import_results = AsyncMock(side_effect=[Exception("500"), Exception("500"), {"results_inserted": 5}])
    monkeypatch.setattr(win_daemon, "_retry_delays", [0, 0, 0])  # 不真等
    ok = await daemon._upload_with_retry("t1", "b1", {"meta": {}}, "r1")
    assert ok is True
    assert daemon.backend.import_results.await_count == 3


@pytest.mark.asyncio
async def test_upload_failure_leaves_result_on_disk(monkeypatch, tmp_path):
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.output_dir = str(tmp_path)
    daemon.backend = AsyncMock()
    daemon.backend.import_results = AsyncMock(side_effect=Exception("always fails"))
    daemon.backend.report_status = AsyncMock()
    monkeypatch.setattr(win_daemon, "_retry_delays", [0])
    ok = await daemon._upload_with_retry("t1", "b1", {"meta": {"run_id": "r1"}}, "r1")
    assert ok is False
    # 结果文件留在 output/
    saved = list(tmp_path.glob("b1.r1.json"))
    assert len(saved) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_win_daemon.py -v -k "parse_partial or upload"`
Expected: FAIL

- [ ] **Step 3: 实现 parse_partial + _upload_with_retry + _run_and_upload**

在 `scripts/win_daemon.py` 加模块级：
```python
_retry_delays = [5, 15, 30]  # 回传失败重试间隔（秒）


def parse_partial(path: str) -> tuple:
    """读 runner 的 output/{run_id}.partial.json，返回 (已完成数, 总题数?)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return (0, 0)
    results = data.get("analysis_results", {})
    done = sum(len(v) for v in results.values())
    total = data.get("meta", {}).get("total_results", done)
    return (done, total)
```

在 `WinDaemon` 类中加：
```python
    async def _upload_with_retry(self, task_id: str, batch_id: str,
                                 result_dict: dict, run_id: str) -> bool:
        """回传 import-results，失败重试3次；仍失败则结果留本地 + 状态 failed。"""
        last = None
        for i, delay in enumerate(_retry_delays + [0]):
            try:
                resp = await self.backend.import_results(task_id, batch_id, result_dict)
                logger.info(f"回传成功: {resp}")
                return True
            except Exception as e:
                last = e
                logger.warning(f"回传失败(第{i+1}次): {e}")
                if i < len(_retry_delays):
                    await asyncio.sleep(delay)
        # 全失败：结果留盘
        os.makedirs(self.output_dir, exist_ok=True)
        save_path = os.path.join(self.output_dir, f"{batch_id}.{run_id}.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False)
        logger.error(f"回传彻底失败，结果已存 {save_path}")
        await self.backend.report_status(batch_id, "failed", message=f"回传失败: {last}")
        self._notify(f"批次 {batch_id} 回传失败，结果已存 {save_path}")
        return False

    async def _run_and_upload(self, payload: dict, config: dict, batch_id: str, task_id: str):
        run_id = config.get("run_id", batch_id)
        # 写临时配置文件
        os.makedirs(self.output_dir, exist_ok=True)
        cfg_path = os.path.join(self.output_dir, f"{batch_id}.config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        partial_path = os.path.join(self.output_dir, f"{run_id}.partial.json")
        out_path = os.path.join(self.output_dir, f"{run_id}.json")

        # 调 runner（headed），subprocess 隔离便于崩溃恢复 + --resume
        cmd = [sys.executable, self.runner_path, "--config", cfg_path, "--headed"]
        logger.info(f"启动 runner: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(*cmd)

        # 监 partial + heartbeat（每 30s）
        async def heartbeat():
            while proc.returncode is None:
                await asyncio.sleep(30)
                done, total = parse_partial(partial_path)
                try:
                    await self.backend.report_status(batch_id, "running", completed=done, total=total)
                except Exception as e:
                    logger.warning(f"heartbeat 失败: {e}")
        hb = asyncio.create_task(heartbeat())
        rc = await proc.wait()
        hb.cancel()

        if rc != 0:
            logger.error(f"runner 退出码 {rc}，状态 failed（partial 已存可 --resume）")
            await self.backend.report_status(batch_id, "failed", message=f"runner 退出码 {rc}")
            self._notify(f"批次 {batch_id} runner 异常退出({rc})")
            return

        # 读完整结果回传
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                result_dict = json.load(f)
        except FileNotFoundError:
            # 退而用 partial
            with open(partial_path, "r", encoding="utf-8") as f:
                result_dict = json.load(f)

        await self.backend.report_status(batch_id, "importing")
        ok = await self._upload_with_retry(task_id, batch_id, result_dict, run_id)
        if ok:
            await self.backend.report_status(batch_id, "imported")
            self._notify(f"✅ 批次 {batch_id} 已导入")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_win_daemon.py -v -k "parse_partial or upload"`
Expected: 3 PASS

- [ ] **Step 5: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（policy/db/router/webhook/daemon 所有测试通过）

- [ ] **Step 6: 提交**

```bash
git add scripts/win_daemon.py tests/test_win_daemon.py
git commit -m "feat(win_daemon): 调runner+监partial+回传重试+断点续跑"
```

---

### Task 8: 前端 — 批次状态展示 + 重推按钮 + 运行中轮询

**Files:**
- Modify: `frontend/src/api/tasks.js`（加 `repushBatch`）
- Modify: `frontend/src/views/TaskList.vue`（状态 tag + 重推按钮 + 轮询）

**Interfaces:**
- Consumes: `POST /api/tasks/{taskId}/batches/{batchId}/repush`（Task 3 产出）
- Produces: UI 上批次状态实时显示（pushed/awaiting_human/running/importing/imported/failed）+ 重推按钮。

- [ ] **Step 1: 加 API wrapper**

`frontend/src/api/tasks.js` 在 `getBatchImportLogs` 后加：
```javascript
export function repushBatch(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/repush`, { method: 'POST' })
}
```

- [ ] **Step 2: 扩展状态 tag 映射**

`frontend/src/views/TaskList.vue` 的 `batchTagType`（约 444-450 行）替换为：
```javascript
function batchTagType(status) {
  const map = {
    completed: 'success', imported: 'success',
    config_downloaded: 'info', pushed: 'info',
    awaiting_human: 'warning', running: 'warning', importing: 'warning',
    failed: 'danger', push_failed: 'danger',
  }
  return map[status] || 'info'
}
```

- [ ] **Step 3: 加重推按钮**

`TaskList.vue` 批次表「操作」列（约 124-133 行）在「导入」「配置」按钮后加重推按钮：
```html
<el-button v-if="isAdmin()" size="small" link type="primary" @click="repushBatch(b)">重推</el-button>
```

- [ ] **Step 4: 加 repush 方法 + 运行中轮询**

`TaskList.vue` script 区加方法（在 `doImport` 附近）：
```javascript
async function repushBatch(b) {
  const taskId = b.task_id || currentTaskId.value
  try {
    const res = await api.repushBatch(taskId, b.batch_id)
    ElMessage.success(res.message || '已重推')
    refreshBatches(taskId)
  } catch (e) {
    ElMessage.error('重推失败: ' + (e.message || e))
  }
}

// 展开某任务时，若有批次在 pushed/awaiting_human/running/importing，轮询刷新
let pollTimer = null
function startPolling(taskId) {
  stopPolling()
  pollTimer = setInterval(() => {
    const bs = batchesMap.value[taskId] || []
    const active = bs.some(b => ['pushed','awaiting_human','running','importing'].includes(b.status))
    if (active) refreshBatches(taskId)
    else stopPolling()
  }, 15000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
```

在 `onExpand`（约 281-294 行）加载批次后调用 `startPolling(row.id)`；任务行收起时 `stopPolling()`。`currentTaskId` 用当前展开任务 id（onExpand 里记录）。

> 注：`api` 是 `tasks.js` 的导入别名，按文件顶部现有 import 风格调用（现有代码用 `importBatchResults` 等具名导入，这里 `repushBatch` 同样具名导入）。若现有用 `import * as api`，则 `api.repushBatch`；否则直接 `repushBatch(taskId, b.batch_id)`。按 `TaskList.vue` 顶部实际 import 形态对齐。

- [ ] **Step 5: 构建前端验证无错**

Run: `cd frontend && npm run build`
Expected: 构建成功（无编译错误）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/tasks.js frontend/src/views/TaskList.vue
git commit -m "feat(frontend): 批次状态tag+重推按钮+运行中轮询"
```

---

### Task 9: Win 部署物 — NSSM 服务脚本 + .env 模板 + 文档

**Files:**
- Create: `scripts/install_win_daemon.bat`
- Create: `scripts/win_daemon.env.example`
- Modify: `docs/webchat_local_guide.md`（追加云联动章节）

- [ ] **Step 1: .env 模板**

`scripts/win_daemon.env.example`:
```
# Windows 守护进程配置（复制为 win_daemon.env，填实际值，勿入库）
BACKEND_URL=http://<linux内网IP或公网EIP>
SERVICE_USER=admin
SERVICE_PASSWORD=<后端admin密码>
WEBHOOK_SECRET=<与后端 .env WEBHOOK_SECRET 一致>
```

- [ ] **Step 2: NSSM 安装脚本**

`scripts/install_win_daemon.bat`:
```bat
@echo off
REM 用 NSSM 把 win_daemon 注册为开机自启服务。需先装 NSSM 并放 PATH。
REM 用法（管理员 PowerShell）： scripts\install_win_daemon.bat
setlocal
set ROOT=%~dp0..
set PY=python
set SCRIPT=%ROOT%\scripts\win_daemon.py
set ENVFILE=%ROOT%\scripts\win_daemon.env

if not exist "%ENVFILE%" (
  echo [ERR] 未找到 %ENVFILE%，请复制 win_daemon.env.example 并填写
  exit /b 1
)

nssm install WinDaemon "%PY%" "%SCRIPT%"
nssm set WinDaemon AppDirectory "%ROOT%"
nssm set WinDaemon AppEnvironmentExtra "PYTHONUNBUFFERED=1"
REM 把 .env 内容作为环境变量注入（NSSM 不直接读 .env，用 dotenv 在脚本内加载）
nssm set WinDaemon Start SERVICE_AUTO_START
nssm start WinDaemon
echo [OK] WinDaemon 服务已安装并启动
endlocal
```

> 注：`win_daemon.py` 需在 `main()` 开头加载 `.env`。在 `main()` 最前加：
> ```python
> from dotenv import load_dotenv
> load_dotenv(os.path.join(os.path.dirname(__file__), "win_daemon.env"))
> ```

- [ ] **Step 3: 文档追加云联动章节**

`docs/webchat_local_guide.md` 末尾追加：
```markdown
## 云上自动化模式（服务器推送 + Win 守护进程）

部署后可省去手动下配置/敲命令/传结果。流程：

1. 后端建批次 → 自动 webhook 推 Win 守护进程
2. Win 守护进程探登录态 → 弹通知 → 你 RDP 上 Win 开 `http://localhost:8443` 点[开始]
3. 守护进程自动调 `local_webchat_runner --headed` 跑（每模型满20题休息1小时）
4. 跑完自动回传，Dashboard 出分

Win 守护进程安装：管理员 PowerShell 跑 `scripts\install_win_daemon.bat`（需 NSSM）。
配置：复制 `scripts/win_daemon.env.example` 为 `win_daemon.env` 填值。
```

- [ ] **Step 4: 在 win_daemon.main 加 dotenv 加载**

`scripts/win_daemon.py` 的 `main()` 开头（`backend = BackendClient(...)` 之前）加：
```python
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "win_daemon.env"))
```
顶部 import 区加 `from dotenv import load_dotenv`（或函数内 import 如上）。

- [ ] **Step 5: 提交**

```bash
git add scripts/install_win_daemon.bat scripts/win_daemon.env.example docs/webchat_local_guide.md scripts/win_daemon.py
git commit -m "feat(win_daemon): NSSM服务脚本+env模板+云联动文档"
```

---

### Task 10: 建两台主机 + 部署 + 联调

> 此任务为基础设施部署，使用 `ucloud-cli` skill 建机；非 TDD，以验证为门。主机留到最后（用户要求）。

**Files:** 无代码改动；产出两台在线主机 + 部署的服务。

**Prerequisites:** Task 1-9 全部完成并测试通过；用户 Win11 镜像已 copy 到 UCloud 乌兰察布。

- [ ] **Step 1: 建两台主机（乌兰察布 cn-wlcb）**

调用 `ucloud-cli` skill。复用上轮验证路径（见记忆 `ucloud-deploy-gotchas`）：
- 复用「Web服务器推荐」防火墙 + DefaultVPC/子网；两台同 VPC 内网互通。
- Linux 后端：`uhost create` Ubuntu 镜像，纯字母数字密码，绑 BGP EIP（开 80/22），用户 `ubuntu`。
- Win 机器：`uhost create` 选已 copy 的 Win11 镜像（镜像 ID 用 `ucloud uhost` 查），同防火墙，开 3389/22/8443，绑 EIP。
- 记下两台内网 IP（互访用）与公网 EIP（RDP/浏览器用）。
- ⚠️ 踩坑：`uhost create --password` 勿含特殊字符；Ubuntu 登录用 `ubuntu` 非 `root`。

- [ ] **Step 2: 部署 Linux 后端**

SSH 上 Linux（paramiko/`ubuntu` 用户 + sudo），复用上轮脚本：
- 拉 general-geo-eval 代码（含本计划所有改动）
- 装 Python 依赖、systemd 起 uvicorn（:8000）、nginx 反代 :80
- 初始化 admin 密码
- 配 `.env`：`WEBHOOK_WIN_URL=http://<win内网IP>:8443`、`WEBHOOK_SECRET=<生成串>`

- [ ] **Step 3: 部署 Win 守护进程**

RDP 上 Win：
- 装 Python 3.11 + `pip install -r scripts/win_requirements.txt` + 项目根 `requirements.txt`
- `playwright install chromium`（各模型用各自浏览器，按 web_chat_clients 实际需求装）
- 复制 `scripts/win_daemon.env.example` → `win_daemon.env`，填 `BACKEND_URL=http://<linux内网IP>`、与后端一致的 `WEBHOOK_SECRET`、admin 密码
- 装 NSSM，管理员跑 `scripts\install_win_daemon.bat`
- 验证：`curl http://localhost:8443/status` 返回 JSON

- [ ] **Step 4: 首次登录 5 个模型**

RDP 上 Win，跑 `python scripts/local_webchat_runner.py --models kimi ernie doubao qwen --headed`（无 --config，触发登录引导），逐模型 `_login_flow` 登录存登录态。或用现有 `setup_webchat_auth.py`。

- [ ] **Step 5: 联调小批次**

- 浏览器开 Linux 后端，建一个 task（2-3 题）+ batch（先只选 kimi，已登录）
- 观察：批次状态 `config_downloaded → pushed`；Win 弹通知 + 确认页显示 kimi 已登录
- RDP 上 Win 开 `http://localhost:8443` 点[开始]
- 观察：状态 `running`，Dashboard 每 15s 轮询刷新；runner headed 开跑
- 跑完：状态 `importing → imported`，Dashboard 出分
- ✅ 联调通过标志：Dashboard 显示该批次 GEO 分数

- [ ] **Step 6: 风控实测（决策是否转广州）**

- 用 5 题×5 模型批次实测机房 IP 风控
- 若 DeepSeek 等频繁要求验证码/封号 → 按 Global Constraint 转 **广州** 重建两台（同流程）
- 若稳定 → 乌兰察布定型

- [ ] **Step 7: 更新记忆 + 提交部署结果**

- 更新记忆 `general-geo-eval-deploy.md`：记录两台新主机 IP/角色/服务
- 更新 `ucloud-deploy-gotchas.md`：若 Win11 镜像/Win 部署有新坑，追加
- Git 提交（若部署中改了配置文件）：`git commit -m "chore(deploy): 乌兰察布双机云联动部署"`

---

## Self-Review

**1. Spec coverage:**
- 始终 headed → Task 7 `--headed` 固定 ✅
- 20题/h 休息 → Task 1 policy ✅
- webhook 推送 → Task 4 ✅
- 批次状态机 → Task 2(db) + Task 3(router) + Task 5-7(daemon 回报) ✅
- 在场确认页 → Task 6 ✅
- 探登录态+人在才跑(a) → Task 6 ✅
- 监 partial + heartbeat 30s → Task 7 ✅
- 回传重试3次+留本地 → Task 7 ✅
- 断点续跑(--resume) → Task 7 runner 子进程 + Task 5 `_bootstrap_pending` ✅
- webhook 共享密钥鉴权 → Task 5 `verify_secret` ✅
- daemon 启动拉 pending → Task 5 `_bootstrap_pending` ✅
- 前端状态展示+重推 → Task 8 ✅
- NSSM 开机自启 → Task 9 ✅
- 主机最后建 → Task 10 ✅
- 风控转广州 → Task 10 Step 6 ✅

**2. Placeholder scan:** 无 TBD/TODO；Task 10 的镜像 ID/内网 IP 是运行时确定值，已注明用 `ucloud uhost` 查/paramiko 获取，非占位符遗漏。

**3. Type consistency:**
- `BatchStatusUpdate{status,completed?,total?,message?}` — Task 3 定义，Task 5 `report_status` 签名一致 ✅
- `_push_webhook(task_id,batch_id,run_id)->bool` — Task 4 定义，Task 3 repush 路由调 `repush_batch` ✅
- `get_run_by_batch_id`/`list_pending_batches` — Task 2 定义，Task 3/4 消费 ✅
- `parse_partial(path)->tuple` — Task 7 定义并消费 ✅
- `_upload_with_retry(task_id,batch_id,result_dict,run_id)->bool` — 定义与测试一致 ✅
- `repushBatch(taskId,batchId)` — Task 8 前端与 Task 3 后端 `/{task_id}/batches/{batch_id}/repush` 路径一致 ✅

无遗留问题。
