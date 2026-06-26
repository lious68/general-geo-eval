# Win 守护进程交接文档（2026-06-25）

> 给 Win 主机上的 Claude Code 用：读这份就等于接上了当前进度。
> 本机（开发机 `C:\Users\las\general-geo-eval`）的会话上下文无法跨机器同步，这份文档是等价替代。
> 项目分支 `feat/webchat-cloud-automation`，最新 commit `7f1a6be`。

---

## 1. 这套系统是什么

WebChat 云上自动化：Linux 后端建批次 → webhook 推 Win 守护进程 → 守护进程在 RDP 里跑 Playwright headed 评测（浏览器可见，能过验证码）→ 自动回传结果。消除手动下载配置/敲命令/上传结果三步。

**核心约束（不可违反）：**
- 所有评测必须 **headed**（非 headless），验证码才看得见能过
- 每个模型跑 20 题/小时后**休息 1 小时**（`webchat_policy` 限流，防封号）
- **decision-a「人在才跑」**：守护进程只在 Administrator 登录 RDP 时才跑（任务计划 AtLogOn 触发）；人不在时批次留 `config_downloaded`，下次登录 `_bootstrap_pending` 自动拉回
- `.env` / `win_daemon.env` 含密钥，**绝不 push GitHub**

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
| 主机密码 | `GeoEval2026Server` | `GeoEval2026Server` |
| 代码目录 | `/opt/general-geo-eval` | `C:\general-geo-eval` |
| 服务 | systemd `geo-eval.service`（uvicorn :8000）+ nginx :80 | 任务计划 `WinDaemon`（aiohttp :8443）|
| 后端 admin | `admin` / `GeoEval2026` | — |
| WEBHOOK_SECRET | `WHK_4H5AATfjgv2BVi8Iv3lru3HMD-75gicH` | 同左 |

区域 UCloud 乌兰察布 `cn-wlcb-01`，项目 `org-xuwspu`，两机同 VPC 内网互通。

**Win 远程执行全不可用**（22 开无 sshd、WinRM 5985/5986 开但不响应）→ Win 上一切操作必须在 RDP 会话里做。Linux 可全程 paramiko SSH 自动化。

---

## 3. 当前进度

| # | 任务 | 状态 |
|---|---|---|
| 34 | 建两台主机 | ✅ 完成 |
| 35 | 部署 Linux 后端 | ✅ 完成（health 200，admin 登录通，100 题已入库）|
| 36 | 部署 Win 守护进程 | ✅ 完成（但 env BOM bug 刚修，待最终验证）|
| 37 | 首次登录 5 个模型 | ✅ 完成（kimi/deepseek/ernie/doubao/qwen storageState 全存到 `data\webchat_auth\`）|
| **38** | **联调小批次** | 🔄 **进行中（当前卡点）** |
| 39 | 风控实测 + 收尾 | ⏳ 待 |

---

## 4. 当前卡点（联调小批次）

已在后端建了一个联调批次推过去，但 Win 守护进程之前因 **env 文件 UTF-8 BOM** 导致 `KeyError: 'BACKEND_URL'` 一启动就 exit 1，所以 webhook 没送达。

**已做的修复：**
1. `scripts/win_setup.ps1` 改用 `WriteAllText` + `UTF8Encoding($false)` 写无 BOM env（commit `7f1a6be`，已 push）
2. 待用户在 Win RDP 手动重写 env 一次（Win 上跑的 setup 是旧的）

**待验证的联调批次：**
```
TASK_ID  = task_20260625_230415_4a46d3   （联调小批次，3题 q001/q002/q003）
BATCH_ID = batch_20260625_230416_29fe79
RUN_ID   = run_20260625_230416_db4db4
模型     = kimi
当前状态 = config_downloaded（webhook 未送达，待守护进程起来后 _bootstrap_pending 自动拉）
```

**联调验证流程（守护进程起来后）：**
1. RDP 浏览器开 `http://localhost:8443` → 应看到批次 + kimi 登录态
2. 点 [开始评测] → 守护进程调 `local_webchat_runner.py --headed`
3. 盯状态流转：`config_downloaded → pushed → awaiting_human → running → importing → imported`
4. Dashboard 出 GEO 评分 = 联调成功

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

# 重装（拉最新代码，复用已装 Python/依赖）
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/lious68/general-geo-eval/feat/webchat-cloud-automation/scripts/win_setup.ps1"))) -BackendUrl "http://10.60.84.46" -WebhookSecret "WHK_4H5AATfjgv2BVi8Iv3lru3HMD-75gicH" -ServicePassword "GeoEval2026"

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

**Task #38 联调**（当前）：守护进程验证起来 → 确认页点开始 → 跑通 3 题 kimi → Dashboard 出分。

**Task #39 风控实测 + 收尾**：
- 5 题 × 5 模型，测乌兰察布机房 IP 风控
- 频繁验证码/封号 → 改广州区域重建
- 稳定 → 乌兰察布定稿，更新 memory + commit

---

## 8. 文心一言域名（重要）

`core/web_chat_auth.py` 的 `WEBCHAT_SITES["ernie"]["url"]` 已从 `yiyan.baidu.com` 改成 `chat.baidu.com`（commit e26a95e）。Win 上的代码需 `git pull` 或重跑 setup 才拿到新版。登录态判据不变（BDUSS httpOnly cookie）。
