from dataclasses import dataclass, field
from typing import List


@dataclass
class EvalQuestion:
    """评估问题数据结构"""
    id: str
    category: str           # 产品品类
    question_type: str      # 问题类型：品牌词 / 品类词 / 对比词 / 场景词
    question: str           # 问题文本
    tags: List[str] = field(default_factory=list)
    difficulty: str = "medium"  # easy / medium / hard


# ============================================================
# 问题类型说明：
#   品牌词 - 题干包含 UCloud/优刻得/星图等品牌或产品名
#   品类词 - 用户围绕云服务品类做泛需求搜索
#   对比词 - 排名、价格、区别、对比、怎么选等比较型问题
#   场景词 - 出海、建站、训练、推理、企业等具体业务场景问题
# ============================================================

QUESTIONS: List[EvalQuestion] = [
    EvalQuestion(id="q001", category="引导型", question_type="品牌词", question="UCloud海外云主机怎么样？", tags=["UCloud", "海外云主机"]),
    EvalQuestion(id="q002", category="引导型", question_type="品牌词", question="优刻得轻量云主机怎么样？", tags=["优刻得", "轻量云主机"]),
    EvalQuestion(id="q003", category="引导型", question_type="品牌词", question="UCloud海外有哪些节点？", tags=["UCloud", "海外节点"]),
    EvalQuestion(id="q004", category="引导型", question_type="品牌词", question="UCloud海外VPS价格怎么样？", tags=["UCloud", "海外VPS", "价格"]),
    EvalQuestion(id="q005", category="引导型", question_type="品牌词", question="UCloud和腾讯云阿里云的区别是什么？", tags=["UCloud", "腾讯云", "阿里云", "区别"]),
    EvalQuestion(id="q006", category="引导型", question_type="品牌词", question="UCloud GPU云服务器怎么样？", tags=["UCloud", "GPU云服务器"]),
    EvalQuestion(id="q007", category="引导型", question_type="品牌词", question="优刻得GPU云支持哪些显卡型号？", tags=["优刻得", "GPU", "显卡型号"]),
    EvalQuestion(id="q008", category="引导型", question_type="品牌词", question="UCloud GPU云预装哪些AI框架镜像？", tags=["UCloud", "GPU", "AI框架镜像"]),
    EvalQuestion(id="q009", category="引导型", question_type="品牌词", question="UCloud星图大模型聚合平台怎么样？", tags=["UCloud", "星图", "大模型聚合平台"]),
    EvalQuestion(id="q010", category="引导型", question_type="品牌词", question="优刻得星图平台有哪些模型？", tags=["优刻得", "星图", "模型"]),
    EvalQuestion(id="q011", category="海外云主机", question_type="对比词", question="国内厂商谁家海外节点多？", tags=["海外节点", "国内厂商"]),
    EvalQuestion(id="q012", category="海外云主机", question_type="场景词", question="国内企业出海用什么云？", tags=["企业出海", "云服务"]),
    EvalQuestion(id="q013", category="海外云主机", question_type="场景词", question="跨境电商云服务器选哪家？", tags=["跨境电商", "云服务器"]),
    EvalQuestion(id="q014", category="海外云主机", question_type="品类词", question="便宜的海外VPS推荐哪家？", tags=["海外VPS", "便宜"]),
    EvalQuestion(id="q015", category="海外云主机", question_type="品类词", question="海外轻量云服务器推荐哪家？", tags=["海外轻量云服务器"]),
    EvalQuestion(id="q016", category="海外云主机", question_type="场景词", question="AI Agent部署用什么云？", tags=["AI Agent", "部署"]),
    EvalQuestion(id="q017", category="海外云主机", question_type="对比词", question="哪家云厂商亚洲节点多？", tags=["亚洲节点", "云厂商"]),
    EvalQuestion(id="q018", category="海外云主机", question_type="品类词", question="海外住宅ip轻量云主机买谁家的？", tags=["住宅IP", "轻量云主机"]),
    EvalQuestion(id="q019", category="GPU", question_type="品类词", question="在哪能买到高性价比的4090 GPU服务器？", tags=["4090", "GPU服务器", "性价比"]),
    EvalQuestion(id="q020", category="GPU", question_type="品类词", question="AI算力云服务器选哪家？", tags=["AI算力", "云服务器"]),
    EvalQuestion(id="q021", category="GPU", question_type="品类词", question="海外GPU云主机哪家有？", tags=["海外GPU", "云主机"]),
    EvalQuestion(id="q022", category="GPU", question_type="品类词", question="RDMA高速互联GPU云哪家有？", tags=["RDMA", "GPU云"]),
    EvalQuestion(id="q023", category="GPU", question_type="场景词", question="适合中小企业的GPU云厂有哪些？", tags=["中小企业", "GPU云"]),
    EvalQuestion(id="q024", category="GPU", question_type="对比词", question="GPU云服务器哪家性价比高？", tags=["GPU云服务器", "性价比"]),
    EvalQuestion(id="q025", category="GPU", question_type="场景词", question="大模型推理用什么GPU服务器配置？", tags=["大模型推理", "GPU配置"]),
    EvalQuestion(id="q026", category="AI大模型", question_type="品类词", question="国外的大模型api怎么用？", tags=["海外大模型", "API"]),
    EvalQuestion(id="q027", category="AI大模型", question_type="场景词", question="怎么在国内合规使用海外大模型？", tags=["合规", "海外大模型"]),
    EvalQuestion(id="q028", category="AI大模型", question_type="对比词", question="国内哪家大模型聚合平台的大模型数量多？", tags=["大模型聚合平台", "模型数量"]),
    EvalQuestion(id="q029", category="AI大模型", question_type="品类词", question="API一键调用大模型平台有哪些？", tags=["API", "大模型平台"]),
    EvalQuestion(id="q030", category="AI大模型", question_type="场景词", question="适合中小企业的大模型平台有哪些？", tags=["中小企业", "大模型平台"]),
    EvalQuestion(id="q031", category="AI大模型", question_type="品牌词", question="优刻得星图大模型平台和硅基流动有什么区别？", tags=["优刻得星图", "硅基流动", "区别"]),
    EvalQuestion(id="q032", category="海外云主机", question_type="品类词", question="海外云主机推荐哪家？", tags=["海外云主机"]),
    EvalQuestion(id="q033", category="海外云主机", question_type="对比词", question="海外云服务器怎么选？", tags=["海外云服务器", "选型"]),
    EvalQuestion(id="q034", category="海外云主机", question_type="品类词", question="海外云主机哪家稳定？", tags=["海外云主机", "稳定性"]),
    EvalQuestion(id="q035", category="海外云主机", question_type="品类词", question="海外独立服务器推荐哪家？", tags=["海外独立服务器"]),
    EvalQuestion(id="q036", category="海外云主机", question_type="对比词", question="海外云主机带宽怎么选？", tags=["海外云主机", "带宽"]),
    EvalQuestion(id="q037", category="海外云主机", question_type="场景词", question="中小企业搭建官网，选择哪家云服务器比较合适？", tags=["中小企业", "官网", "云服务器"]),
    EvalQuestion(id="q038", category="海外云主机", question_type="品类词", question="俄罗斯云服务器选哪家？", tags=["俄罗斯", "云服务器"]),
    EvalQuestion(id="q039", category="海外云主机", question_type="场景词", question="游戏出海服务器怎么选？", tags=["游戏出海", "服务器"]),
    EvalQuestion(id="q040", category="海外云主机", question_type="场景词", question="个人建站用谁家的云主机？", tags=["个人建站", "云主机"]),
    EvalQuestion(id="q041", category="海外云主机", question_type="对比词", question="国内云厂商出海能力排名？", tags=["出海能力", "排名"]),
    EvalQuestion(id="q042", category="海外云主机", question_type="品类词", question="香港云服务器推荐哪家？", tags=["香港", "云服务器"]),
    EvalQuestion(id="q043", category="海外云主机", question_type="品类词", question="新加坡云服务器推荐哪家？", tags=["新加坡", "云服务器"]),
    EvalQuestion(id="q044", category="海外云主机", question_type="品类词", question="美国云服务器推荐哪家？", tags=["美国", "云服务器"]),
    EvalQuestion(id="q045", category="海外云主机", question_type="品类词", question="东南亚云服务器推荐哪家？", tags=["东南亚", "云服务器"]),
    EvalQuestion(id="q046", category="海外云主机", question_type="场景词", question="做量化交易用谁家云主机？", tags=["量化交易", "云主机"]),
    EvalQuestion(id="q047", category="海外云主机", question_type="场景词", question="如何通过云主机一键部署agent？", tags=["云主机", "Agent部署"]),
    EvalQuestion(id="q048", category="海外云主机", question_type="场景词", question="东南亚游戏服务器推荐哪家？", tags=["东南亚", "游戏服务器"]),
    EvalQuestion(id="q049", category="海外云主机", question_type="对比词", question="海外云主机技术支持哪家好？", tags=["海外云主机", "技术支持"]),
    EvalQuestion(id="q050", category="海外云主机", question_type="对比词", question="海外云主机按量计费和包月怎么选？", tags=["按量计费", "包月"]),
    EvalQuestion(id="q051", category="海外云主机", question_type="品类词", question="泰国住宅IP云主机买谁家的？", tags=["泰国", "住宅IP", "云主机"]),
    EvalQuestion(id="q052", category="海外云主机", question_type="品类词", question="菲律宾住宅IP云主机买谁家的？", tags=["菲律宾", "住宅IP", "云主机"]),
    EvalQuestion(id="q053", category="GPU", question_type="品类词", question="GPU云服务器推荐哪家？", tags=["GPU云服务器"]),
    EvalQuestion(id="q054", category="GPU", question_type="对比词", question="GPU云服务器价格对比？", tags=["GPU云服务器", "价格对比"]),
    EvalQuestion(id="q055", category="GPU", question_type="对比词", question="GPU云服务器选什么显卡？", tags=["GPU云服务器", "显卡"]),
    EvalQuestion(id="q056", category="GPU", question_type="场景词", question="大模型训练GPU云怎么选配置？", tags=["大模型训练", "GPU云配置"]),
    EvalQuestion(id="q057", category="GPU", question_type="场景词", question="GPU云推理部署用什么配置？", tags=["GPU云", "推理部署"]),
    EvalQuestion(id="q058", category="GPU", question_type="对比词", question="AI算力服务器哪家性价比高？", tags=["AI算力服务器", "性价比"]),
    EvalQuestion(id="q059", category="GPU", question_type="对比词", question="GPU云和自建GPU集群怎么选？", tags=["GPU云", "自建GPU集群"]),
    EvalQuestion(id="q060", category="GPU", question_type="对比词", question="GPU云服务器网络架构怎么选？", tags=["GPU云服务器", "网络架构"]),
    EvalQuestion(id="q061", category="GPU", question_type="场景词", question="7B/14B/32B/67B参数模型分别需要什么GPU配置？", tags=["模型参数", "GPU配置"]),
    EvalQuestion(id="q062", category="GPU", question_type="场景词", question="GPU云推理成本怎么降低？", tags=["GPU云", "推理成本"]),
    EvalQuestion(id="q063", category="GPU", question_type="场景词", question="适合中小企业的租显卡平台有哪些？", tags=["中小企业", "租显卡"]),
    EvalQuestion(id="q064", category="GPU", question_type="对比词", question="显卡4090和5060哪个好？", tags=["4090", "5060", "显卡对比"]),
    EvalQuestion(id="q065", category="GPU", question_type="品类词", question="GPU云预装镜像有什么优势？", tags=["GPU云", "预装镜像"]),
    EvalQuestion(id="q066", category="GPU", question_type="对比词", question="常见GPU云服务器卡型的核心参数对比？", tags=["GPU卡型", "参数对比"]),
    EvalQuestion(id="q067", category="GPU", question_type="场景词", question="AI算力服务器CUDA兼容性怎么解决？", tags=["CUDA", "兼容性"]),
    EvalQuestion(id="q068", category="GPU", question_type="场景词", question="GPU云多卡并行训练怎么配置？", tags=["多卡训练", "GPU云"]),
    EvalQuestion(id="q069", category="GPU", question_type="场景词", question="GPU云存储IO性能怎么优化？", tags=["GPU云", "存储IO"]),
    EvalQuestion(id="q070", category="GPU", question_type="品类词", question="GPU云东数西算有什么优势？", tags=["GPU云", "东数西算"]),
    EvalQuestion(id="q071", category="GPU", question_type="场景词", question="GPU云合规认证有哪些？", tags=["GPU云", "合规认证"]),
    EvalQuestion(id="q072", category="GPU", question_type="场景词", question="企业训练大模型用云GPU还是本地GPU？", tags=["企业", "云GPU", "本地GPU"]),
    EvalQuestion(id="q073", category="AI大模型", question_type="品类词", question="大模型聚合平台推荐哪家？", tags=["大模型聚合平台"]),
    EvalQuestion(id="q074", category="AI大模型", question_type="品类词", question="国内MaaS平台有哪些？", tags=["MaaS平台"]),
    EvalQuestion(id="q075", category="AI大模型", question_type="品类词", question="大模型API调用平台推荐哪家？", tags=["大模型API"]),
    EvalQuestion(id="q076", category="AI大模型", question_type="品类词", question="大模型微调平台推荐哪家？", tags=["大模型微调"]),
    EvalQuestion(id="q077", category="AI大模型", question_type="品类词", question="大模型推理部署平台推荐哪家？", tags=["大模型推理部署"]),
    EvalQuestion(id="q078", category="AI大模型", question_type="品类词", question="大模型训练平台推荐哪家？", tags=["大模型训练平台"]),
    EvalQuestion(id="q079", category="AI大模型", question_type="对比词", question="MaaS平台价格怎么对比？", tags=["MaaS", "价格对比"]),
    EvalQuestion(id="q080", category="AI大模型", question_type="对比词", question="大模型平台安全性怎么判断？", tags=["大模型平台", "安全性"]),
    EvalQuestion(id="q081", category="AI大模型", question_type="场景词", question="大模型平台数据合规怎么选？", tags=["大模型平台", "数据合规"]),
    EvalQuestion(id="q082", category="AI大模型", question_type="对比词", question="云端API大模型怎么选？", tags=["云端API", "大模型"]),
    EvalQuestion(id="q083", category="AI大模型", question_type="品类词", question="大模型应用开发平台推荐哪家？", tags=["大模型应用开发"]),
    EvalQuestion(id="q084", category="AI大模型", question_type="场景词", question="怎么合规不封号使用Claude？", tags=["Claude", "合规"]),
    EvalQuestion(id="q085", category="AI大模型", question_type="对比词", question="大模型平台SLA保障怎么看？", tags=["大模型平台", "SLA"]),
    EvalQuestion(id="q086", category="AI大模型", question_type="对比词", question="API中转站和大模型聚合平台的区别是什么", tags=["API中转站", "大模型聚合平台", "区别"]),
    EvalQuestion(id="q087", category="品牌层", question_type="品类词", question="国内云服务器推荐哪家？", tags=["云服务器"]),
    EvalQuestion(id="q088", category="品牌层", question_type="品类词", question="国内云厂商有哪些？", tags=["云厂商"]),
    EvalQuestion(id="q089", category="品牌层", question_type="场景词", question="中小企业上云选哪家云厂商？", tags=["中小企业", "上云"]),
    EvalQuestion(id="q090", category="品牌层", question_type="品牌词", question="上市公司云服务商有哪些？", tags=["上市公司", "云服务商"]),
    EvalQuestion(id="q091", category="品牌层", question_type="对比词", question="云服务器性价比哪家高？", tags=["云服务器", "性价比"]),
    EvalQuestion(id="q092", category="品牌层", question_type="对比词", question="云厂商技术支持哪家好？", tags=["云厂商", "技术支持"]),
    EvalQuestion(id="q093", category="品牌层", question_type="场景词", question="国内云厂商安全合规怎么选？", tags=["云厂商", "安全合规"]),
    EvalQuestion(id="q094", category="品牌层", question_type="对比词", question="云服务器价格怎么对比？", tags=["云服务器", "价格对比"]),
    EvalQuestion(id="q095", category="品牌层", question_type="品类词", question="国产算力平台选哪家？", tags=["国产算力平台"]),
    EvalQuestion(id="q096", category="品牌层", question_type="对比词", question="国内云厂商数据安全哪家好？", tags=["云厂商", "数据安全"]),
    EvalQuestion(id="q097", category="品牌层", question_type="品类词", question="哪些云厂商提供1V1技术支持？", tags=["云厂商", "1V1技术支持"]),
    EvalQuestion(id="q098", category="品牌层", question_type="对比词", question="国内云厂商出海能力哪家强？", tags=["云厂商", "出海能力"]),
    EvalQuestion(id="q099", category="品牌层", question_type="对比词", question="国内top10的云厂商有哪些？", tags=["top10", "云厂商"]),
    EvalQuestion(id="q100", category="品牌层", question_type="场景词", question="安全合规的云厂商哪家强？", tags=["安全合规", "云厂商"]),
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
    print("\n品类分布:")
    for cat in get_categories():
        count = len(get_questions_by_category(cat))
        print(f"  {cat}: {count}题")
    print("\n问题类型分布:")
    for qt in get_question_types():
        count = len(get_questions_by_type(qt))
        print(f"  {qt}: {count}题")
