# WebChat 云上自动化设计（服务器主动推送 + Win 守护进程）

> 日期：2026-06-24
> 范围：把本地 WebChat 评测改造为「云上 Linux 后端主动推送批次 → 云上 Windows 守护进程接收并自动跑 → 跑完自动回传」的端到端自动化，省去手动下配置/敲命令/传结果三步手工搬运。

## Context（为什么做）

当前 WebChat 评测是纯本地、全手工的 6 步流程：

1. 浏览器登录后端 → 建批次 → 下载 `webchat_task_xxx.json` 到本地
2. 手动把配置文件拷到 Windows 电脑
3. PowerShell `cd` 到项目目录，敲长命令 `python scripts/local_webchat_runner.py --config webchat_task_xxx.json --headed`
4. 浏览器弹出，手动登录/过验证码
5. runner 自动问/答/分析/写盘
6. 跑完生成 `output/webchat_xxx.json` → 手动回服务器上传导入

步骤 2、3、6 是纯手工搬运（下文件、敲命令路径、传结果），最易出错也最烦。本次目标是把这三步自动化，把手工动作压到最小。

用户已选方案 C（服务器主动推送），且要求**新建一台 Windows 云主机**（与 Linux 后端同区域、内网互通），Win11 镜像用户正在 copy，主机留到最后建。

## 关键约束（用户硬性要求）

1. **始终 headed（非 headless）**——随时可能弹验证码，必须留窗口给人处理；即使全模型已登录也开 headed。
2. **每模型问满约 20 题后强制休息 1 小时**——延续 DeepSeek 防封号策略。
3. **WebChat 必须有人登录/过验证码**——云上 Win 机器也需 RDP 上去人工处理；自动化省不掉登录/验证码，只省手工搬运。
4. **主机留到最后建**——先做设计/代码，最后才建机部署。

## 关键决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 触发方式 | C 服务器主动推送 | 用户明确选定；Win 在公网不在 NAT 后 |
| 推送通道 | A1 HTTP webhook | 真正主动推送，fire-and-forget，同区域内网可达 |
| 守护进程形态 | B1 常驻 Python 服务（aiohttp + NSSM 开机自启） | 单进程自洽，webhook/调度/回传一处 |
| 20题/h 实现 | C1 改 scheduler policy（max_consecutive=20 + burst_cooldown=3600） | 复用现有限流退避，不重造计数 |
| 登录态存储 | D1 沿用 web_chat_auth.py 本地文件 | 零改动，现有登录引导直接可用 |
| 无人时行为 | a 探登录态+人在才跑 | 全登录+你标记在场才开跑；不烧配额 |
| 在场确认 | RDP 上 Win 开 localhost:8444 点[开始] | headed+1h 休息的长任务，确认时机比自动开跑稳 |
| 进度回报 | heartbeat 每 30s | partial.json + heartbeat 解耦，不侵入 runner |

## 整体架构

```
┌─ UCloud 乌兰察布 cn-wlcb（同区域，内网互通；各自公网 EIP）─────────────────────┐
│                                                                                │
│  ① Linux 后端 (general-geo-eval)  公网:80        ② Windows 机器（新建）  公网:3389(RDP)+8443(webhook) │
│  ┌──────────────────────────┐                    ┌──────────────────────────────────────┐      │
│  │ FastAPI 后端 + 前端       │  ── webhook 推送 ─→│ win_daemon.py（常驻服务，NSSM 开机自启）│      │
│  │  /api/tasks/.../config    │   POST /webhook     │  ├ HTTP 收 webhook（共享密钥）         │      │
│  │  /import-results          │   {task_id,batch_id}│  ├ 探登录态 + 等你在场确认            │      │
│  │  + 新增: /api/batches/    │                    │  ├ 调 local_webchat_runner.py (headed) │      │
│  │    status/pending         │ ←── 回传结果 JSON ──│  ├ scheduler policy: 20题/h 硬停1h     │      │
│  │  + 批次状态机             │                    │  └ 跑完 POST import-results 自动回传   │      │
│  └──────────────────────────┘                    └──────────────────────────────────────┘      │
│            ↑ 你日常浏览器用                                       ↑ 你 RDP 上去登录/过验证码            │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 组件清单（5 个）

| 组件 | 位置 | 职责 | 复用/新增 |
|------|------|------|----------|
| C1 Linux 后端 | Linux | 现有 FastAPI，加 2 处：建批次后发 webhook；批次状态机 | 复用 + 小改 |
| C2 批次状态机 | Linux 后端 | 批次流转状态值 | 新增（复用 evaluation_runs.status 字段，加状态值） |
| C3 win_daemon | Win | 常驻 Python 服务：收 webhook + 探登录态 + 等在场 + 调 runner + 回传 | 新增单文件 |
| C4 runner + scheduler | Win | 现有 local_webchat_runner.py + core/scheduler.py，policy 加 20/h | 复用 + policy 改 |
| C5 登录态 | Win | 现有 web_chat_auth.py storageState 文件 | 复用零改 |

## 批次状态机

复用 `evaluation_runs.status` 字段，新增状态值：

```
        你建批次
            │
            ▼
   config_downloaded  ──webhook 推送成功──→  pushed
            │                                    │
            └─(推送失败/Win离线)─→ pushed 重试×3 → 仍失败 → 留 config_downloaded（可手动重推）
                                                 │
                                  Win 守护进程收到，探登录态
                                                 │
                              ┌──────────────────┴──────────────────┐
                              ▼                                     ▼
                  全模型已登录 + 你在场                    有未登录 / 等你到场
                              │                                     │
                              ▼                                     ▼
                          running                              awaiting_human
                              │                            (弹通知，等你RDP上去补登/标记在场)
                              │                                     │
                  scheduler 跑题:每模型满20题→burst_cooldown 1h         └─→ 你确认在场 → running
                              │
                    跑完/卡验证码(可选回传部分)
                              │
                              ▼
                         importing  ──POST 结果JSON──→  Linux 后端 import-results
                              │                              │
                              ▼                              ▼
                          imported  ←───成功合并去重+重算──── (现成接口 tasks.py:94)
                              │
                    (失败) → failed
