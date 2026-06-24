# WebChat 本地评测使用指南

## 整体架构

```
┌───────────────────── 服务器 (Linux) ──────────────────────┐
│                                                             │
│  Evaluation.vue 前端                                        │
│  ├─ API 模式 → 直接调用模型 API + 联网搜索                   │
│  └─ WebChat 模式 → 下载任务配置 ↓                           │
│                                                             │
│                                    ┌─ 导入结果 ← 本地 .json  │
│                                    └─ Dashboard 展示结果      │
└─────────────────────────────────────────────────────────────┘
                              │
                    下载 task_config.json
                              │
                              ▼
┌───────────────────── 本地电脑 (Win10 / Mac) ───────────────┐
│                                                             │
│  python scripts/local_webchat_runner.py                     │
│    --config task_config.json --headed                       │
│                                                             │
│  → 弹出浏览器窗口（人可手动处理验证码/登录）                  │
│  → 自动提问 → 等待回复 → 分析 → 评分                        │
│  → 输出: output/webchat_评测_20260608_143022.json          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                    上传 .json 到服务器前端
                              │
                              ▼
                    服务器导入 → Dashboard 展示
```

## 使用流程

### 第一步：在服务器上选择 WebChat 评测

1. 登录服务器前端，进入「执行评测」页面
2. 选择「🌐 WebChat 模式」
3. 勾选要评测的模型（需已登录，显示「✓ 已登录」）
4. 选择品类筛选（可选）
5. 调整请求间隔（建议 8 秒以上）
6. 点击 **「下载任务配置」** → 获得 `webchat_task_XXX.json`

### 第二步：在本地电脑上运行评测

将 `webchat_task_XXX.json` 传到本地电脑后，有三种运行方式：

#### 方式 1：从配置文件运行（推荐）

```bash
# 显示浏览器窗口（可手动处理验证码/登录）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json --headed

# 后台运行（不显示窗口）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json
```

#### 方式 2：交互式引导（新手友好）

```bash
# 无参数启动，进入交互式配置引导
python scripts/webchat_run.py

# 或显式
python scripts/webchat_run.py --interactive
```

交互式会逐步引导选择：
- 模型 → 品类 → 延迟 → 输出路径 → 是否显示浏览器 → 确认执行

#### 方式 3：手动指定参数

```bash
# Windows 快捷启动
scripts\run_webchat.bat kimi headed

# Mac/Linux
python scripts/local_webchat_runner.py --models kimi ernie --headed --delay 10
python scripts/local_webchat_runner.py --models kimi --categories 云数据库
```

### 第三步：处理验证码/登录

使用 `--headed` 参数时，浏览器会弹出窗口。运行过程中：
- 如果需要登录 → 在浏览器窗口中手动登录
- 如果出现验证码 → 在浏览器窗口中手动完成验证
- 登录状态会自动保存，下次运行无需重复登录

### 第四步：上传结果到服务器

评测完成后，会在 `output/` 目录生成结果文件：
```
output/webchat_评测_20260608_143022.json
```

1. 将此文件传到服务器
2. 在服务器前端「执行评测」页面，找到「导入本地 WebChat 结果」区域
3. 拖拽或点击上传 .json 文件
4. 导入成功后，点击「查看结果 →」跳转到 Dashboard

## 命令参考

```bash
# 从服务器下载的任务配置运行
python scripts/local_webchat_runner.py --config task.json

# 从服务器下载的任务配置 + 显示浏览器
python scripts/local_webchat_runner.py --config task.json --headed

# 交互式配置引导
python scripts/webchat_run.py

# 手动指定模型
python scripts/local_webchat_runner.py --models kimi ernie doubao

# 指定品类
python scripts/local_webchat_runner.py --models kimi --categories 云数据库

# 指定输出路径
python scripts/local_webchat_runner.py --models kimi --output results/kimi.json

# 后台运行（不显示浏览器）
python scripts/local_webchat_runner.py --models kimi --headless
```

## Windows 快捷启动

```powershell
# 交互式引导
scripts\run_webchat.bat

# 指定模型 + 显示浏览器
scripts\run_webchat.bat kimi headed

# 从配置文件运行
scripts\run_webchat.bat config task.json
```

## Mac/Linux 快捷启动

```bash
# 交互式引导
python scripts/webchat_run.py

# 指定模型 + 显示浏览器
python scripts/webchat_run.py --models kimi ernie

# 从配置文件运行
python scripts/webchat_run.py --config task.json
```

## 三级任务架构：任务 → 模型 → 问题

为应对 DeepSeek 等平台「连续问询超过约 25 次即封号」，runner 已接入三级任务调度引擎（`core/scheduler.py`，server 与本地共用）：

