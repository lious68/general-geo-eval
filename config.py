"""
UCloud GEO 评估框架 - 配置文件
包含模型配置、品牌关键词、评分参数等
基于五大模型API调研结果和UCloud产品线研究
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 品牌关键词配置（基于UCloud产品线研究）
# ============================================================
BRAND_KEYWORDS = {
    "primary": [
        "UCloud", "ucloud", "优刻得", "优刻得科技",
        "优刻得科技股份有限公司", "688158",
    ],
    "products": [
        # 计算
        "UHost", "uhost", "UPHost", "uphost", "ULightHost",
        "快杰", "快杰型",
        # 存储
        "US3", "us3", "UFile", "ufile", "UDisk", "udisk",
        "UFS", "UPFS", "UDataArk", "数据方舟",
        # 数据库
        "UDB", "udb", "UMem", "umem",
        # 网络
        "UVPC", "uvpc", "ULB", "ulb", "UDPN", "udpn",
        "EIP", "UDNS", "UGN", "UWAN",
        # CDN/边缘
        "UCDN", "ucdn", "UEC", "UEDN",
        # 容器
        "UK8S", "uk8s",
        # 安全
        "UWAF", "uwaf", "UDDoS", "UHIDS",
        "SafeHouse", "安全屋",
        # 大数据
        "UHadoop", "UKafka",
        # 监控
        "CloudWatch", "天镜",
        # 混合云
        "UHybrid", "UCloudStack", "UXC", "信创云",
        # 通信
        "USMS", "UVMS",
    ],
    "flagship": [
        # 旗舰产品/差异化产品
        "PathX", "pathx", "全球加速", "全球动态加速",
        "安全屋", "数据沙箱",
        "星图", "Astraflow",
        "UModelVerse",
        "OpenClaw",
        "FinClaw",
        "优智推理",
        "一云多芯",
        "中立云",
    ],
    "aliases": [
        "UCloud优刻得", "ucloud优刻得",
        "UCloud云", "优刻得云",
        "UCloudStack", "ucloudstack",
    ]
}

# 竞品关键词（用于对比分析）
COMPETITOR_KEYWORDS = {
    "alibaba": ["阿里云", "Alibaba Cloud", "阿里云ECS", "阿里云OSS", "飞天", "Apsara", "通义千问"],
    "tencent": ["腾讯云", "Tencent Cloud", "腾讯云CVM", "腾讯云COS", "混元"],
    "huawei": ["华为云", "Huawei Cloud", "华为云ECS", "华为云OBS", "盘古"],
    "baidu_cloud": ["百度云", "百度智能云", "百度云BCC", "文心"],
    "aws": ["AWS", "亚马逊云", "Amazon Web Services", "亚马逊AWS"],
    "azure": ["Azure", "微软云", "Microsoft Azure"],
    "gcp": ["GCP", "Google Cloud", "谷歌云"],
}

# ============================================================
# 模型配置（基于API调研 - 全部支持OpenAI兼容格式）
# ============================================================
MODELS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",           # 也可用 deepseek-v4-flash / deepseek-v4-pro
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
        "pricing": {"input": 1, "output": 2},  # 元/百万tokens
    },
    "ernie": {
        "name": "文心一言",
        "base_url": "https://qianfan.baidubce.com/v2",  # OpenAI兼容端点
        "model": "ernie-4.0-8k",
        "api_key_env": "ERNIE_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
        "pricing": {"input": 120, "output": 120},
        "note": "也可使用百度原生API: aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop",
    },
    "doubao": {
        "name": "豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",           # 实际使用时替换为 endpoint ID: ep-xxxxxxxx
        "api_key_env": "DOUBAO_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
        "pricing": {"input": 0.8, "output": 2},
        "note": "model 参数需替换为火山引擎 Ark 控制台创建的推理接入点 ID (ep-xxxxxxxx)",
    },
    "kimi": {
        "name": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",            # 也可用 kimi-k2.6
        "api_key_env": "KIMI_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
        "pricing": {"input": 12, "output": 12},
    },
    "qwen": {
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",                 # 也可用 qwen3.7-max / qwen3.6-flash
        "api_key_env": "QWEN_API_KEY",
        "max_tokens": 2048,
        "temperature": 0.7,
        "pricing": {"input": 4, "output": 12},
    },
}

# ============================================================
# GEO 评分参数（基于 GEO 学术论文 Aggarwal et al., KDD 2024）
# ============================================================
SCORE_CONFIG = {
    # 情感分析阈值
    "sentiment": {
        "positive_threshold": 0.6,    # > 0.6 视为正面
        "negative_threshold": 0.4,    # < 0.4 视为负面
        "positive_weight": 1.0,
        "neutral_weight": 0.5,
        "negative_weight": -0.5,
    },
    # 推荐判定关键词
    "recommendation": {
        "strong_keywords": [
            "强烈推荐", "首选", "最佳选择", "最推荐",
            "首推", "强烈建议", "第一选择", "不二之选",
            "极力推荐", "强烈推荐使用", "最优选",
        ],
        "moderate_keywords": [
            "推荐", "建议", "可以考虑", "值得选择",
            "不错的选择", "也是一个好选择", "值得关注",
            "可以考虑使用", "值得推荐", "值得一试",
            "也是不错的选择", "可以考虑的",
        ],
        "comparison_win_keywords": [
            "优于", "比...好", "更具优势", "更胜一筹",
            "性价比更高", "更值得", "更有竞争力",
            "表现更好", "更有优势", "更适合",
        ],
    },
    # 引用判定规则
    "citation": {
        "url_patterns": [
            r"https?://(www\.)?ucloud\.cn",
            r"https?://(www\.)?ucloud\.com",
            r"https?://(www\.)?ucloudstack\.com",
        ],
        "reference_keywords": [
            "据UCloud", "UCloud官网", "UCloud数据显示",
            "根据UCloud", "UCloud报告", "UCloud官方",
            "UCloud数据显示", "UCloud白皮书",
        ],
    },
    # 位置权重（首次出现位置越靠前权重越高）
    # 基于 GEO 论文 Position-Adjusted Word Count: Imp_pwc = Σ|s|·e^(-pos/|S|)
    "position_weight": {
        "top_10_percent": 1.5,    # 前10%位置提及
        "top_20_percent": 1.2,    # 前20%位置提及
        "top_40_percent": 1.0,    # 前40%位置提及
        "beyond_40_percent": 0.8, # 40%之后提及
    },
    # GEO综合分数权重
    "geo_weights": {
        "coverage_rate": 0.45,
        "mention_rate": 0.0,
        "citation_rate": 0.25,
        "recommendation_rate": 0.20,
        "sentiment_score": 0.10,
    },
}

# ============================================================
# 输出配置
# ============================================================
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
RAW_RESPONSES_DIR = os.path.join(OUTPUT_DIR, "raw_responses")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")

# 确保目录存在
for d in [OUTPUT_DIR, RAW_RESPONSES_DIR, REPORTS_DIR, CHARTS_DIR]:
    os.makedirs(d, exist_ok=True)