```

状态语义：

| 状态 | 含义 | 谁写入 |
|------|------|--------|
| `config_downloaded` | 批次已建，配置就绪 | 建批次时（现有） |
| `pushed` | webhook 已推到 Win | 后端推送后 |
| `running` | Win 正在跑 | Win 守护进程回报 `POST /api/batches/{id}/status` |
| `awaiting_human` | 需人工（未登录/等在场） | Win 守护进程回报 |
| `importing` | Win 正在回传 | Win 守护进程回报 |
| `imported` | 结果已导入，出分 | 后端 import 接口（现有）成功后 |
| `failed` | 推送失败/运行失败/回传失败 | 各失败点 |

## 一次完整评测的数据流

```
① 你：浏览器 → Linux 后端 POST /api/tasks/{tid}/batches  (建批次, 现有接口)
   └ 后端生成 batch_id/run_id, 状态=config_downloaded, 落库

② 后端: 状态→pushed, POST http://{win内网IP}:8443/webhook/batch
   载荷 {task_id, batch_id, config_url:"/api/tasks/{tid}/batches/{bid}/config"}
   Header: X-Webhook-Secret: <共享密钥>
   (fire-and-forget + 重试3次, Win离线则状态留 config_downloaded, 不阻塞建批次)

③ Win 守护进程收到 webhook:
   ├ 校验 X-Webhook-Secret
   ├ GET {config_url} 拉配置 (现成接口 tasks.py:84 get_batch_config)
   ├ 逐模型探登录态 (复用 _is_logged_in)
   ├ 全登录 → 等你"在场"标记 (见下) → POST /api/batches/{bid}/status running
   └ 有未登录 → POST /api/batches/{bid}/status awaiting_human + 弹桌面通知

④ "在场"标记机制 (因每次都headed, 需你确认开始):
   └ Win 守护进程开一个小本地HTTP页 http://localhost:8444/
      显示「批次X已就绪, 模型: kimi/ernie/... 全已登录, 点[开始]」
      你 RDP 上 Win 后, 浏览器开这个本地页点[开始] → 守护进程开跑
   (全已登录仍要你点一下, 因为 headed + 1h休息 这么长的任务, 你确认时机比自动开跑稳)

⑤ Win 调 local_webchat_runner.py --config <内存配置> --headed (复用, 不改 runner 主逻辑)
   └ scheduler 按 policy: 每模型满20题 → burst_cooldown 3600s

⑥ 每跑完一题: runner 增量写 output/{run_id}.partial.json (现有断点续跑)
   守护进程监控 partial, 定期 POST /api/batches/{bid}/heartbeat {done,total}

⑦ 全部跑完: 守护进程 状态→importing, POST /api/tasks/{tid}/batches/{bid}/import-results
   载荷=runner 的完整结果 JSON (现成接口 tasks.py:94, 自动去重+重算)
   └ 成功 → 后端状态 imported, Dashboard 出分; 守护进程弹通知"✅已导入N条"

