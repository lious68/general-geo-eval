# Win 守护进程交接文档（2026-06-26）

> 给 Win 主机上的 Claude Code 用：读这份 + 配套的 [部署 runbook](./DEPLOY_AGENT_RUNBOOK.md) 就能接上当前进度。
> 本机（开发机 `C:\Users\las\general-geo-eval`）的会话上下文无法跨机器同步，这份文档是等价替代。
> 主分支 `master`（GitHub 上为权威源；Linux/Win 均已切到 master）。

> 🔐 **密钥不在本文档**：主机密码、admin 密码、WEBHOOK_SECRET 等真实值**绝不写入 repo**。
> 它们只存在开发机 Claude 的 memory 文件里（`general-geo-eval-deploy`、`ucloud-deploy-gotchas`）和已登录的 UCloud CLI profile。
> 下文表格一律用 `<占位符>`。agent 读到占位符后，从本机 memory 取真实值代入 SSH/SCP 命令，不在任何输出里回显。

---

## 1. 这套系统是什么

WebChat 云上自动化：Linux 后端建批次 → webhook 推 Win 守护进程 → 守护进程在 RDP 里跑 Playwright headed 评测（浏览器可见，能过验证码）→ 自动回传结果。消除手动下载配置/敲命令/上传结果三步。

**核心约束（不可违反）：**
- 所有评测必须 **headed**（非 headless），验证码才看得见能过
- 每个模型跑 20 题/小时后**休息 1 小时**（`webchat_policy` 限流，防封号）
- **decision-a「人在才跑」**：守护进程只在 Administrator 登录 RDP 时才跑（任务计划 AtLogOn 触发）；人不在时批次留 `config_downloaded`，下次登录 `_bootstrap_pending` 自动拉回
- `.env` / `win_daemon.env` 含密钥，**绝不 push GitHub**
- 模型**不要求预先登录**：未登录的模型首次跑批次时会弹浏览器引导登录并自动保存 storageState（runner 的 `_login_flow` 实现）

---

## 2. 两台主机信息

| | Linux 后端 | Win 守护进程 |
|---|---|---|
| UCloud 主机名 | geo-eval-backend | geo-eval-win |
| 主机 ID | `uhost-1s1ut1xntwwy` | `uhost-1s1utg6ezfxk` |
| 公网 EIP | `117.50.195.148` | `117.50.189.16` |
| 内网 IP | `10.60.84.46` | `10.60.164.214` |
| 系统 | Ubuntu 22.04 | Windows Server 2022（geo_win_svr 镜像）|
| 用户 | `ubuntu`（免密 sudo）| `Administrator` |
| 主机密码 | `<见 memory: 主机密码>` | 同左 |
| 代码目录 | `/opt/general-geo-eval` | `C:\general-geo-eval` |
| 服务 | systemd `geo-eval.service`（uvicorn :8000）+ nginx :80 | 任务计划 `WinDaemon`（aiohttp :8443）|
| 后端 admin | `admin` / `<见 memory: admin 密码>` | — |
| WEBHOOK_SECRET | `<见 memory: WEBHOOK_SECRET>` | 同左 |

区域 UCloud 乌兰察布 `cn-wlcb-01`，项目 `org-xuwspu`，两机同 VPC 内网互通。
真实密钥值见开发机 memory `general-geo-eval-deploy`，agent 代入命令时不回显。

**Win 远程执行全不可用**（22 开无 sshd、WinRM 5985/5986 开但不响应）→ Win 上一切操作必须在 RDP 会话里做。Linux 可全程 paramiko SSH 自动化。

---

## 3. 当前进度

| # | 任务 | 状态 |
|---|---|---|
| 34 | 建两台主机 | ✅ 完成 |
| 35 | 部署 Linux 后端 | ✅ 完成（health 200，admin 登录通，100 题已入库）|
| 36 | 部署 Win 守护进程 | ✅ 完成 |
| 37 | 首次登录 5 个模型 | ✅ 完成（kimi/deepseek/ernie/doubao/qwen storageState 全存到 `data\webchat_auth\`）|
| 38 | 联调小批次 | ✅ 完成（3 题×kimi GEO=75.0 全链路跑通）|
| 39 | 风控实测 + 收尾 | ✅ 完成（2 题×5 模型，乌兰察布无风控，4 模型出分，定稿）|

> 联调/风控详见开发机 memory `general-geo-eval-deploy`。本节为历史归档，无待办。

---

## 4. 联调批次（历史归档，已跑通）

首个联调批次曾因 **env 文件 UTF-8 BOM** 导致 `KeyError: 'BACKEND_URL'` 一启动就 exit 1，webhook 没送达。已修：`scripts/win_setup.ps1` 改用 `WriteAllText` + `UTF8Encoding($false)` 写无 BOM env；runner run_id 文件名对齐；确认页[开始]按钮加错误反馈。三坑修复后全链路跑通。

联调批次示例（已 completed/imported）：
```
TASK_ID  = task_20260625_230415_4a46d3   （3题 q001/q002/q003）
BATCH_ID = batch_20260625_230416_29fe79
RUN_ID   = run_20260625_230416_db4db4
模型     = kimi
```

新批次跑通流程（参考）：
1. RDP 浏览器开 `http://localhost:8443` → 应看到批次 + 各模型登录态
2. 点 [开始评测] → 守护进程调 `local_webchat_runner.py --headed`（未登录模型会先弹浏览器引导登录并保存）
3. 盯状态流转：`config_downloaded → pushed → awaiting_human → running → importing → imported`
4. Dashboard 出 GEO 评分 = 成功

