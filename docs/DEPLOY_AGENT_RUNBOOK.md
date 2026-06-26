# Agent 一键双机部署 Runbook

> **这份文档写给 agent 自己看。** agent 读完本文档 + `WIN_HANDOFF.md` + 开发机 memory
>（`general-geo-eval-deploy` / `ucloud-deploy-gotchas`），就能把这套 GEO 评估系统
> 从零部署到 UCloud 乌兰察布双机、让全世界访问 dashboard。
>
> 全程意图驱动：用户只说「帮我部署」「同步到云上」，agent 调 UCloud CLI + SSH 自己干。

---

## 0. 前置（一次性，人在终端做）

```bash
# 装 UCloud CLI（自动识别系统架构）
npx skills add ucloud/skills ucloud-cli
# OAuth 登录（弹 UCloud 官网，不碰 AK/SK；需交互式终端，agent 跑不了这步）
ucloud auth login
```

授权后凭证存在 `~/.ucloud/`，agent 用已登录 profile 操作资源，不再过问密钥。

> 🔐 **安全铁律**：绝不在说明/计划/命令预览/补丁/摘要里打印 UCLOUD_PUBLIC_KEY/PRIVATE_KEY 或原始密钥。
> 主机密码/admin 密码/WEBHOOK_SECRET 只在开发机 memory 里，代入命令时不回显。

---

## 1. 读代码判断规格（agent 自主）

agent 先 Read 这几处，理解系统复杂度，再决定要几台机器、什么系统、什么规格：

- `backend/app.py` + `backend/routers/*` → FastAPI 后端，sqlite，无重型依赖
- `frontend/package.json` → Vue3 + Vite，构建需 Node 20+
- `core/web_chat_clients.py` + `scripts/local_webchat_runner.py` → Playwright **headed** 评测
- `scripts/win_daemon.py` → aiohttp 守护进程，调 runner 带 `--headed`

**结论（已验证的最小规格）**：
- **Linux 后端**：Ubuntu 22.04，4 核 8G，50G 云盘。跑 FastAPI+nginx+构建前端。
- **Win 评测机**：Windows Server 2022（带桌面体验），4 核 8G，50G 云盘。跑 Playwright headed。
- 两台同 VPC 内网互通；Linux 绑公网 EIP（dashboard 全世界访问），Win 仅内网+RDP。

---

## 2. 用 UCloud CLI 建双机（agent 调，用户只做选择）

agent 用已登录 profile 调 CLI，隐藏 region code/镜像名/参数。用户只回答选择题。

### 2.1 复用现成网络资源（乌兰察布默认有）

```bash
ucloud region                              # 确认 region code（乌兰察布 cn-wlcb / cn-wlcb-01）
ucloud project list                        # 项目 org-xuwspu
ucloud vpc list --region cn-wlcb           # DefaultVPC
ucloud subnet list --region cn-wlcb        # 子网
ucloud firewall list --region cn-wlcb      # 「Web服务器推荐」防火墙（开 22/3389/80/443/ICMP）
```

### 2.2 建主机（坑已沉淀在 skill，自动绕过）

```bash
# Linux 后端
ucloud uhost create --region cn-wlcb --zone cn-wlcb-01 --project-id org-xuwspu \
  --image-id <Ubuntu 22.04 镜像> --cpu 4 --memory-gb 8 --disk-gb 50 \
  --password <纯字母数字主机密码> --create-eip-line BGP --create-eip-traffic-mode Traffic \
  --firewall-id <Web服务器推荐> --subnet-id <子网> --uhost-name geo-eval-backend

# Win 评测机（必须 --hot-plug false，否则报 8041；无桌面版 Win11 用 Server 2022）
ucloud uhost create --region cn-wlcb --zone cn-wlcb-01 --project-id org-xuwspu \
  --image-id <Win Server 2022 镜像> --cpu 4 --memory-gb 8 --disk-gb 50 \
  --hot-plug false \
  --password <同上> --firewall-id <Web服务器推荐> --subnet-id <子网> --uhost-name geo-eval-win
```

> 结尾的 `299 IAM permission error` 无害，忽略。密码必须纯字母数字（含 `!` 会静默失效）。

### 2.3 agent 把结果交给用户