⑧ 卡验证码/中途想停: 你在 RDP 上处理验证码继续; 或守护进程检测 throttle/login_expired
   (复用 classify_signal) → 状态 awaiting_human + 通知, 你处理后续跑或 --resume 续跑
```

关键取舍：
- **"在场"用本地确认页，不用后端轮询**——避免你在 Linux 后端额外操作，RDP 上 Win 直接点。点完守护进程接管，1h 休息期间可离开。
- **partial.json + heartbeat 解耦**——runner 断点续跑机制不变，守护进程只读 partial 上报进度，不侵入 runner。
- **回传走现成 import-results**——去重/重算逻辑现成，守护进程只管把文件 POST 上去。
- **推送失败不阻塞建批次**——webhook best-effort，Win 离线时批次留 `config_downloaded`，Dashboard 可手动重推。

## win_daemon 组件设计

### win_daemon.py 单文件结构

```
win_daemon.py
├ HTTP 服务 (aiohttp, 监听 0.0.0.0:8443 收 webhook + localhost:8444 在场确认页)
├ 单任务串行执行器 (同一时刻只跑一个批次, 排队后续)
├ 探登录态 (复用 create_web_chat_client / _is_logged_in)
├ 调 runner (subprocess 调 local_webchat_runner.py --headed, 注入配置)
├ 监 partial + heartbeat 回报
└ 回传 import-results
```

### 配置 .env（Win 机器上，不入库）

```
BACKEND_URL=http://<linux内网IP>          # 同区域内网回传
WEBHOOK_SECRET=<共享密钥>                  # 与后端一致
WIN_LOCAL_PORT=8444                       # 在场确认页
WIN_WEBHOOK_PORT=8443                     # 收后端推送
SERVICE_USER=admin                        # 后端服务账号
SERVICE_PASSWORD=<后端admin密码>           # 换 token 用
```

### 接口契约

**A. 后端新增 2 个接口**（`routers/batches.py` 新文件，注册到 `app.py:117` 后）：

```
POST /api/batches/{batch_id}/status     # Win 守护进程回报状态
  Body: {status: "running|awaiting_human|importing|imported|failed",
         completed?: int, total?: int, message?: str}
  鉴权: 服务账号 token (Bearer) — 复用 require_admin
  作用: db.set_batch_status(batch_id→run_id, status, completed)
  返回: {success: true}

GET /api/batches/pending                # (备用) 守护进程启动时拉未完成批次
  鉴权: Bearer token
  返回: {success, data: [{task_id, batch_id, status, config_url}]}
```

状态回报用 `batch_id` 反查 `run_id`（`evaluation_runs.batch_id` 字段已有），写 `update_run_status`。

**B. 后端建批次后发 webhook**（改 `task_service.create_batch_config` 末尾）：

```python
# 建批次成功后, fire-and-forget 推送 (失败不阻塞)
async def _push_webhook(task_id, batch_id, run_id):
    try:
        await httpx.AsyncClient().post(
            f"{WEBHOOK_WIN_URL}/webhook/batch",  # 配置项, 指向 Win 内网IP:8443
            json={"task_id": task_id, "batch_id": batch_id,
                  "config_url": f"/api/tasks/{task_id}/batches/{batch_id}/config"},
            headers={"X-Webhook-Secret": WEBHOOK_SECRET}, timeout=5)
        await db.set_batch_status(run_id, "pushed")
    except Exception:
        # 失败留 config_downloaded, 不改状态, Dashboard 可手动重推
        logger.warning(...)
```

**C. Win 守护进程提供的端点**：

```
POST /webhook/batch         # 收后端推送 (X-Webhook-Secret 校验)
  → 入队, 立即 200 ACK, 后台串行处理

GET  /  (localhost:8444)    # 在场确认页 (HTML)
  → 显示当前批次: 模型登录态表 + [开始]按钮
     全已登录→按钮可点; 有未登录→显示"请先在浏览器登录X" + 引导

POST /start  (localhost:8444)  # 你点[开始]
  → 触发当前批次开跑 (headed)

GET  /status               # 本地查当前批次进度 (给确认页轮询)
```

### 串行执行器主循环（伪代码）

```python
queue = asyncio.Queue()
current = None

async def handle_webhook(payload):
    await queue.put(payload)          # 入队即 ACK, 不阻塞后端

async def worker():
    while True:
        payload = await queue.get()
        current = payload
        await run_batch(payload)
        current = None

