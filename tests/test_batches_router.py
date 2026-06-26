import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import app as appmod


@pytest.fixture
def client(monkeypatch):
    # 跳过真实 init_db；中间件放行（模拟 admin）
    async def fake_init(): pass
    monkeypatch.setattr("database.init_db", fake_init)
    # 让中间件把请求当 admin 放行（需带 Bearer token 才会走到 verify_session）
    # app.py 是 `from database import verify_session`，故 patch app 模块的绑定
    with patch.object(appmod, "verify_session", new=AsyncMock(return_value={"role": "admin", "username": "svc"})):
        with TestClient(appmod.app, headers={"Authorization": "Bearer testtoken"}) as c:
            yield c


def test_status_update_updates_run(client):
    with patch("database.get_run_by_batch_id", new=AsyncMock(return_value={"id": "run_x", "batch_id": "b1"})), \
         patch("database.update_run_status", new=AsyncMock()) as upd:
        r = client.post("/api/batches/b1/status", json={"status": "running", "completed": 3, "total": 10})
        assert r.status_code == 200, r.text
        upd.assert_awaited_once()
        args = upd.await_args.args
        assert args[0] == "run_x" and args[1] == "running"


def test_status_update_404_when_no_run(client):
    with patch("database.get_run_by_batch_id", new=AsyncMock(return_value=None)):
        r = client.post("/api/batches/ghost/status", json={"status": "running"})
        assert r.status_code == 404


def test_pending_list(client):
    with patch("database.list_pending_batches", new=AsyncMock(return_value=[{"batch_id": "b1", "status": "pushed"}])):
        r = client.get("/api/batches/pending")
        assert r.status_code == 200, r.text
        assert r.json()["data"][0]["batch_id"] == "b1"
