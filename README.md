# UCloud GEO 评估框架

> 类似 [geo.timus.cn](https://geo.timus.cn/) 的 GEO（Generative Engine Optimization）评分体系，用于评估 UCloud 在各大 AI 模型中的品牌可见度。

## 🎯 核心指标

| 指标 | 说明 | 计算方式 |
|------|------|---------|
| **覆盖率** | UCloud 被提及的问题比例 | 提及UCloud的问题数 / 总问题数 |
| **提及率** | 平均每条响应中UCloud提及次数（含位置权重） | Σ(提及次数×位置权重) / 总问题数 |
| **引用率** | 包含UCloud引用/链接的响应比例 | 含引用响应数 / 总问题数 |
| **推荐率** | UCloud 被推荐的响应比例 | 被推荐响应数 / 总问题数 |
| **情感值** | UCloud 提及时的平均情感倾向 | 平均 SnowNLP 情感分数 (0-1) |
| **GEO综合得分** | 五指标加权求和 (0-100) | 覆盖率×25% + 提及率×15% + 引用率×15% + 推荐率×25% + 情感值×20% |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Keys

```bash
cp .env.example .env
# 编辑 .env 填入你的 API keys
```

| 模型 | API Key 注册 | 价格（元/百万tokens） |
|------|-------------|---------------------|
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com/) | 输入 1 / 输出 2 |
| 文心一言 | [console.bce.baidu.com/qianfan](https://console.bce.baidu.com/qianfan/) | 输入 120 / 输出 120 |
| 豆包 | [console.volcengine.com/ark](https://console.volcengine.com/ark) | 输入 0.8 / 输出 2 |
| Kimi | [platform.moonshot.cn](https://platform.moonshot.cn/) | 输入 12 / 输出 12 |
| 通义千问 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) | 输入 4 / 输出 12 |

> 💡 推荐先注册 DeepSeek（最便宜）和 Kimi（注册送额度）测试

### 3. 运行评估

```bash
# 演示模式（无需API keys，使用模拟数据）
python main.py --demo

# 快速评估（前10题，用于测试API连接）
python main.py --quick

# 完整评估（48题 × 5模型）
python main.py

# 只评估指定模型
python main.py --models deepseek kimi qwen

# 调整API请求间隔（避免限频）
python main.py --delay 2.0
```

## 📁 项目结构

```
ucloud-geo-eval/
├── config.py           # 配置文件（模型、关键词、评分参数）
├── questions.py        # 评估问题集（48题，10品类，5类型）
├── model_clients.py    # AI模型API客户端（OpenAI兼容）
├── analyzer.py         # 响应分析器（提及/引用/推荐/情感）
├── metrics.py          # GEO指标计算引擎
├── report.py           # 报告生成器（HTML/Excel/图表）
├── main.py             # 主执行脚本
├── web_eval.py         # Web快速评估模式
├── .env.example        # API Key 模板
├── requirements.txt    # Python 依赖
└── output/             # 评估输出
    ├── raw_responses/  # 原始API响应JSON
    ├── reports/        # HTML报告 + Excel数据
    └── charts/         # 可视化图表
```

## 📋 评估问题设计

### 10大品类
云计算、云存储、云数据库、CDN、AI服务、安全服务、大数据、容器/K8s、行业方案、性价比

### 5种问题类型
- **直接推荐型**：「推荐一个好用的国内云服务器」
- **对比型**：「UCloud和阿里云的云服务器哪个更好？」
- **技术选型型**：「高并发场景下，选择什么云数据库方案？」
- **场景型**：「游戏公司上云，推荐什么云服务？」
- **评测型**：「2025年国内主流云服务商对比评测」

## 📊 输出示例

### 终端输出
```
排名    模型        GEO得分  覆盖率   提及率  引用率   推荐率   情感值  平均排名
🥇    通义千问     41.8    58.3%   2.04   8.3%    12.5%   0.63   3.3
🥈    DeepSeek    39.6    60.4%   1.85   6.2%    10.4%   0.58   2.2
🥉    豆包        34.3    43.8%   1.55   6.2%    10.4%   0.60   3.8
 #4   Kimi        33.9    45.8%   1.80   2.1%    8.3%    0.55   3.5
 #5   文心一言     33.0    45.8%   1.43   0.0%    8.3%    0.62   3.3
```

### 生成的报告文件
- `geo_report.html` - 可视化HTML报告
- `geo_data.xlsx` - Excel数据表（模型对比/详细数据/品类分析）
- `geo_scores.png` - GEO综合得分柱状图
- `radar_chart.png` - 多维度雷达图
- `coverage_comparison.png` - 核心指标对比图
- `sentiment_distribution.png` - 情感分布图

## 🔬 方法论

基于 GEO 学术论文（Aggarwal et al., KDD 2024, arXiv:2311.09735）：

- **Position-Adjusted Weighting**: 首次出现位置越靠前权重越高，使用指数衰减函数
- **Multi-dimensional Scoring**: 覆盖率、提及率、引用率、推荐率、情感值五维加权
- **Sentiment Analysis**: 使用 SnowNLP 进行中文情感分析，结合规则补充

## ⚙️ 豆包模型特殊配置

豆包（Doubao）使用火山引擎 Ark 平台的「推理接入点」模式，需要在 `config.py` 中将 `model` 替换为你在 Ark 控制台创建的 endpoint ID：

```python
"doubao": {
    "model": "ep-xxxxxxxx",  # 替换为你的 endpoint ID
    ...
}
```

## 📝 License

MIT