async def run_batch(payload):
    config = GET(payload.config_url)              # 拉配置
    login_status = probe_all_logins(config)       # 探登录态
    await report_status("awaiting_human" or ...)  # 回报后端
    notify_desktop(...)                           # 弹通知
    await wait_for_user_start(login_status)       # 阻塞等你点 /start
    await report_status("running")
    proc = subprocess(local_webchat_runner --headed --config <config内存路径>)
    monitor_partial(proc, heartbeat_cb)           # 监 partial, 每30s heartbeat
    proc.wait()
    result_json = read_output()
    await report_status("importing")
    POST import-results(result_json)              # 回传
    await report_status("imported" or "failed")
    notify_desktop("✅ 批次X 已导入 N 条")
```

### runner 调用方式（不改 runner 主逻辑）

守护进程把拉到的配置写临时文件，subprocess 调用——**完全复用现有 `local_webchat_runner.py --config <file> --headed`**，断点续跑/policy/scheduler 全沿用。守护进程只新增"拉配置→监 partial→回传"这层壳。

守护进程**不重写**评测逻辑，runner 是黑盒，通过 partial.json 观测进度、通过返回码判断成败。runner 的任何改进守护进程自动受益。

### Webhook 鉴权

- 后端→Win：`X-Webhook-Secret` Header，值来自后端 `.env` 的 `WEBHOOK_SECRET`（与 Win `.env` 一致）。
- Win→后端：启动时用 `SERVICE_USER/PASSWORD` 登录 `/api/auth/login` 拿 token 存内存，token 过期(401)则重新登录。所有回报/回传接口带 `Authorization: Bearer <token>`。

## scheduler policy 改动（20 题/h 硬停 1h）

现有 `core/webchat_policy.py` 的 `max_consecutive` + `burst_cooldown` 正是"跑满 N 题→停 M 秒"机制。改动：把全模型设成 `max_consecutive=20 / burst_cooldown=3600`。

```python
# webchat_policy.py 改动
_DEFAULT_POLICY = {
    "max_attempts": 3,
    "inter_unit_delay": 8.0,
    "max_consecutive": 20,       # ← 25 改 20（用户要求：每模型满20题休息）
    "burst_cooldown": 3600,      # ← 180 改 3600（休息1小时）
    "rate_max": 20,              # ← 30 改 20（每小时上限同步收紧）
    "rate_window_sec": 3600,
    "ban_cooldown_sec": 900,
}