---

## 5. 关键命令速查（Win RDP 管理员 PowerShell）

```powershell
# 守护进程管理
Start-ScheduledTask WinDaemon / Stop-ScheduledTask WinDaemon
Get-ScheduledTask WinDaemon | Select TaskName,State
Get-ScheduledTaskInfo WinDaemon | Select LastRunTime,LastTaskResult

# 自检
Invoke-WebRequest http://localhost:8443/status -UseBasicParsing | Select -ExpandProperty Content

# 前台跑看报错（调试用，pythonw 吞报错）
cd C:\general-geo-eval
& "C:\Program Files\Python311\python.exe" scripts\win_daemon.py

# 日志
Get-Content C:\general-geo-eval\output\win_daemon.log -Tail 50 -Wait

# 重装（拉最新代码，复用已装 Python/依赖；⚠️ 会 wipe 5 模型登录态，仅在首次部署或确认可重登时用）
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/lious68/general-geo-eval/master/scripts/win_setup.ps1"))) -BackendUrl "http://10.60.84.46" -WebhookSecret "<WEBHOOK_SECRET>" -ServicePassword "<admin 密码>"

# 5 模型登录（headed，逐个弹 Chrome）
python scripts\setup_webchat_auth.py all
```

---

## 6. 踩过的坑（避免重复）

1. **Win env 文件 BOM**：PowerShell 5.1 `Set-Content -Encoding UTF8` 写 BOM，python-dotenv 首行 key 读成 `﻿XXX` → KeyError。必须 `WriteAllText` + `UTF8Encoding($false)`。（已修，commit 7f1a6be）
2. **WindowsApps python.exe stub**：`Get-Command python` 找到的是商店重定向 stub 不是真 Python。安装脚本里 `Test-RealPy` 会跳过它 + 验证 `--version`。
3. **pip 连官方源 SSL EOF**（乌兰察布机房被墙）：装依赖必须用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；playwright chromium 用 `PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`。
4. **session 0 隔离**：Windows 服务（NSSM）跑在 session 0 无桌面 → headed 浏览器/验证码看不见。所以用任务计划 AtLogOn 在 Administrator 交互会话跑，**不用 NSSM**。
5. **多行粘贴倒序执行**：PowerShell 把多行倒着跑。安装脚本都走 `iex (irm <url>)` 一行式。
6. **pythonw 吞报错**：任务计划用 pythonw.exe 无窗口，崩了看不见。调试时改用 python.exe 前台跑抓 Traceback。
7. **文心一言域名迁移**：`yiyan.baidu.com` → `chat.baidu.com`（2026），登录态判据仍用 BDUSS cookie（commit e26a95e）。
8. **Win Server 镜像需 `--hot-plug false`** 才能创建；UCloud 无桌面版 Win11，用 Server 2022 带桌面体验等效。

更全的坑见开发机 memory：`ucloud-deploy-gotchas.md`（13 条）。

---

## 7. 接下来要做的

全部联调与风控实测已完成（见开发机 memory `general-geo-eval-deploy`）：3 题×kimi 联调 GEO=75.0 跑通；2 题×5 模型风控实测乌兰察布无验证码/封号/限流，4 模型正常出分，**乌兰察布定稿**；ernie chat.baidu.com 适配完成（commit e7f4dc8/986adac）。

后续只剩**日常迭代**：代码改了在开发机 `git push` → 「同步到云上」→ agent SSH 到 Linux `git pull`+重建前端+重启；Win 侧单文件热更新（见 runbook）。

---

## 8. 文心一言域名（重要）

`core/web_chat_auth.py` 的 `WEBCHAT_SITES["ernie"]["url"]` 已从 `yiyan.baidu.com` 改成 `chat.baidu.com`（commit e26a95e）。Win 上的代码需 `git pull` 或重跑 setup 才拿到新版。登录态判据不变（BDUSS httpOnly cookie）。
