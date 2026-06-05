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
│   └── main.py                  # CLI 主执行脚本
│
├── backend/                     # Web 后端 (FastAPI)
│   ├── app.py                   # FastAPI 入口 + 鉴权中间件
│   ├── database.py              # SQLite 异步数据库 + 迁移 + 动态指标重算
│   ├── models.py                # Pydantic 数据模型
│   ├── routers/
│   │   ├── auth.py              # 登录鉴权
│   │   ├── evaluations.py       # 评测管理 + WebSocket 进度
│   │   ├── results.py           # 结果查询 / 引用详情 / 引用源统计 / 下钻
│   │   ├── questions.py         # 问题管理
│   │   └─ settings.py          # 系统设置
│   └── services/
│       ├── eval_runner.py       # 异步评测执行器
│       └── chart_builder.py     # ECharts 图表 JSON 构建
│
├── frontend/                    # Web 前端 (Vue 3)
│   └── src/
│       ├── views/
│       │   ├── Dashboard.vue       # 📊 GEO 仪表盘
│       │   ├── Evaluation.vue      # 🚀 执行评测
│       │   ├── History.vue         # 📜 历史评测情况
│       │   ├── CitationSources.vue # 🔗 引用源情况
│       │   ├── Questions.vue       # 📝 问题管理
│       │   ├── Settings.vue        # ⚙️ 系统设置
│       │   └─ Login.vue           # 🔐 登录
│       └── composables/
│           └── useWebSocket.js     # API 请求 + WebSocket
│
├── nginx.conf                   # Nginx 配置
├── deploy.sh                    # 一键部署脚本
├── ucloud-geo.service           # systemd 服务配置
└── DEPLOY.md                    # 部署文档
```

## 🚀 快速开始

### 方式一：Web 系统（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/lious68/ucloud-geo-eval.git
cd ucloud-geo-eval

# 2. 一键部署（服务器上执行）
bash deploy.sh
```

部署完成后访问 `http://<服务器IP>/`，首次使用设置管理密码，然后在「系统设置」页面配置 API Key。

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
- **回答摘要**：展开行可查看 AI 回答摘要
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