# DeepSeek 保留更敏感的触发（满15题就停，比20题更早，更保守），
# 但休息时长统一 1 小时（满足用户"满20题休息1h"要求——DeepSeek 满15题即休息1h，
# 比满20题更早休息，符合"不超过20题"的精神，且单次休息1h不缩水）。
_MODEL_OVERRIDES = {
    "deepseek": {
        "max_attempts": 4,
        "inter_unit_delay": 15.0,
        "max_consecutive": 15,       # 更早触发（<20，更保守）
        "burst_cooldown": 3600,      # ← 180 改 3600（统一休息1h）
        "rate_max": 20,
        "rate_window_sec": 3600,
        "ban_cooldown_sec": 1800,
    },
}
```

## 错误处理矩阵

| 故障点 | 表现 | 处理 | 状态走向 |
|--------|------|------|----------|
| 后端推 webhook，Win 离线 | POST 超时/拒连 | fire-and-forget 不阻塞；重试 3 次（5/15/30s）仍失败留 `config_downloaded`，Dashboard 显示「待重推」 | 留 `config_downloaded` |
| Win 守护进程没在跑 | webhook 无人收 | 同上；daemon 启动时 `GET /api/batches/pending` 自拉未完成批次补跑 | — |
| Win 拉配置失败（后端挂/token过期） | GET config 401/500 | token 过期→重新登录重试 1 次；仍失败→`failed` + 通知 | `failed` |
| 有模型未登录 | 探登录态发现 | `awaiting_human` + 桌面通知 + 确认页引导；RDP 上去 `_login_flow` 登录后[刷新登录态]重探 | `awaiting_human` |
| 你长时间不到场 | `awaiting_human` 挂着 | 不超时、不烧配额；一直等到点[开始] | 保持 `awaiting_human` |
| 跑题中弹验证码 | classify_signal 命中 throttle/captcha | scheduler 现有逻辑：throttle→长冷却后重试；RDP 在场可手动过验证码 | 保持 `running` |
| 跑题中登录失效 | classify_signal 命中 login_expired | scheduler 现有逻辑：该模型剩余单元 `skipped`，不卡死全批；通知 | 保持 `running`，跑完回传部分结果 |
| 跑题中守护进程崩溃/Win 断电 | runner 子进程也死 | partial.json 已落盘；Win 重启后 daemon 拉 pending → 同 run_id `--resume` 续跑 | `running`→续跑 |
| 回传 import-results 失败 | POST 失败 | 重试 3 次（5/15/30s）；仍失败→结果 JSON 留 Win `output/`，`failed` + 通知；Dashboard 手动上传兜底 | `failed`（结果不丢） |
| 后端重算/导入异常 | import 接口 400 | 现成接口已处理；记录错误信息 | `failed` |

核心原则：结果数据永不在传输中丢——partial.json 增量落盘 + 回传失败留本地 + Dashboard 手动上传兜底，三重保险。

## 测试策略

| 层 | 测试 | 怎么做 |
|----|------|--------|
| policy 单测 | 20 题→停 1h 生效 | 构造 20 个 unit 喂 scheduler，断言第 21 个被 `burst_cooldown=3600` 推迟（monkeypatch 把 3600 调小到 1s 验证逻辑，不真等 1h） |
| 状态机单测 | 各状态流转正确 | mock db，覆盖 pushed/awaiting_human/running/importing/imported/failed 转移 |
| webhook 鉴权 | 错密钥被拒 | POST `/webhook/batch` 不带/错带 `X-Webhook-Secret` → 401 |
| Win daemon 端到端（本地 Win 验证） | 全链路跑通 | 后端起在 localhost，daemon 起在 localhost，用一个 `--inline-questions` 的 2 题假批次 + kimi（已登录）走完 推送→拉配置→[开始]→跑2题→回传→imported |
| 断点续跑 | 崩溃恢复 | 跑到第 1 题后 kill daemon，重启→`--resume` 跳过 done 只补第 2 题 |
| 回传失败兜底 | 结果不丢 | mock 后端 import 返回 500，断言结果 JSON 留在 `output/` + 状态 failed |
| 真实云上联调 | 风控实测 | 两台建好后，5 题×5 模型小批次实测机房 IP 是否被风控；不行转广州 |

真实模型登录/验证码/风控无法单测，靠云上小批次联调验证。

## 部署清单（主机留最后建）

**阶段 0 · 本地代码**（现在就能做，不依赖主机）：
1. 后端：新建 `routers/batches.py`（status/pending 接口）+ 改 `task_service.create_batch_config` 加 webhook 推送 + `.env` 加 `WEBHOOK_SECRET`/`WEBHOOK_WIN_URL`
2. policy：`webchat_policy.py` 全模型 `max_consecutive=20 / burst_cooldown=3600`
3. Win 侧：`win_daemon.py` + `win_daemon.service`（NSSM 配置）+ `.env` 模板
4. 前端：Dashboard 批次状态展示 + 「重推」「手动上传」按钮

**阶段 1 · 建两台主机**（最后做）：
- Linux 后端：复用上轮验证过的可靠路径（uhost create + 「Web服务器推荐」防火墙 + BGP EIP + ubuntu 用户）
- Win 机器：等 Win11 镜像 copy 完，`uhost create` 选 Win 镜像（镜像名届时 `ucloud uhost` 查），同区域同防火墙，开 3389+8443
- 两台同 VPC/子网，内网互通

**阶段 2 · Linux 后端部署**（复用上轮脚本）：
- 拉 general-geo-eval 代码、装 Python 依赖、systemd 起 uvicorn、nginx 反代、初始化 admin 密码

**阶段 3 · Win 机器部署**：
- RDP 上去，装 Python + Playwright + 浏览器（`playwright install chromium`）
- 装 NSSM，注册 win_daemon 为开机自启服务
- 配 `.env`（指向 Linux 内网 IP）
- 首次 RDP 登录 5 个模型账号（`_login_flow`），存登录态

**阶段 4 · 联调**：5 题×5 模型小批次实测全链路 + 风控

## 不做（YAGNI）

- 不做 Win→后端的 WebSocket 长连（webhook fire-and-forget 够用）。
- 不做守护进程并行多批次（串行足够，WebChat 本就要人盯着）。
- 不做登录态存后端集中分发（本机登录本机存，零改动）。
- 不做无人值守自动开跑（headed+1h 休息的长任务，确认时机更稳）。
- 不做跨区域（乌兰察布不通才转广州，不预先做多区域支持）。

## 安全约束

- `.env`（含 WEBHOOK_SECRET、SERVICE_PASSWORD）不入库，与现有 .gitignore 一致。
- webhook 端口 8443 仅同区域内网可达（EIP 防火墙只放行 Linux 后端内网 IP），或仅监听内网网卡。
- 在场确认页 8444 仅 localhost，不暴露公网。
- 不在任何说明/计划/命令/摘要中打印真实密钥材料，命令模板用占位符。
