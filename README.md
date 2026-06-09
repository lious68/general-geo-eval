# UCloud GEO 评估系统

> 类似 [geo.timus.cn](https://geo.timus.cn/) 的 GEO（Generative Engine Optimization）评分体系，评估 UCloud 在五大 AI 模型中的品牌可见度。

## 🎯 核心指标

| 指标 | 说明 | 计算公式 | 权重 |
|------|------|---------|------|
| **提及率** | UCloud 被提及的自然问题响应比例 | UCloud 被提及的自然有效响应数 / 自然有效响应总数 | 45% |
| **引用率** | 包含 UCloud 有效引用的响应比例 | 含 UCloud 官方引用或相关第三方来源引用的响应数 / 全部有效响应总数 | 25% |
| **TOP3推荐率** | UCloud 进入前三推荐位的自然问题响应比例 | UCloud 进入 TOP3 推荐的自然响应数 / 自然有效响应总数 | 20% |
| **情感值** | 全部有效响应的平均情感倾向 | Σ(全部有效响应的情感分数) / 全部有效响应总数 | 10% |
| **GEO综合得分** | 四指标加权求和 (0-100) | (提及率×45% + 引用率×25% + TOP3推荐率×20% + 情感值×10%) × 100 | — |

> **自然问题**：排除引导型问题（Q1-Q10）及题干自带 UCloud/优刻得 字眼的问题。提及率、TOP3推荐率仅统计自然问题；引用率、情感值统计全部有效问题。

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
│  ├─ 鉴权中间件 (JWT Token)                       │
│  ├─ 评测管理 (创建/执行/删除)                     │
│  ├─ 结果查询 (评分/详情/图表/引用/下钻)            │
│  ├─ 引用源统计 (全量来源聚类/下钻)                │
│  ├─ 问题管理 (CRUD)                              │
│  └─ 系统设置 (API Key/模型配置)                   │
├───────────────────────────────────────────────────┤
│  SQLite 数据库 (data/geo.db)                      │
├───────────────────────────────────────────────────┤
│  Core 评估引擎                                    │
│  ├─ model_clients.py  → 5大模型API (OpenAI兼容)   │
│  ├─ analyzer.py       → 响应分析 (提及/引用/推荐)  │
│  ├─ metrics.py        → GEO指标计算               │
│  └─ config.py         → 品牌关键词/评分参数/URL渠道 │
└───────────────────────────────────────────────────┘
```

## 📁 项目结构

```
ucloud-geo-eval/
├── core/                        # 核心评估引擎
│   ├── config.py                # 模型配置、品牌关键词、评分参数、URL渠道映射
│   ├── questions.py             # 48题评估问题集（10品类×5类型）
│   ├── model_clients.py         # AI模型API客户端（OpenAI兼容）
│   ├── analyzer.py              # 响应分析器（提及/引用/推荐/情感/全URL检测）
│   ├── metrics.py               # GEO指标计算引擎
│   ├── report.py                # 报告生成器（HTML/Excel）
│   ├── web_chat_clients.py      # WebChat浏览器自动化客户端（5模型Playwright）
│   ├── web_chat_auth.py         # WebChat认证状态管理
│   └── main.py                  # CLI 主执行脚本
│
├── backend/                     # Web 后端 (FastAPI)
│   ├── app.py                   # FastAPI 入口 + 鉴权中间件
│   ├── database.py              # SQLite 异步数据库 + 迁移 + 动态指标重算
│   ├── models.py                # Pydantic 数据模型
│   ├── routers/
│   │   ├── auth.py              # 登录鉴权
│   │   ├── evaluations.py       # 评测管理 + WebSocket 进度 + 任务配置导出
│   │   ├── results.py           # 结果查询 / 引用详情 / 引用源统计 / 下钻
│   │   ├── questions.py         # 问题管理
│   │   ├── settings.py          # 系统设置
│   │   └── webchat.py           # WebChat认证状态上传/验证
│   └── services/
│       ├── eval_runner.py       # 异步评测执行器
│       └── chart_builder.py     # ECharts 图表 JSON 构建
│
├── frontend/                    # Web 前端 (Vue 3)
│   └── src/
│       ├── views/
│       │   ├── Dashboard.vue       # 📊 GEO 仪表盘
│       │   ├── Evaluation.vue      # 🚀 执行评测（支持API/导入本地结果）
│       │   ├── History.vue         # 📜 历史评测情况
│       │   ├── CitationSources.vue # 🔗 引用源情况
│       │   ├── Questions.vue       # 📝 问题管理
│       │   ├── Settings.vue        # ⚙️ 系统设置
│       │   └── Login.vue           # 🔐 登录
│       ├── stores/
│       │   └── evalProgress.js     # 评测进度全局状态（跨页面可见）
│       └── composables/
│           └── useWebSocket.js     # API 请求 + WebSocket
│
├── scripts/                     # 工具脚本
│   ├── setup_webchat_auth.py    # WebChat 登录态设置脚本（本地运行）
│   ├── local_webchat_runner.py  # 本地 Playwright WebChat 评测 runner
│   ├── webchat_run.py           # WebChat 交互式一键启动（Win/Mac通用）
│   ├── run_webchat.bat          # Windows 快捷启动脚本
│   ├── webchat_interactive_helper.py  # VNC 远程反爬验证辅助
│   └── inspect_chat_dom.py      # 聊天页面 DOM 检查工具
│
├── docs/
│   └── webchat_local_guide.md   # WebChat 本地评测详细使用指南
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
git clone https://github.com/lious68/ucloud-geo-eval.git
cd ucloud-geo-eval

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
git clone https://github.com/lious68/ucloud-geo-eval.git
cd ucloud-geo-eval

# 2. 一键部署
bash deploy.sh
```

部署完成后访问 `http://<服务器IP>/`，首次使用设置管理密码，然后在「系统设置」页面配置 API Key。

### WebChat 联网搜索评测（云 + 本地联动模式）

除了 API 模式评测（调用模型 API），系统还支持 **WebChat 模式**——通过 Playwright 浏览器自动化，模拟真实用户在各 AI 模型官网的聊天交互，获取带联网搜索引用的完整响应。

**为什么需要云+本地联动？**
- **API 模式**（服务器上直接跑）：适用于有 API Key 且支持联网搜索的模型
- **WebChat 模式**（本地电脑跑）：适用于 API 无法调通或需要浏览器交互处理验证码的模型

> **核心思路**：服务器前端选择评测配置 → 下载任务配置 JSON → 本地电脑运行 Playwright 浏览器自动化 → 生成的结果文件上传回服务器 → Dashboard 查看

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
┌────────────────────── 服务器 (Linux) ──────────────────────┐
│                                                              │
│  Evaluation.vue 前端                                         │
│  ├─ API 模式 → 直接调用模型 API + 联网搜索                    │
│  └─ WebChat 模式 → 下载任务配置 ↓                            │
│                                                              │
│                                     ┌─ 导入结果 ← 本地 .json  │
│                                     └─ Dashboard 展示结果      │
└──────────────────────────────────────────────────────────────┘
                               │
                     下载 task_config.json
                               │
                               ▼
┌───────────────────── 本地电脑 (Win10 / Mac) ───────────────┐
│                                                              │
│  python scripts/local_webchat_runner.py                      │
│    --config task_config.json --headed                        │
│                                                              │
│  → 弹出浏览器窗口（人可手动处理验证码/登录）                   │
│  → 自动提问 → 等待回复 → 分析 → 评分                         │
│  → 输出: output/webchat_评测_20260608_143022.json           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                               │
                     上传 .json 到服务器前端
                               │
                               ▼
                     服务器导入 → Dashboard 展示
```

#### 第一步：在服务器上下载任务配置

1. 登录服务器前端 → 「执行评测」页面
2. 选择 **「🌐 WebChat 模式」**
3. 勾选要评测的模型（需显示 **「✓ 已登录」**）
4. 选择品类筛选（可选）
5. 调整请求间隔（建议 8 秒以上）
6. 点击 **「下载任务配置（在本地电脑运行）」** → 浏览器下载 `webchat_task_XXX.json`

#### 第二步：在本地电脑上运行评测

将 `webchat_task_XXX.json` 传到本地电脑后，有三种运行方式：

**方式 A：从任务配置运行（推荐，云联动）**

```bash
# 显示浏览器窗口（可手动处理验证码/登录）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json --headed

# 后台运行（不显示窗口）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json
```

**方式 B：交互式引导（新手友好）**

```bash
# 进入交互式配置引导
python scripts/webchat_run.py
```

**方式 C：手动指定参数**

```bash
python scripts/local_webchat_runner.py --models kimi ernie --headed --delay 10
python scripts/local_webchat_runner.py --models kimi --categories 云数据库
```

**Windows 快捷启动：**
```powershell
scripts\run_webchat.bat                # 交互式引导
scripts\run_webchat.bat kimi headed    # 指定模型 + 显示浏览器
scripts\run_webchat.bat config task.json  # 从配置文件运行
```

**Mac/Linux 快捷启动：**
```bash
python scripts/webchat_run.py                    # 交互式
python scripts/webchat_run.py --config task.json  # 从配置
python scripts/webchat_run.py --models kimi ernie  # 手动指定
```

#### 第三步：处理验证码/登录

使用 `--headed` 参数时，浏览器会弹出窗口。运行过程中：
- 如果需要登录 → 在浏览器窗口中手动登录
- 如果出现验证码 → 在浏览器窗口中手动完成验证
- 登录状态会自动保存到 `data/webchat_auth/`，下次运行无需重复登录

#### 第四步：上传结果到服务器

评测完成后，会在 `output/` 目录生成结果文件（如 `output/webchat_评测_20260608_143022.json`）。

1. 将此文件传到服务器
2. 在服务器前端「执行评测」页面，找到 **「导入本地 WebChat 结果」** 区域
3. 拖拽或点击上传 .json 文件
4. 导入成功后，点击 **「查看结果 →」** 跳转到 Dashboard

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
- **GEO 综合得分趋势**：2 次及以上评测后自动展示折线趋势
- **核心指标趋势**：4 张独立趋势图分别展示提及率、引用率、TOP3 推荐率、情感值的 5 渠道平均值变化
- 支持删除历史记录

## 🔗 引用源情况

独立菜单页面，汇总所有问题中被引用的平台来源（不区分厂商）：

- **按日期/渠道筛选**：支持日期范围、5 渠道（通义千问/Kimi/文心一言/DeepSeek/豆包）筛选
- **统计卡片**：引用来源数、总引用次数、平均引用次数
- **Top 10 引用来源**：横向柱状图
- **渠道引用占比**：环形图
- **引用来源明细**：可点击"引用次数"下钻查看具体哪些问题引用了该来源，以及引用链接详情
- **"其他"类细化**：未在渠道映射表中的 URL 按实际域名拆分展示

## 📋 评估问题设计

### 10大品类
云计算、云存储、云数据库、CDN、AI服务、安全服务、大数据、容器/K8s、行业方案、性价比

### 5种问题类型
- **直接推荐型**：「推荐一个好用的国内云服务器」
- **对比型**：「UCloud和阿里云的云服务器哪个更好？」
- **技术选型型**：「高并发场景下，选择什么云数据库方案？」
- **场景型**：「游戏公司上云，推荐什么云服务？」
- **评测型**：「2025年国内主流云服务商对比评测」

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
cd /opt/ucloud-geo-eval && git pull
cd frontend && npm run build && cd ..
systemctl restart ucloud-geo
```

## 📝 License

MIT