```
Task (一次评测，对应一个 run_id)
  └─ Unit (run_id, model_key, question_id)  ← 唯一事实来源，自带 status
        └─ Scheduler：跨模型交错 + 逐模型限流 + 单题重试 + 封号退避
```

### 防封号三策并用

1. **跨模型交错**：每模型一个并发 worker，按问题顺序推进，自然交错各平台请求。
2. **逐模型限流配额**（`core/webchat_policy.py` 的 `MODEL_POLICY`）：
   - `max_consecutive` 突发上限，达到后强制 `burst_cooldown`；
   - 滑动窗口 `rate_max` / `rate_window_sec`（DeepSeek 默认 ≤20 次/小时）；
   - `inter_unit_delay` 相邻请求最小间隔。
   - DeepSeek 已收紧：突发 15、每小时 20、封号冷却 1800s。
3. **封号信号检测 + 自动退避**：页面/错误出现「频率过快/登录已过期」等信号时——限流类→长冷却后单元退回 `pending` 重试；登录失效→该模型剩余单元 `skipped`（需人工重登）。
4. **单题多次重试**：瞬态错误（超时/空响应/提取失败）指数退避 + 抖动重试，超 `max_attempts` 落 `failed`。

> `analysis_results` 唯一性靠 `(run_id, question_id, model_key)` 三元组，GEO 评分计算不依赖落库顺序——所以交错执行对最终评分零影响。

### 断点续跑（零中断）

- 每个单元状态持久化到 `data/local_runs/<run_id>.db`；
- 每完成一题即增量写 `output/<run_id>.partial.json`，**崩溃也不丢已完成题**；
- 中断后用同一 `run_id` 恢复，自动跳过 `done`，仅补跑 `pending/failed`：

```bash
# 首次运行（控制台会打印 run_id，如 20260617_103022_a1b2c3）
python scripts/local_webchat_runner.py --config task.json --headed

# 中断后续跑
python scripts/local_webchat_runner.py --resume 20260617_103022_a1b2c3 --headed
```

### 调参

DeepSeek 等敏感平台的限流参数在 `core/webchat_policy.py` 的 `_MODEL_OVERRIDES`。若实测仍触发风控，进一步调小 `max_consecutive` / `rate_max`，或调大 `burst_cooldown` / `ban_cooldown_sec`。


## 云上自动化模式（服务器推送 + Win 守护进程）

部署后可省去手动下配置 / 敲命令 / 传结果三步。整体链路：

```
Linux 后端建批次 → webhook 推 Win 守护进程
   → Win 探登录态 → 弹通知 → 你 RDP 上 Win 开 http://localhost:8443 点[开始]
   → 守护进程自动调 local_webchat_runner --headed 跑（每模型满20题休息1小时）
   → 跑完自动回传 import-results → Dashboard 出分
```

### Windows 守护进程安装

1. RDP 上 Win 机器，确保已装 Python 3.11 + 项目依赖（`requirements.txt` + `scripts/win_requirements.txt`）+ Playwright 浏览器。
2. 复制 `scripts/win_daemon.env.example` → `scripts/win_daemon.env`，填 `BACKEND_URL`/`SERVICE_PASSWORD`/`WEBHOOK_SECRET`（与后端 `.env` 一致）。
3. 装 [NSSM](https://nssm.cc/) 并放 PATH。
4. 管理员权限运行 `scripts\install_win_daemon.bat`。
5. 验证：浏览器开 `http://localhost:8443` 见确认页；`nssm status WinDaemon` 为 RUNNING。

### Linux 后端配置

`.env` 加两项（与 Win 端对应）：

```
WEBHOOK_WIN_URL=http://<win内网IP>:8443
WEBHOOK_SECRET=<与 Win 端一致>
```

### 日常使用

1. 浏览器开 Linux 后端 → 建任务 + 添加批次 → 批次状态自动 `config_downloaded → pushed`。
2. Win 守护进程收到推送 → 探登录态：全登录则确认页可点[开始]；有未登录则先在 Win 浏览器登录该模型。
3. RDP 上 Win 开 `http://localhost:8443` → 点[开始] → runner 自动跑（headed，注意处理验证码）。
4. Dashboard 每 15s 自动刷新批次状态（pushed/awaiting_human/running/importing/imported）。
5. 推送丢失/Win 离线时，批次行点「重推」重新触发。

### 断点续跑

守护进程崩溃 / Win 重启后，启动时自动 `GET /api/batches/pending` 拉未完成批次入队续跑；runner 的 `output/<run_id>.partial.json` 保证已完成题不丢。
