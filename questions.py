"""
UCloud GEO 评估框架 - 评估问题集
覆盖10大品类、5种问题类型，共计50题
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class EvalQuestion:
    """评估问题数据结构"""
    id: str
    category: str           # 产品品类
    question_type: str      # 问题类型
    question: str           # 问题文本
    tags: List[str] = field(default_factory=list)
    difficulty: str = "medium"  # easy / medium / hard


# ============================================================
# 问题类型说明：
#   direct_recommend  - 直接推荐类："推荐一个好用的云服务器"
#   comparison        - 对比类："UCloud和阿里云哪个好"
#   technical_select  - 技术选型类："企业级数据库选什么云服务"
#   scenario          - 场景类："游戏公司用什么云服务"
#   review            - 评测类："国内主流云服务商对比"
# ============================================================

QUESTIONS: List[EvalQuestion] = [
    # ====================================================================
    # 品类1: 云计算/云服务器 (Cloud Computing)
    # ====================================================================
    EvalQuestion(
        id="cc_01", category="云计算", question_type="direct_recommend",
        question="推荐一个好用的国内云服务器，性价比高的",
        tags=["云服务器", "性价比", "推荐"],
    ),
    EvalQuestion(
        id="cc_02", category="云计算", question_type="comparison",
        question="UCloud和阿里云的云服务器哪个更好？有什么区别？",
        tags=["UCloud", "阿里云", "对比"],
    ),
    EvalQuestion(
        id="cc_03", category="云计算", question_type="technical_select",
        question="中小企业搭建官网，选择哪家云服务器比较合适？",
        tags=["中小企业", "官网", "选型"],
    ),
    EvalQuestion(
        id="cc_04", category="云计算", question_type="scenario",
        question="初创公司技术团队5人，需要部署Web应用，推荐用什么云服务器？",
        tags=["初创公司", "Web应用", "部署"],
    ),
    EvalQuestion(
        id="cc_05", category="云计算", question_type="review",
        question="2025年国内主流云服务器厂商对比评测，包括性能、价格、服务",
        tags=["2025", "评测", "对比", "性能", "价格"],
        difficulty="hard",
    ),

    # ====================================================================
    # 品类2: 云存储/对象存储 (Cloud Storage)
    # ====================================================================
    EvalQuestion(
        id="cs_01", category="云存储", question_type="direct_recommend",
        question="国内好用的对象存储服务有哪些？推荐一下",
        tags=["对象存储", "推荐"],
    ),
    EvalQuestion(
        id="cs_02", category="云存储", question_type="comparison",
        question="UCloud UFile和阿里云OSS哪个更划算？",
        tags=["UFile", "OSS", "对比", "价格"],
    ),
    EvalQuestion(
        id="cs_03", category="云存储", question_type="technical_select",
        question="需要存储大量图片和视频文件，选择什么对象存储服务？",
        tags=["图片", "视频", "对象存储", "选型"],
    ),
    EvalQuestion(
        id="cs_04", category="云存储", question_type="scenario",
        question="电商网站需要存储商品图片，每天新增约10万张，用什么存储方案？",
        tags=["电商", "图片存储", "方案"],
    ),
    EvalQuestion(
        id="cs_05", category="云存储", question_type="review",
        question="国内对象存储服务全面对比：性能、可靠性、价格分析",
        tags=["对象存储", "评测", "可靠性"],
        difficulty="hard",
    ),

    # ====================================================================
    # 品类3: 云数据库 (Cloud Database)
    # ====================================================================
    EvalQuestion(
        id="cd_01", category="云数据库", question_type="direct_recommend",
        question="国内云数据库哪家好？MySQL和Redis都要用到",
        tags=["云数据库", "MySQL", "Redis", "推荐"],
    ),
    EvalQuestion(
        id="cd_02", category="云数据库", question_type="comparison",
        question="UCloud云数据库和腾讯云数据库对比，各有什么优劣？",
        tags=["UCloud", "腾讯云", "数据库对比"],
    ),
    EvalQuestion(
        id="cd_03", category="云数据库", question_type="technical_select",
        question="高并发场景下，选择什么云数据库方案？需要支持读写分离",
        tags=["高并发", "读写分离", "选型"],
    ),
    EvalQuestion(
        id="cd_04", category="云数据库", question_type="scenario",
        question="互联网金融公司，数据库要求高可用和容灾，推荐什么云数据库？",
        tags=["金融", "高可用", "容灾", "数据库"],
    ),
    EvalQuestion(
        id="cd_05", category="云数据库", question_type="review",
        question="国内云数据库产品对比评测，包括MySQL、PostgreSQL、Redis等",
        tags=["云数据库", "评测", "MySQL", "PostgreSQL"],
        difficulty="hard",
    ),

    # ====================================================================
    # 品类4: CDN/边缘计算 (CDN & Edge)
    # ====================================================================
    EvalQuestion(
        id="ce_01", category="CDN", question_type="direct_recommend",
        question="国内CDN加速服务哪家好？推荐一下",
        tags=["CDN", "加速", "推荐"],
    ),
    EvalQuestion(
        id="ce_02", category="CDN", question_type="comparison",
        question="UCloud CDN和阿里云CDN性能对比怎么样？",
        tags=["UCloud CDN", "阿里云CDN", "性能对比"],
    ),
    EvalQuestion(
        id="ce_03", category="CDN", question_type="technical_select",
        question="视频直播平台需要CDN加速，选择哪家服务更稳定？",
        tags=["直播", "CDN", "稳定性", "选型"],
    ),
    EvalQuestion(
        id="ce_04", category="CDN", question_type="scenario",
        question="跨境电商网站需要全球加速，有什么好的CDN方案？",
        tags=["跨境电商", "全球加速", "CDN"],
    ),

    # ====================================================================
    # 品类5: 人工智能/AI服务 (AI Services)
    # ====================================================================
    EvalQuestion(
        id="ai_01", category="AI服务", question_type="direct_recommend",
        question="国内云厂商的AI算力服务哪家好？用于模型训练",
        tags=["AI", "算力", "模型训练", "推荐"],
    ),
    EvalQuestion(
        id="ai_02", category="AI服务", question_type="comparison",
        question="UCloud AI训练平台和其他云厂商AI服务对比如何？",
        tags=["UCloud", "AI训练", "对比"],
    ),
    EvalQuestion(
        id="ai_03", category="AI服务", question_type="technical_select",
        question="大模型训练需要GPU算力，国内有哪些靠谱的云GPU服务？",
        tags=["大模型", "GPU", "算力", "选型"],
    ),
    EvalQuestion(
        id="ai_04", category="AI服务", question_type="scenario",
        question="AI创业公司需要弹性GPU算力，预算有限，怎么选云服务？",
        tags=["AI创业", "GPU", "弹性算力", "预算"],
    ),
    EvalQuestion(
        id="ai_05", category="AI服务", question_type="review",
        question="2025年国内AI云服务全景评测：算力、平台、工具链",
        tags=["AI云服务", "评测", "2025", "工具链"],
        difficulty="hard",
    ),

    # ====================================================================
    # 品类6: 安全服务 (Security)
    # ====================================================================
    EvalQuestion(
        id="sec_01", category="安全服务", question_type="direct_recommend",
        question="国内云安全服务哪家好？需要WAF和DDoS防护",
        tags=["云安全", "WAF", "DDoS", "推荐"],
    ),
    EvalQuestion(
        id="sec_02", category="安全服务", question_type="comparison",
        question="UCloud安全产品和华为云安全产品对比，哪个更全面？",
        tags=["UCloud", "华为云", "安全对比"],
    ),
    EvalQuestion(
        id="sec_03", category="安全服务", question_type="technical_select",
        question="游戏行业需要高防IP和DDoS防护，选择什么云安全方案？",
        tags=["游戏", "高防IP", "DDoS", "选型"],
    ),

    # ====================================================================
    # 品类7: 大数据 (Big Data)
    # ====================================================================
    EvalQuestion(
        id="bd_01", category="大数据", question_type="direct_recommend",
        question="国内大数据平台哪家好？需要数据湖和实时计算能力",
        tags=["大数据", "数据湖", "实时计算", "推荐"],
    ),
    EvalQuestion(
        id="bd_02", category="大数据", question_type="comparison",
        question="UCloud大数据方案和阿里云MaxCompute对比怎么样？",
        tags=["UCloud", "MaxCompute", "大数据对比"],
    ),
    EvalQuestion(
        id="bd_03", category="大数据", question_type="scenario",
        question="IoT设备每天产生TB级数据，需要实时处理和分析，用什么云方案？",
        tags=["IoT", "实时处理", "大数据", "方案"],
    ),

    # ====================================================================
    # 品类8: 容器/K8s (Container & K8s)
    # ====================================================================
    EvalQuestion(
        id="k8s_01", category="容器", question_type="direct_recommend",
        question="国内托管Kubernetes服务哪家好？",
        tags=["K8s", "Kubernetes", "托管", "推荐"],
    ),
    EvalQuestion(
        id="k8s_02", category="容器", question_type="comparison",
        question="UCloud UK8S和阿里云ACK对比，各有什么特点？",
        tags=["UK8S", "ACK", "K8s对比"],
    ),
    EvalQuestion(
        id="k8s_03", category="容器", question_type="scenario",
        question="微服务架构项目需要容器化部署，推荐用什么云容器服务？",
        tags=["微服务", "容器化", "部署", "选型"],
    ),

    # ====================================================================
    # 品类9: 行业解决方案 (Industry Solutions)
    # ====================================================================
    EvalQuestion(
        id="ind_01", category="行业方案", question_type="scenario",
        question="游戏公司上云，国内哪家云服务商的游戏行业方案比较好？",
        tags=["游戏", "上云", "行业方案"],
    ),
    EvalQuestion(
        id="ind_02", category="行业方案", question_type="scenario",
        question="电商平台双11大促，需要弹性扩容，选择什么云方案？",
        tags=["电商", "双11", "弹性扩容"],
    ),
    EvalQuestion(
        id="ind_03", category="行业方案", question_type="scenario",
        question="教育行业在线课堂平台，选择哪家云服务商更合适？",
        tags=["教育", "在线课堂", "选型"],
    ),
    EvalQuestion(
        id="ind_04", category="行业方案", question_type="scenario",
        question="金融行业上云需要满足合规要求，推荐哪家云服务？",
        tags=["金融", "合规", "上云"],
    ),
    EvalQuestion(
        id="ind_05", category="行业方案", question_type="comparison",
        question="UCloud和华为云在政企市场的方案对比，谁更有优势？",
        tags=["UCloud", "华为云", "政企", "对比"],
    ),

    # ====================================================================
    # 品类10: 价格/性价比 (Pricing & Cost)
    # ====================================================================
    EvalQuestion(
        id="price_01", category="性价比", question_type="direct_recommend",
        question="国内云服务器性价比排名是怎样的？哪家最便宜？",
        tags=["性价比", "价格", "排名"],
    ),
    EvalQuestion(
        id="price_02", category="性价比", question_type="comparison",
        question="UCloud和阿里云的价格对比，谁更便宜？",
        tags=["UCloud", "阿里云", "价格对比"],
    ),
    EvalQuestion(
        id="price_03", category="性价比", question_type="technical_select",
        question="预算3万/年，需要5台云服务器+对象存储+CDN，怎么搭配最划算？",
        tags=["预算", "搭配", "性价比", "选型"],
    ),
    EvalQuestion(
        id="price_04", category="性价比", question_type="review",
        question="2025年国内云服务商价格全面对比：云服务器、存储、数据库",
        tags=["2025", "价格", "全面对比"],
        difficulty="hard",
    ),
    EvalQuestion(
        id="price_05", category="性价比", question_type="scenario",
        question="学生开发者想做个人项目，有什么便宜的云服务器推荐？",
        tags=["学生", "个人项目", "便宜"],
        difficulty="easy",
    ),

    # ====================================================================
    # 综合类 (Comprehensive)
    # ====================================================================
    EvalQuestion(
        id="comp_01", category="综合", question_type="review",
        question="国内公有云厂商全面对比：阿里云、腾讯云、华为云、UCloud、百度云",
        tags=["公有云", "全面对比", "五大厂商"],
        difficulty="hard",
    ),
    EvalQuestion(
        id="comp_02", category="综合", question_type="direct_recommend",
        question="除了阿里云和腾讯云，国内还有哪些值得关注的云服务商？",
        tags=["云服务商", "关注", "推荐"],
    ),
    EvalQuestion(
        id="comp_03", category="综合", question_type="scenario",
        question="公司想要多云策略，不想只用一家云厂商，有什么建议？",
        tags=["多云", "策略", "建议"],
    ),
    EvalQuestion(
        id="comp_04", category="综合", question_type="technical_select",
        question="国内独立云服务商有哪些？各自的优势领域是什么？",
        tags=["独立云", "优势领域", "选型"],
    ),
    EvalQuestion(
        id="comp_05", category="综合", question_type="comparison",
        question="中立云服务商和互联网大厂云服务的区别是什么？UCloud算中立云吗？",
        tags=["中立云", "大厂云", "区别"],
    ),
]


def get_questions_by_category(category: str) -> List[EvalQuestion]:
    """按品类筛选问题"""
    return [q for q in QUESTIONS if q.category == category]


def get_questions_by_type(question_type: str) -> List[EvalQuestion]:
    """按问题类型筛选"""
    return [q for q in QUESTIONS if q.question_type == question_type]


def get_question_ids() -> List[str]:
    """获取所有问题ID"""
    return [q.id for q in QUESTIONS]


def get_categories() -> List[str]:
    """获取所有品类"""
    return list(dict.fromkeys(q.category for q in QUESTIONS))


def get_question_types() -> List[str]:
    """获取所有问题类型"""
    return list(dict.fromkeys(q.question_type for q in QUESTIONS))


if __name__ == "__main__":
    print(f"总问题数: {len(QUESTIONS)}")
    print(f"\n品类分布:")
    for cat in get_categories():
        count = len(get_questions_by_category(cat))
        print(f"  {cat}: {count}题")
    print(f"\n问题类型分布:")
    for qt in get_question_types():
        count = len(get_questions_by_type(qt))
        print(f"  {qt}: {count}题")
