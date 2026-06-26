import pytest
from unittest.mock import AsyncMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from services import task_service


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

    with patch("services.task_service.httpx.AsyncClient", return_value=FakeClient()), \
         patch("services.task_service.db.set_batch_status", new=AsyncMock()) as sb:
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

    with patch("services.task_service.httpx.AsyncClient", return_value=FakeClient()), \
         patch("services.task_service.db.set_batch_status", new=AsyncMock()) as sb:
        ok = await task_service._push_webhook("t1", "b1", "r1")
        assert ok is False
        sb.assert_not_awaited()  # 失败不改状态，留 config_downloaded
