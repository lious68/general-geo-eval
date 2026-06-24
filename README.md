# 通用 GEO 评估系统

> 类似 [geo.timus.cn](https://geo.timus.cn/) 的 GEO（Generative Engine Optimization）评分体系，评估**任意品牌**在五大 AI 模型中的品牌可见度。由 UCloud 专用版（ucloud-geo-eval）通用化演化而来：首页输入被测品牌/官网/行业，AI 按行业特性生成题集，评测指标对任意品牌生效。

## 🆕 通用化使用流程

1. **设置品牌档案**：登录后首页（「品牌设置」）填写被测品牌名、公司名、官网、行业并保存。首次未设置时会弹必填对话框，品牌名与网站为必选项。系统据此自动派生品牌关键词、官方域名、引用 URL 规则。
2. **AI 生成题集**：进入「问题管理」→「AI 生成问题」，选择已配置模型，AI 按行业生成若干场景、**每个场景恰好 5 个示例问题**（含品牌词/公司名/产品型号，模拟真实搜索意图），生成后替换当前题集。
3. **执行评测**：在「执行评测」按 任务→模型→问题 三级架构下载配置、本地运行、导入结果。
4. **查看结果**：仪表盘展示被测品牌的提及率/引用率/TOP3 推荐率/情感值/GEO 综合得分。

> 旧 UCloud 数据库无需迁移：未设置品牌档案时自动回退 UCloud 默认档案，历史数据照常工作。

## 🎯 核心指标

| 指标 | 说明 | 计算公式 | 权重 |
|------|------|---------|------|
| **提及率** | UCloud 被提及的自然问题响应比例 | UCloud 被提及的自然有效响应数 / 自然有效响应总数 | 45% |
| **引用率** | 包含 UCloud 有效引用的响应比例 | 含 UCloud 官方引用或相关第三方来源引用的响应数 / 全部有效响应总数 | 25% |
| **TOP3推荐率** | UCloud 进入前三推荐位的自然问题响应比例 | UCloud 进入 TOP3 推荐的自然响应数 / 自然有效响应总数 | 20% |
| **情感值** | 全部有效响应的平均情感倾向 | Σ(全部有效响应的情感分数) / 全部有效响应总数 | 10% |
| **GEO综合得分** | 四指标加权求和 (0-100) | (提及率×45% + 引用率×25% + TOP3推荐率×20% + 情感值×10%) × 100 | — |

> **自然问题**：排除引导型问题（Q1-Q10）及题干自带 UCloud/优刻得 字眼的问题。提及率、TOP3推荐率仅统计自然问题；引用率、情感值统计全部有效问题。

## 👥 用户与权限

系统支持多用户、双角色权限管理：

| 角色 | 权限 |
|------|------|
| **管理员 (admin)** | 完整权限：查看数据、执行评测、管理问题、修改配置、管理用户 |
| **查看者 (viewer)** | 只读权限：查看所有页面和数据，不能增删改任何内容 |

- **首次使用**：设置管理密码后自动创建 admin 账号
- **添加用户**：管理员在「系统设置」→「👥 用户管理」中添加查看者账号
- **登录方式**：用户名 + 密码（兼容旧密码自动迁移）
- **修改密码**：每个用户可修改自己的密码

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│              Nginx (Port 80)                      │
│  /            → 前端静态文件 (Vue 3 + Element Plus) │
│  /api/*       → 反代到 Uvicorn (Port 8000)        │
│  /api/ws/*    → WebSocket 实时进度推送             │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│          FastAPI Backend (Python)                 │
│  ├─ 鉴权中间件 (Token + 角色权限)                 │
│  ├─ 三级任务管理 (任务→模型→问题, WebChat 模式)    │
│  │   ├─ tasks 顶层表 + task_id/batch_id 跨批次合并 │
│  │   └─ 固定总题集 + 按 (task,model,question) 去重 │
│  ├─ 评测管理 (API 模式 创建/执行/删除)             │
│  ├─ 结果查询 (评分/详情/图表/引用/下钻, 支持 task_id)│
│  ├─ 引用源统计 (全量来源聚类/下钻)                │
│  ├─ 问题管理 (CRUD)                              │
│  ├─ 用户管理 (添加/删除/角色分配)                  │
│  └─ 系统设置 (API Key/模型配置)                   │
├───────────────────────────────────────────────────┤
│  SQLite 数据库 (data/geo.db)                      │
├───────────────────────────────────────────────────┤
│  Core 评估引擎 (服务器 + 本地 runner 共用)         │
│  ├─ scheduler.py      → 三级调度(交错/限流/重试/封号退避/续跑) │
│  ├─ task_units.py     → 单元状态层(断点续跑)        │
│  ├─ webchat_policy.py → 逐模型限流策略 + 封号信号检测 │
│  ├─ model_clients.py  → 5大模型API (OpenAI兼容)   │
│  ├─ analyzer.py       → 响应分析 (提及/引用/推荐)  │
│  ├─ metrics.py        → GEO指标计算               │
│  └─ config.py         → 品牌关键词/评分参数/URL渠道 │
└───────────────────────────────────────────────────┘
```

## 📁 项目结构

```
general-geo-eval/
├── core/                        # 核心评估引擎（服务器 + 本地 runner 共用）
│   ├── config.py                # 模型配置、默认品牌关键词、评分参数、URL渠道映射
│   ├── brand_profile.py         # 通用品牌档案（BrandProfile）+ 自然问题判定
│   ├── questions.py             # 默认题集（UCloud，向后兼容；实际题集由 AI 生成）
│   ├── model_clients.py         # AI模型API客户端（OpenAI兼容）
│   ├── analyzer.py              # 响应分析器（提及/引用/推荐/情感/全URL检测）
│   ├── metrics.py               # GEO指标计算引擎
│   ├── report.py                # 报告生成器（HTML/Excel）
│   ├── web_chat_clients.py      # WebChat浏览器自动化客户端（5模型Playwright）
│   ├── web_chat_auth.py         # WebChat认证状态管理
│   ├── scheduler.py             # 三级调度引擎（交错/限流/重试/封号退避/断点续跑）
│   ├── task_units.py            # 单元状态层（断点续跑的唯一事实来源）
│   ├── webchat_policy.py        # 逐模型限流策略 + 封号信号检测
│   └── main.py                  # CLI 主执行脚本
│
├── backend/                     # Web 后端 (FastAPI)
│   ├── app.py                   # FastAPI 入口 + 鉴权中间件 + 角色权限
│   ├── database.py              # SQLite 异步数据库 + 迁移 + 用户管理 + task 维度查询
│   ├── models.py                # Pydantic 数据模型（含 TaskCreate/BatchCreate）
│   ├── routers/
│   │   ├── auth.py              # 登录鉴权 + 用户管理 API + require_admin
│   │   ├── tasks.py             # 三级任务管理（建任务/批次/导入/评分/详情）
│   │   ├── evaluations.py       # API 模式评测管理 + WebSocket 进度
│   │   ├── results.py           # 结果查询（支持 task_id）/ 引用 / 下钻
│   │   ├── questions.py         # 问题管理
│   │   ├── settings.py          # 系统设置
│   │   └── webchat.py           # WebChat认证状态上传/验证
│   └── services/
│       ├── task_service.py      # 三级任务领域逻辑（合并去重/重算/覆盖率矩阵）
│       ├── eval_runner.py       # API 模式异步评测执行器
│       ├── question_generator.py# AI 题集生成（按行业每场景5题）
│       └── chart_builder.py     # ECharts 图表 JSON 构建
│
├── frontend/                    # Web 前端 (Vue 3)
│   └── src/
│       ├── views/
│       │   ├── Home.vue             # 🏠 品牌设置首页（品牌/网站必填提示）
│       │   ├── Dashboard.vue       # 📊 GEO 仪表盘（支持 ?task_id= 任务级）
│       │   ├── Evaluation.vue      # 🚀 执行评测（三级任务管理入口，嵌入 TaskList）
│       │   ├── TaskList.vue        # 📋 任务列表 + 新建任务向导
│       │   ├── TaskDetail.vue      # 🧩 任务详情（模型×题覆盖率矩阵 + 批次 + 导入）
│       │   ├── History.vue         # 📜 历史评测情况
│       │   ├── CitationSources.vue # 🔗 引用源情况
│       │   ├── Questions.vue       # 📝 问题管理
│       │   ├── Settings.vue        # ⚙️ 系统设置 + 用户管理
│       │   └── Login.vue           # 🔐 登录（用户名+密码）
│       ├── api/
│       │   └── tasks.js            # /api/tasks 路由组 API 客户端
│       ├── stores/
│       │   └── evalProgress.js     # 评测进度全局状态（跨页面可见）
│       └── composables/
│           └── useWebSocket.js     # API 请求 + WebSocket + 角色管理
│
├── scripts/                     # 工具脚本
│   ├── setup_webchat_auth.py    # WebChat 登录态设置脚本（本地运行）
│   ├── local_webchat_runner.py  # 本地 Playwright WebChat 评测 runner（消费 v2 任务配置）
│   ├── webchat_run.py           # WebChat 交互式一键启动（Win/Mac通用）
│   ├── run_webchat.bat          # Windows 快捷启动脚本
│   ├── test_db_migration.py     # 自检：tasks 表 + task_id 列迁移幂等
│   ├── test_tasks_service.py    # 自检：task_service 合并去重/矩阵/重算
│   ├── test_tasks_api.py        # 自检：/api/tasks 全链路冒烟
│   ├── test_runner_v2_config.py # 自检：本地 runner v2 配置解析
│   ├── test_scheduler_selfcheck.py  # 自检：调度器交错/限流/重试/封号/续跑/每模型题区间
│   ├── webchat_interactive_helper.py  # VNC 远程反爬验证辅助
│   └── inspect_chat_dom.py      # 聊天页面 DOM 检查工具
│
├── docs/
│   ├── webchat_local_guide.md           # WebChat 本地评测详细使用指南
│   └── superpowers/
│       ├── specs/2026-06-17-evaluation-three-level-design.md   # 三级任务架构设计
│       └── plans/2026-06-17-evaluation-three-level.md          # 实施计划
│
├── data/
│   └── webchat_auth/            # WebChat 认证状态文件目录
│       └── {model}_state.json   # 各模型 Playwright storageState
│
├── nginx.conf                   # Nginx 配置
├── deploy.sh                    # 一键部署脚本
├── ucloud-geo.service           # systemd 服务配置
└── DEPLOY.md                    # 部署文档
```

## 🚀 快速开始

### 环境准备

**Python 3.9+** 是必需的。

**本地电脑（Win10/Mac/Linux）：**
```bash
# 克隆项目
git clone https://github.com/lious68/general-geo-eval.git
cd general-geo-eval

# 安装 Python 依赖（Playwright 浏览器自动化）
pip install -r backend/requirements.txt
pip install playwright
playwright install chromium

# 设置 WebChat 登录状态（首次运行只需一次）
python scripts/setup_webchat_auth.py kimi
# ... 其他模型同理
```

**服务器（Linux，一键部署）：**
```bash
# 1. 克隆项目
git clone https://github.com/lious68/general-geo-eval.git
cd general-geo-eval

# 2. 一键部署
bash deploy.sh
```

部署完成后访问 `http://<服务器IP>/`，首次使用设置管理密码，然后在「系统设置」页面配置 API Key、添加查看者账号。

### WebChat 联网搜索评测（三级任务架构，云 + 本地联动）

除 API 模式外，系统支持 **WebChat 模式**——通过 Playwright 浏览器自动化，模拟真实用户在各 AI 模型官网的聊天交互，获取带联网搜索引用的完整响应。WebChat 模式采用 **任务 → 模型 → 问题** 三级任务架构，将网站管理端与实际执行端解耦：

- **服务器（Linux）**：任务创建、参数配置、结果合并与去重、数据展示
- **本地电脑（Win/Mac）**：异步执行实际评测（浏览器自动化），不受网站服务/浏览器状态/网络波动影响

**为什么需要三级任务架构？** DeepSeek 等平台对高频连续请求极敏感，同一账号短时连续问询超过约 25 次即触发封号。标准基准 40 题 × 5 模型 = 200 次请求，链路必须零中断、可恢复。三级任务机制通过单元级持久化 + 跨模型交错 + 逐模型限流 + 封号信号自动退避 + 单题多次重试 + 断点续跑来保证完整性。

**数据结构支持灵活追加与分批执行：**
- 同一任务下可以先评测模型 1，后续再增加模型 2
- 同一模型下可以先执行第 1–20 题，再补充执行第 21–40 题
- 服务器按 `(task_id, model_key, question_id)` 自动合并多次导入，以任务为最终汇总单位，避免重复执行、结果覆盖或数据错乱

**支持的 WebChat 模型：**

| 模型 | 网址 | 联网搜索 |
|------|------|---------|
| DeepSeek | chat.deepseek.com | ❌ 无 |
| 文心一言 | yiyan.baidu.com | ✅ 有 |
| 豆包 | doubao.com/chat | ✅ 有 |
| Kimi | www.kimi.com | ✅ 有 |
| 千问 | www.qianwen.com | ✅ 有 |

#### 整体工作流

```
┌──────────────────── 服务器 (Linux) ──────────────────────┐
│  /evaluation 三级任务管理页                                │
│  ① 新建任务 → 拍板固定总题集                                │
│  ② 任务下挂模型 + 每模型题区间 → 下载 task_config.json     │
│        (含 task_id / batch_id / units)                    │
│  ④ 导入结果 JSON → 按 (task,model,question) 合并去重        │
│     → 重算 GEO 评分 → 覆盖率矩阵 + Dashboard 展示          │
└────────────────────────┬─────────────────────────────────┘
                         │ 下载 task_config.json
                         ▼
┌──────────────────── 本地电脑 (Win / Mac) ────────────────┐
│  python scripts/local_webchat_runner.py                  │
│    --config task_config.json --headed                    │
│  EvalScheduler：跨模型交错 + 逐模型限流 + 单题重试         │
│                 + 封号信号退避 + 断点续跑(--resume)        │
│  → output/<run_id>.json (meta 透传 task_id / batch_id)    │
└────────────────────────┬─────────────────────────────────┘
                         │ 上传结果 JSON
                         ▼
              服务器导入 → 合并 → 矩阵刷新 + 评分重算
```

#### 第一步：在服务器上创建任务并下载配置

1. 登录服务器前端 → 「执行评测」页面（即三级任务管理页）
2. 点击 **「新建任务」**：填任务名 + 选品类 → **拍板固定总题集**（创建后不可改）
3. 在任务下 **「添加评测模型」**：每行选一个模型 + 该模型要跑的题区间（总题集子集，默认全选）→ 点击 **「下载任务配置」** → 浏览器下载 `task_<name>_<batch_id>.json`
   - 可重复添加：先下模型 1 的 1–20 题，后补模型 2、或模型 1 的 21–40 题——每次独立批次 + 独立配置下载

#### 第二步：在本地电脑上运行评测

将 `task_<name>_<batch_id>.json` 传到本地电脑后运行：

```bash
# 显示浏览器窗口（可手动处理验证码/登录）
python scripts/local_webchat_runner.py --config task_<name>_<batch_id>.json --headed

# 后台运行（不显示窗口）
python scripts/local_webchat_runner.py --config task_<name>_<batch_id>.json
```

runner 解析 v2 配置中的 `units`（每模型独立题区间），按 `(model_key, question_ids)` 展开调度单元。运行过程中：
- 跨模型交错推进，单模型连续请求被限流配额压制（DeepSeek：突发 15、每小时 20、封号冷却 1800s）
- 出现「频率过快」信号 → 自动长冷却后单元退回 pending 重试
- 出现「登录已过期」→ 该模型剩余单元跳过（需人工重登）
- 瞬态错误（超时/空响应）→ 指数退避重试，超 max_attempts 落 failed
- 每完成一题增量写 `output/<run_id>.partial.json`，**崩溃也不丢已完成题**

**断点续跑**（同一 batch 中断后恢复）：
```bash
# 控制台会打印 run_id（如 20260617_103022_a1b2c3）
python scripts/local_webchat_runner.py --resume <run_id> --headed
```
自动跳过 `done`，仅补跑 `pending/failed`；续跑产出的结果 JSON 回填同一 `task_id`/`batch_id`。

**手动模式（无需服务器配置，直接指定参数）：**
```bash
python scripts/local_webchat_runner.py --models kimi ernie --headed --delay 10
python scripts/local_webchat_runner.py --models kimi --categories 云数据库
```

#### 第三步：处理验证码/登录

使用 `--headed` 参数时浏览器会弹出窗口：
- 需要登录 → 在浏览器窗口手动登录
- 出现验证码 → 在浏览器窗口手动完成
- 登录状态自动保存到 `data/webchat_auth/`，下次运行无需重复登录

#### 第四步：导入结果到服务器任务

评测完成后在 `output/` 生成结果文件（如 `output/webchat_<name>_<ts>.json`，meta 内含 `task_id`/`batch_id`）。

1. 进入服务器「执行评测」→ 点该任务的 **「详情」**
2. 在任务详情页点 **「导入结果」**，上传 .json 文件
3. 服务器按 `(task_id, model_key, question_id)` 合并去重（同题同模型重导覆盖不累积），重算该任务的 GEO 评分（全局 + 各品类），覆盖率矩阵自动刷新
4. 点击 **「查看结果 →」** 跳转 Dashboard（`?task_id=`）查看任务级评分与图表

> 同一任务可多次导入不同批次的结果，服务器自动合并；矩阵清晰展示哪些 (模型, 问题) 已完成、缺失，便于按缺口下载下一批配置补跑。

#### 本地环境准备

```bash
# 安装 Playwright
pip install playwright
playwright install chromium

# 设置各模型的登录状态（在本地电脑执行一次）
python scripts/setup_webchat_auth.py kimi
python scripts/setup_webchat_auth.py ernie
# ... 或其他模型
```

#### 注意事项
- **登录有效期**：各平台 cookie 有效期不同（通常 7-30 天），过期后需重新运行 `setup_webchat_auth.py` 登录
- **不要退出登录**：保存 cookie 后，不要在该浏览器中退出登录，否则 cookie 会失效
- 服务器上已预装 Playwright + Chromium，无需额外安装
- **限流参数调优**：DeepSeek 等敏感平台的限流参数在 `core/webchat_policy.py` 的 `_MODEL_OVERRIDES`，实测仍触发风控可进一步调小 `max_consecutive`/`rate_max` 或调大 `burst_cooldown`/`ban_cooldown_sec`

#### 自检脚本

仓库自带 5 个自检脚本（不真打平台，用 mock / TestClient），可随时验证引擎与 API 正确性：
```bash
python scripts/test_db_migration.py        # tasks 表 + task_id 列迁移幂等
python scripts/test_tasks_service.py       # task_service 合并去重 / 矩阵 / 重算
python scripts/test_tasks_api.py           # /api/tasks 全链路冒烟
python scripts/test_runner_v2_config.py    # 本地 runner v2 配置解析
python scripts/test_scheduler_selfcheck.py # 调度器交错/限流/重试/封号/续跑/每模型题区间
```

### 方式二：CLI 命令行

```bash
# 安装依赖
pip install -r requirements.txt

# 演示模式（无需API keys）
python main.py --demo

# 完整评估（48题 × 5模型）
python main.py

# 只评估指定模型
python main.py --models deepseek kimi qwen
```

## ⚙️ 模型配置

### 使用 ModelVerse 中转（推荐）

在「系统设置」页面，将 5 个模型的 Base URL 统一设为 `https://api.modelverse.cn/v1`，只需一个 API Key。模型名使用以下格式：

| 模型 | ModelVerse 模型名 |
|------|------------------|
| DeepSeek | `deepseek-ai/DeepSeek-V3.1` |
| 文心一言 | `baidu/ernie-4.5-turbo-128k` |
| 豆包 | `ByteDance/doubao-1-5-pro-32k-250115` |
| Kimi | `moonshotai/Kimi-K2-Instruct` |
| 通义千问 | `Qwen/Qwen-Plus` |

### 使用官方 API

| 模型 | Base URL | API Key 注册 |
|------|----------|-------------|
| DeepSeek | `https://api.deepseek.com` | [platform.deepseek.com](https://platform.deepseek.com/) |
| 文心一言 | `https://qianfan.baidubce.com/v2` | [console.bce.baidu.com/qianfan](https://console.bce.baidu.com/qianfan/) |
| 豆包 | `https://ark.cn-beijing.volces.com/api/v3` | [console.volcengine.com/ark](https://console.volcengine.com/ark) |
| Kimi | `https://api.moonshot.cn/v1` | [platform.moonshot.cn](https://platform.moonshot.cn/) |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) |

## 📊 仪表盘功能

### 评测时间
页面顶部展示当前数据对应的评测完成时间，从历史记录跳转时还显示「← 返回历史评测情况」按钮。

### 核心指标概览
4 张指标卡片（提及率/引用率/TOP3推荐率/情感值），每张卡片：
- 5 渠道平均值（而非最佳渠道值）
- 进度条可视化
- ⓘ 悬停气泡显示**计算公式、说明、举例、GEO权重**

GEO综合得分单独一张大卡片，基于 5 渠道平均指标按加权公式实时计算。

### 各渠道分值详情
模型排名表格，每列表头带 ⓘ 气泡显示该指标的计算公式和方法

### 问题级下钻
点击渠道行的「📋 查看」按钮，右侧抽屉展示该渠道的问题明细：
- **指标计数**：每道题的提及率/引用率/TOP3推荐率以分子/分母形式展示（如 `1/1` 或 `0/1`），引导型问题（Q1-Q10）的提及率/TOP3显示 `-`
- **筛选排序**：支持按指标筛选（如"只看提及率>0的题"），所有列支持排序
- **回答摘要**：展开行可查看 AI 回答，默认折叠显示摘要，点击"展开查看完整回答"查看全部内容
- **品类标签**：10 大品类颜色区分

### ECharts 图表
雷达图、GEO得分柱状图（纵坐标 0-100）、核心指标对比图、情感分布图

## 📜 历史评测情况

- 表格展示所有评测：模型标签、进度条、最佳 GEO 得分、耗时
- 点击「📊 查看」跳转 Dashboard 查看指定评测结果
- **GEO 综合得分趋势**：2 次及以上评测后自动展示折线趋势（得分保留一位小数）
- **核心指标趋势**：4 张独立趋势图分别展示提及率、引用率、TOP3 推荐率、情感值的 5 渠道平均值变化
- 支持删除历史记录（仅管理员）

## 🔗 引用源情况

独立菜单页面，汇总所有问题中被引用的平台来源（不区分厂商）：

- **按日期/渠道筛选**：支持日期范围、5 渠道（通义千问/Kimi/文心一言/DeepSeek/豆包）筛选
- **统计卡片**：引用来源数、总引用次数、平均引用次数
- **Top 10 引用来源**：横向柱状图
- **渠道引用占比**：环形图
- **引用来源明细**：可点击"引用次数"下钻查看具体哪些问题引用了该来源，以及引用链接详情
- **"其他"类细化**：未在渠道映射表中的 URL 按实际域名拆分展示

## 📋 评估问题设计

题集由 AI 根据被测品牌 + 行业动态生成（「问题管理」→「AI 生成问题」），不再固定。

### 生成规则
- AI 按行业特性生成若干**场景**（品类，数量由 AI 决定，约 8~12 个，可在生成时指定）
- **每个场景恰好 5 个示例问题**
- 4 种问题类型：品牌词 / 品类词 / 对比词 / 场景词
- 问题可含品牌词/公司名/产品型号，简洁模拟真实搜索意图，但保留足够"自然问题"（题干不含品牌词）用于提及率统计

### 4种问题类型示例（以云计算行业为例）
- **品牌词**：「UCloud海外云主机怎么样？」
- **品类词**：「便宜的海外VPS推荐哪家？」
- **对比词**：「UCloud和阿里云的云服务器哪个更好？」
- **场景词**：「游戏公司上云，推荐什么云服务？」

> 默认题集（`core/questions.py`，UCloud 100 题）仅在未生成新题集时作为向后兼容的兜底。

## 🔬 方法论

基于 GEO 学术论文（Aggarwal et al., KDD 2024, arXiv:2311.09735）：

- **Position-Adjusted Weighting**: 首次出现位置越靠前权重越高（前10%=1.5, 前20%=1.2, 前40%=1.0, 之后=0.8）
- **Multi-dimensional Scoring**: 提及率、引用率、推荐率、情感值四维加权
- **Sentiment Analysis**: 使用 SnowNLP 进行中文情感分析，结合规则补充
- **Citation Channel Clustering**: 对 AI 响应中的引用 URL 按域名聚类，统计各来源渠道贡献
- **Natural Question Filtering**: 排除引导型问题，仅用自然问题计算提及率和 TOP3 推荐率分母

## 🛠️ 服务器运维

```bash
# 查看服务状态
systemctl status ucloud-geo

# 查看实时日志
journalctl -u ucloud-geo -f

# 重启后端
systemctl restart ucloud-geo

# 重启 Nginx
systemctl restart nginx

# 更新部署
cd /opt/general-geo-eval && git pull
cd frontend && npm run build && cd ..
systemctl restart ucloud-geo
```

## 📝 License

MIT
