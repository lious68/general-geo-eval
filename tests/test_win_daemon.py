import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import win_daemon


def test_verify_secret_constant_time():
    assert win_daemon.verify_secret("abc", "abc") is True
    assert win_daemon.verify_secret("abc", "xyz") is False
    assert win_daemon.verify_secret("", "abc") is False


@pytest.mark.asyncio
async def test_backend_client_login(monkeypatch):
    bc = win_daemon.BackendClient("http://backend", "admin", "pw")
    with patch("win_daemon.httpx.AsyncClient") as FC:
        client = AsyncMock()
        # httpx Response.json() 是同步方法 → 用 MagicMock
        login_resp = MagicMock()
        login_resp.status_code = 200
        login_resp.json.return_value = {"success": True, "data": {"token": "TOK"}}
        client.post.return_value = login_resp
        FC.return_value.__aenter__ = AsyncMock(return_value=client)
        FC.return_value.__aexit__ = AsyncMock(return_value=False)
        await bc.login()
        assert bc.token == "TOK"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_secret():
    import asyncio
    from aiohttp.test_utils import make_mocked_request
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.secret = "exp"
    daemon.queue = asyncio.Queue()
    req = make_mocked_request("POST", "/webhook/batch",
                              headers={"X-Webhook-Secret": "wrong"})
    req.json = AsyncMock(return_value={"task_id": "t", "batch_id": "b", "config_url": "/x"})
    resp = await win_daemon._webhook_handler(req, daemon)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_webhook_enqueues_and_acks():
    import asyncio
    from aiohttp.test_utils import make_mocked_request
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.secret = "exp"
    daemon.queue = asyncio.Queue()
    req = make_mocked_request("POST", "/webhook/batch",
                              headers={"X-Webhook-Secret": "exp"})
    req.json = AsyncMock(return_value={"task_id": "t", "batch_id": "b", "config_url": "/x"})
    resp = await win_daemon._webhook_handler(req, daemon)
    assert resp.status == 200
    assert not daemon.queue.empty()



@pytest.mark.asyncio
async def test_probe_logins_uses_clients(monkeypatch):
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)

    class FakeClient:
        is_configured = True
        _page = None
        name = "fake"

        async def initialize(self): return True
        async def _goto_site(self, p): pass
        async def _is_logged_in(self, p, timeout=5): return True
        async def close(self): pass

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
    await daemon.wait_for_user_start()
    assert daemon._start_event.is_set() is False  # wait 后被 clear


@pytest.mark.asyncio
async def test_parse_partial_counts_results(tmp_path):
    import json
    p = tmp_path / "r.partial.json"
    p.write_text(json.dumps({
        "meta": {"run_id": "r", "total_results": 5},
        "analysis_results": {"kimi": [{"question_id": "q1"}, {"question_id": "q2"}],
                             "ernie": [{"question_id": "q1"}]},
    }), encoding="utf-8")
    done, total = win_daemon.parse_partial(str(p))
    assert done == 3
    assert total == 5


@pytest.mark.asyncio
async def test_upload_retries_then_succeeds(monkeypatch, tmp_path):
    daemon = win_daemon.WinDaemon.__new__(win_daemon.WinDaemon)
    daemon.output_dir = str(tmp_path)
    daemon.backend = AsyncMock()
    daemon.backend.import_results = AsyncMock(side_effect=[Exception("500"), Exception("500"), {"results_inserted": 5}])
    daemon.backend.report_status = AsyncMock()
    monkeypatch.setattr(win_daemon, "_retry_delays", [0, 0, 0])
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
    daemon._notify = lambda m: None
    monkeypatch.setattr(win_daemon, "_retry_delays", [0])
    ok = await daemon._upload_with_retry("t1", "b1", {"meta": {"run_id": "r1"}}, "r1")
    assert ok is False
    saved = list(tmp_path.glob("b1.r1.json"))
    assert len(saved) == 1