```
Linux 后端  公网 IP 117.50.x.x  用户 ubuntu   密码 <主机密码>
Win 评测机  公网 IP 117.50.y.y  RDP Administrator  密码 <主机密码>
两台同 VPC 内网互通。
```

---

## 3. 部署 Linux 后端（agent SSH 全自动）

Linux 有 sshd + 免密 sudo 的 ubuntu 用户，agent 用 paramiko 全程自动化。

```bash
ssh ubuntu@<Linux EIP>

# 3.1 拉代码（master 分支，GitHub 权威源）
sudo mkdir -p /opt/general-geo-eval && sudo chown ubuntu:ubuntu /opt/general-geo-eval
git clone https://github.com/lious68/general-geo-eval.git /opt/general-geo-eval
cd /opt/general-geo-eval && git checkout master

# 3.2 装 Python 依赖（venv，乌兰察布走清华镜像）
python3 -m venv venv
source venv/bin/activate
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r scripts/win_requirements.txt        # 含 aiohttp/httpx/dotenv
pip install fastapi uvicorn aiosqlite python-dotenv openai snownlp pandas openpyxl numpy playwright httpx

# 3.3 构建前端（Node 20+，乌兰察布走 npmmirror）
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run build            # 产物 frontend/dist，nginx 伺服
cd ..

# 3.4 初始化数据库
cd backend
PYTHONPATH=/opt/general-geo-eval/backend:/opt/general-geo-eval/core /opt/general-geo-eval/venv/bin/python -c \
  "import asyncio; from database import init_db; asyncio.run(init_db())"
cd ..

# 3.5 写 .env（含密钥，不进 git）
#   WEBHOOK_WIN_URL=http://<Win 内网 IP>:8443
#   WEBHOOK_SECRET=<与 Win 共享>
#   API keys 留空（走 WebChat 模式不需要）
cat > /opt/general-geo-eval/.env <<'EOF'
WEBHOOK_WIN_URL=http://10.60.164.214:8443
WEBHOOK_SECRET=<WEBHOOK_SECRET>
EOF

# 3.6 systemd 服务（不用 xvfb-run——headed 跑在 Win 不在 Linux）
sudo tee /etc/systemd/system/geo-eval.service >/dev/null <<'EOF'
[Unit]
Description=General GEO Eval API
After=network.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/general-geo-eval/backend
ExecStart=/opt/general-geo-eval/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
Environment=PYTHONPATH=/opt/general-geo-eval/backend:/opt/general-geo-eval/core
Environment=WEBHOOK_WIN_URL=http://10.60.164.214:8443
Environment=WEBHOOK_SECRET=<WEBHOOK_SECRET>
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now geo-eval

# 3.7 nginx 反代 :80 → :8000
sudo cp /opt/general-geo-eval/nginx.conf /etc/nginx/conf.d/geo-eval.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# 3.8 验证
curl -s http://localhost/api/health        # → {"status":"ok"}
curl -s http://<Linux EIP>/api/health      # 公网可达 → 全世界可访问 dashboard
```

dashboard：`http://<Linux EIP>/`（admin 登录，密码见 memory）。

---

## 4. 部署 Win 守护进程（agent 指导，人在 RDP 做）

> ⚠️ **Win 远程执行全不可用**：22 开无 sshd、WinRM 5985/5986 开但不响应 → 只能 RDP。
> 这契合 decision-a「人在才跑」——headed 评测要人盯验证码。

### 4.1 RDP 登录后，管理员 PowerShell 一键安装

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/lious68/general-geo-eval/master/scripts/win_setup.ps1"))) `
  -BackendUrl "http://10.60.84.46" `
  -WebhookSecret "<WEBHOOK_SECRET>" `
  -ServicePassword "<admin 密码>"
```

`win_setup.ps1` 自动：下载 master zip → 装 Python 3.11 + 依赖（清华镜像）→ playwright chromium（npmmirror）→ 写无 BOM `win_daemon.env` → 注册任务计划 `WinDaemon`（AtLogOn 登录自启，非 NSSM——session 0 跑不了 headed）→ 自检 `:8443/status`。

### 4.2 5 模型首次登录（headed，逐个弹 Chrome）

> 模型**不要求预先登录**：未登录的模型跑批次时会自动弹浏览器引导登录并保存。但建议先手动登录一次更顺。

```powershell
cd C:\general-geo-eval
python scripts\setup_webchat_auth.py all
```

逐个弹浏览器，手动登录 kimi/deepseek/ernie/doubao/qwen，登录态存到 `data\webchat_auth\<model>_state.json`，复用。

### 4.3 验证守护进程

```powershell
Invoke-WebRequest http://localhost:8443/status -UseBasicParsing | Select -ExpandProperty Content
```

确认页 `http://localhost:8443`（RDP 内浏览器开，跑批次时点[开始]）。

