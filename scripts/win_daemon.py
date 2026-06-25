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

# 让守护进程能 import core.* / scripts.local_webchat_runner / backend.*
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "core"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from web_chat_clients import create_web_chat_client  # noqa: E402

# 回传失败重试间隔（秒）
_retry_delays = [5, 15, 30]


def verify_secret(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def parse_partial(path: str) -> tuple:
    """读 runner 的 output/{run_id}.partial.json，返回 (已完成数, 总题数)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return (0, 0)
    results = data.get("analysis_results", {})
    done = sum(len(v) for v in results.values())
    total = data.get("meta", {}).get("total_results", done)
    return (done, total)


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
        if completed is not None:
            body["completed"] = completed
        if total is not None:
            body["total"] = total
        if message is not None:
            body["message"] = message
        r = await self._request("POST", f"/api/batches/{batch_id}/status", json=body)
        r.raise_for_status()

    async def get_pending(self) -> list:
        r = await self._request("GET", "/api/batches/pending")
        r.raise_for_status()
        return r.json()["data"]

    async def import_results(self, task_id: str, batch_id: str, result_dict: dict) -> dict:
        files = {"file": (f"{batch_id}.json",
                          json.dumps(result_dict, ensure_ascii=False), "application/json")}
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
        self._last_login: Optional[dict] = None
        self._all_in: bool = False
        self._last_status: Optional[str] = None
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

    def _notify(self, msg: str):
        """Windows 桌面通知（无依赖，用 msg 命令；非 Win 跳过）。"""
        if sys.platform == "win32":
            try:
                import subprocess
                subprocess.Popen(["msg", "*", "/TIME:120", msg], shell=False)
            except Exception:
                pass
        logger.info(f"[通知] {msg}")

    async def probe_logins(self, model_keys: list) -> dict:
        """逐模型探登录态：返回 {model_key: bool}。"""
        result = {}
        for mk in model_keys:
            logged_in = False
            client = None
            try:
                client = create_web_chat_client(mk)
                if client.is_configured and await client.initialize():
                    await client._goto_site(client._page)
                    logged_in = await client._is_logged_in(client._page)
            except Exception as e:
                logger.warning(f"探 {mk} 登录态异常: {e}")
            finally:
                if client is not None:
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
        self._last_login = login_status
        self._all_in = all_in
        self._last_status = status
        await self.backend.report_status(batch_id, status,
                                         message=json.dumps(login_status, ensure_ascii=False))
        self._notify(f"批次 {batch_id}: " + ("全部已登录，点[开始]开跑" if all_in
                     else f"待登录 {[k for k, v in login_status.items() if not v]}"))

        # 3. 等在场确认
        await self.wait_for_user_start()
        await self.backend.report_status(batch_id, "running")
        self._last_status = "running"

        # 4-6. 调 runner + 回传
        await self._run_and_upload(payload, config, batch_id, task_id)

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
        os.makedirs(self.output_dir, exist_ok=True)
        cfg_path = os.path.join(self.output_dir, f"{batch_id}.config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        partial_path = os.path.join(self.output_dir, f"{run_id}.partial.json")
        out_path = os.path.join(self.output_dir, f"{run_id}.json")

        cmd = [sys.executable, self.runner_path, "--config", cfg_path, "--headed"]
        logger.info(f"启动 runner: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(*cmd)

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

        try:
            with open(out_path, "r", encoding="utf-8") as f:
                result_dict = json.load(f)
        except FileNotFoundError:
            with open(partial_path, "r", encoding="utf-8") as f:
                result_dict = json.load(f)

        await self.backend.report_status(batch_id, "importing")
        self._last_status = "importing"
        ok = await self._upload_with_retry(task_id, batch_id, result_dict, run_id)
        if ok:
            await self.backend.report_status(batch_id, "imported")
            self._last_status = "imported"
            self._notify(f"✅ 批次 {batch_id} 已导入")


# ── 在场确认页 ──
_CONFIRM_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>WebChat 守护进程</title>
<style>body{font-family:sans-serif;max-width:680px;margin:40px auto;padding:0 16px}
button{padding:12px 24px;font-size:16px;background:#6366f1;color:#fff;border:none;border-radius:8px;cursor:pointer}
button:disabled{opacity:.4;cursor:default}.ok{color:#16a34a}.warn{color:#d97706}</style></head>
<body><h1>WebChat 批次在场确认</h1>
<div id="s">加载中…</div>
<div id="m" style="margin:8px 0;font-size:15px"></div>
<p><button id="b" disabled onclick="start()">开始评测</button></p>
<script>
async function refresh(){
  try{ const s=await (await fetch('/status')).json(); render(s); }
  catch(e){ document.getElementById('s').innerHTML='<span class=warn>状态查询失败: '+e+'</span>'; }
}
function render(s){
  const el=document.getElementById('s'); const btn=document.getElementById('b');
  if(!s.current){ el.innerHTML='<span class=warn>当前无批次。可在服务器建批次后自动推送过来。</span>'; btn.disabled=true; return; }
  let h='<b>批次 '+s.current.batch_id+'</b><br>登录态：<br>';
  for(const [k,v] of Object.entries(s.login||{})){ h+=`${k}: ${v?'<span class=ok>已登录</span>':'<span class=warn>未登录（请先在浏览器登录该模型）</span>'}<br>`; }
  h+=`<br>状态：${s.status}`;
  el.innerHTML=h;
  // 有批次就可点；已进入 running 之后禁用防重复点
  btn.disabled = !!(s.status && s.status!=='awaiting_human');
}
async function start(){
  const btn=document.getElementById('b'); const msg=document.getElementById('m');
  btn.disabled=true; btn.textContent='已触发…'; msg.textContent='';
  try{
    const r=await fetch('/start',{method:'POST'});
    if(!r.ok){ msg.innerHTML='<span class=warn>触发失败: HTTP '+r.status+'</span>'; btn.disabled=false; btn.textContent='开始评测'; return; }
    msg.innerHTML='<span class=ok>已触发，runner 即将启动…（看控制台日志）</span>';
    setTimeout(refresh,1500);
  }catch(e){
    msg.innerHTML='<span class=warn>触发异常: '+e+'</span>'; btn.disabled=false; btn.textContent='开始评测';
  }
}
refresh();setInterval(refresh,3000);
</script></body></html>"""


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


def make_app(daemon: WinDaemon) -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/batch", lambda req: _webhook_handler(req, daemon))
    app.router.add_get("/", lambda req: _index_handler(req, daemon))
    app.router.add_post("/start", lambda req: _start_handler(req, daemon))
    app.router.add_get("/status", lambda req: _status_handler(req, daemon))
    return app


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


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "win_daemon.env"))
    backend = BackendClient(
        os.environ["BACKEND_URL"], os.environ["SERVICE_USER"], os.environ["SERVICE_PASSWORD"])
    daemon = WinDaemon(backend, os.environ["WEBHOOK_SECRET"])
    app = make_app(daemon)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", daemon.webhook_port)
    await site.start()
    asyncio.create_task(daemon.worker())
    asyncio.create_task(_bootstrap_pending(daemon))
    logger.info(f"win_daemon 监听 :{daemon.webhook_port}")
    await asyncio.Event().wait()  # 永驻


if __name__ == "__main__":
    asyncio.run(main())