---

## 5. 联调验证

1. dashboard 建任务 → 展开点「添加批次」选模型×品类×题区间 → 下载配置。
   - **模型下拉应显示全部 5 个**（已登录的带 ✓ 角标），不再只有 `all`。
2. 后端 webhook 推 Win → Win 确认页出现批次 + 登录态。
3. 点[开始] → 状态流转 `config_downloaded → pushed → awaiting_human → running → importing → imported`。
4. Dashboard 出 GEO 评分 = 成功。

---

## 6. 日常迭代（代码更新了，同步到云上）

### 6.1 Linux（agent SSH 全自动）

```bash
ssh ubuntu@<Linux EIP> '
  cd /opt/general-geo-eval && git pull origin master &&
  cd frontend && npm run build && cd .. &&
  sudo systemctl restart geo-eval &&
  curl -s http://localhost/api/health'
```

### 6.2 Win（单文件热更新，别重跑 win_setup——会 wipe 登录态）

Win 远程不可用，要么 RDP 内手动拉，要么 agent 指导用户在 RDP PowerShell 跑：

```powershell
# 单文件热更（举例：改了 web_chat_clients.py）
$base = "https://raw.githubusercontent.com/lious68/general-geo-eval/master"
foreach ($p in @("core/web_chat_clients.py","scripts/local_webchat_runner.py")) {
  $local = "C:\general-geo-eval\$p"
  Invoke-WebRequest "$base/$p" -OutFile $local
}
Start-ScheduledTask WinDaemon   # 重启守护进程加载新代码
```

> ⚠️ **绝不要重跑 `win_setup.ps1`**：它会重新下载覆盖 `C:\general-geo-eval`，wipe `data\webchat_auth\` 5 模型登录态。

---

## 7. 踩坑速查（完整版见 memory `ucloud-deploy-gotchas`）

| 坑 | 修法 |
|---|---|
| CLI OAuth 非交互跑不了 | 人在终端 `ucloud auth login`，agent 复用 profile |
| `uhost create` 密码含 `!` 静默失效 | 纯字母数字密码（大写+小写+数字） |
| Win Server 镜像报 8041 hotplug | `--hot-plug false` |
| 乌兰察布 pip 被墙 | 清华镜像；playwright 用 `PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright` |
| win_daemon.env BOM → KeyError | `WriteAllText` + `UTF8Encoding($false)`（win_setup 已修） |
| Win 服务 session 0 无桌面 | 任务计划 AtLogOn，不用 NSSM |
| `uhost delete` 删不掉 | profile 默认 region 是上海，先 `ucloud config update --region cn-wlcb --zone cn-wlcb-01` |
| 文心一言迁 chat.baidu.com | 选择器 `.answer-box.last-answer-box`（短横线非驼峰） |

---

## 8. 主机信息（密钥见 memory，不进 repo）

| | Linux 后端 | Win 守护进程 |
|---|---|---|
| UCloud 主机名 | geo-eval-backend | geo-eval-win |
| 公网 EIP | `117.50.195.148` | `117.50.189.16` |
| 内网 IP | `10.60.84.46` | `10.60.164.214` |
| 系统 | Ubuntu 22.04 | Windows Server 2022 |
| 用户 | `ubuntu`（免密 sudo）| `Administrator`（RDP）|
| 密码 | `<见 memory>` | 同左 |
| 代码目录 | `/opt/general-geo-eval` | `C:\general-geo-eval` |
| 服务 | systemd `geo-eval` | 任务计划 `WinDaemon` |

区域乌兰察布 `cn-wlcb-01`，项目 `org-xuwspu`，同 VPC 内网互通。
真实密钥值在开发机 memory `general-geo-eval-deploy`，agent 代入命令时不回显。
