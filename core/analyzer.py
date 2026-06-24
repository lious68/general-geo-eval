"""
UCloud GEO 评估框架 - 响应分析器
负责解析模型响应，提取提及、引用、推荐、情感等信息
"""
import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from config import BRAND_KEYWORDS, COMPETITOR_KEYWORDS, SCORE_CONFIG
from brand_profile import BrandProfile, default_brand_profile

logger = logging.getLogger(__name__)

THIRD_PARTY_CITATION_DOMAINS = [
    "zhihu.com", "csdn.net", "juejin.cn", "github.com", "bilibili.com",
    "segmentfault.com", "oschina.net", "cnblogs.com", "infoq.cn", "51cto.com",
    "mp.weixin.qq.com",
    # 补充常见中文技术/资讯社区
    "jianshu.com", "oscimg.com", "weibo.com", "36kr.com",
    "stackoverflow.com", "gitee.com", "readthedocs.io",
    "tianyancha.com", "qcc.com",
    # 自媒体平台（头条/百家号/搜狐号/网易号）
    "toutiao.com", "baijiahao.baidu.com", "sohu.com", "163.com",
]


@dataclass
class BrandMention:
    """品牌提及信息"""
    keyword: str           # 匹配到的关键词
    position: int          # 在文本中的位置（字符偏移）
    context: str           # 上下文（前后各50字）
    mention_type: str      # primary / product / alias


@dataclass
class CitationInfo:
    """引用信息"""
    citation_type: str     # url / reference
    content: str           # 引用内容
    position: int          # 位置
    source_channel: str = ""   # 来源渠道（仅url类型，如"UCloud官网"、"知乎"等）
    is_ucloud: bool = False    # 是否为UCloud相关引用


@dataclass
class RecommendationInfo:
    """推荐信息"""
    brand: str             # 推荐的品牌
    strength: str          # strong / moderate / comparison_win
    keyword: str           # 匹配的关键词
    context: str           # 上下文


@dataclass
class AnalysisResult:
    """单条响应的分析结果"""
    question_id: str
    model_key: str
    model_name: str

    # 基础信息
    response_length: int = 0
    has_error: bool = False
    error_message: str = ""

    # UCloud 品牌
    ucloud_mentioned: bool = False
    ucloud_mentions: List[BrandMention] = field(default_factory=list)
    ucloud_mention_count: int = 0
    ucloud_first_position: Optional[int] = None  # 首次出现位置
    ucloud_rank: Optional[int] = None            # 在推荐列表中的排名

    # 竞品提及
    competitor_mentions: Dict[str, List[BrandMention]] = field(default_factory=dict)

    # 引用
    has_citation: bool = False
    citations: List[CitationInfo] = field(default_factory=list)
    citation_count: int = 0

    # 所有被引用的URL（含非UCloud的，用于来源渠道聚类）
    all_cited_urls: List[CitationInfo] = field(default_factory=list)

    # 推荐
    has_recommendation: bool = False
    recommendations: List[RecommendationInfo] = field(default_factory=list)
    ucloud_recommended: bool = False
    ucloud_recommendation_strength: str = ""  # strong / moderate / none

    # 情感
    sentiment_score: float = 0.5  # 0-1, 0.5为中性
    sentiment_label: str = "neutral"  # positive / neutral / negative

    # 位置权重
    position_weight: float = 1.0

    # 原文
    raw_content: str = ""


class ResponseAnalyzer:
    """响应分析器"""

    def __init__(self, brand_profile: BrandProfile = None):
        """brand_profile 为 None 时使用 UCloud 默认档案（向后兼容）。"""
        self.brand_profile = brand_profile or default_brand_profile()
        p = self.brand_profile
        self.brand_keywords = p.keywords
        self.official_domains = p.official_domains
        self.url_patterns = p.url_patterns
        self.reference_keywords = p.reference_keywords
        self.display_names = p.display_names
        self.competitor_keywords = COMPETITOR_KEYWORDS
        self.score_config = SCORE_CONFIG

    def analyze(self, question_id: str, model_key: str, model_name: str,
                content: str, error: str = None,
                search_results: list = None) -> AnalysisResult:
        """分析单条模型响应"""
        result = AnalysisResult(
            question_id=question_id,
            model_key=model_key,
            model_name=model_name,
        )

        if error or not content:
            result.has_error = True
            result.error_message = error or "Empty response"
            return result

        result.raw_content = content
        result.response_length = len(content)

        # 1. 检测UCloud品牌提及
        self._detect_brand_mentions(content, result)

        # 2. 检测竞品提及
        self._detect_competitor_mentions(content, result)

        # 3. 检测引用
        self._detect_citations(content, result)

        # 3.5 合并 API 返回的联网搜索引用来源
        if search_results:
            self._incorporate_search_results(content, result, search_results)

        # 4. 检测推荐
        self._detect_recommendations(content, result)

        # 5. 情感分析
        self._analyze_sentiment(content, result)

        # 6. 计算位置权重
        self._calculate_position_weight(content, result)

        # 7. 计算排名
        self._calculate_rank(content, result)

        return result

    def _detect_brand_mentions(self, content: str, result: AnalysisResult):
        """检测UCloud品牌提及"""
        for mention_type, keywords in self.brand_keywords.items():
            for keyword in keywords:
                # 大小写不敏感搜索（对于英文关键词）
                if keyword.isascii():
                    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                else:
                    pattern = re.compile(re.escape(keyword))

                for match in pattern.finditer(content):
                    pos = match.start()
                    # 提取上下文
                    context_start = max(0, pos - 50)
                    context_end = min(len(content), match.end() + 50)
                    context = content[context_start:context_end]

                    mention = BrandMention(
                        keyword=keyword,
                        position=pos,
                        context=context,
                        mention_type=mention_type,
                    )
                    result.ucloud_mentions.append(mention)

        # 去重（同一位置可能匹配多个关键词）
        seen_positions = set()
        unique_mentions = []
        for m in result.ucloud_mentions:
            if m.position not in seen_positions:
                seen_positions.add(m.position)
                unique_mentions.append(m)
        result.ucloud_mentions = sorted(unique_mentions, key=lambda x: x.position)

        result.ucloud_mentioned = len(result.ucloud_mentions) > 0
        result.ucloud_mention_count = len(result.ucloud_mentions)
        if result.ucloud_mentions:
            result.ucloud_first_position = result.ucloud_mentions[0].position

    def _detect_competitor_mentions(self, content: str, result: AnalysisResult):
        """检测竞品提及"""
        for competitor, keywords in self.competitor_keywords.items():
            mentions = []
            for keyword in keywords:
                # 跳过通用词（如ECS，可能指不同厂商）
                if keyword in ["ECS", "OBS"] and competitor not in ["alibaba", "huawei"]:
                    continue
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                for match in pattern.finditer(content):
                    pos = match.start()
                    context_start = max(0, pos - 50)
                    context_end = min(len(content), match.end() + 50)
                    context = content[context_start:context_end]
                    mentions.append(BrandMention(
                        keyword=keyword,
                        position=pos,
                        context=context,
                        mention_type="competitor",
                    ))
            if mentions:
                # 去重
                seen = set()
                unique = []
                for m in mentions:
                    if m.position not in seen:
                        seen.add(m.position)
                        unique.append(m)
                result.competitor_mentions[competitor] = sorted(unique, key=lambda x: x.position)

    def _is_ucloud_related_url_context(self, content: str, position: int, window: int = 180) -> bool:
        """判断 URL 附近上下文是否在讲 UCloud/优刻得。"""
        context = content[max(0, position - window): min(len(content), position + window)]
        keywords = []
        for group in ("primary", "products", "aliases"):
            keywords.extend(self.brand_keywords.get(group, []))
        return any(re.search(re.escape(kw), context, re.IGNORECASE) for kw in keywords if kw)

    def _detect_citations(self, content: str, result: AnalysisResult):
        """检测引用（URL链接和参考引用）"""
        from config import resolve_channel

        # 先用通用正则提取所有 URL，以获取完整路径（避免 url_patterns 截断 URL）
        url_pattern = re.compile(r'https?://[^\s<>"\')\]，。、；：！？】}]+')
        content_urls = {}  # pos -> full_url
        for match in url_pattern.finditer(content):
            pos = match.start()
            full_url = match.group().rstrip(".,;:!?)]}>》）】")
            content_urls[pos] = full_url

        # 1. 检测UCloud相关URL（使用完整URL，而非 url_patterns 截断的短匹配）
        for pos, full_url in content_urls.items():
            if any(re.search(p, full_url) for p in self.url_patterns):
                result.citations.append(CitationInfo(
                    citation_type="url",
                    content=full_url,
                    position=pos,
                    source_channel=resolve_channel(full_url),
                    is_ucloud=True,
                ))

        # 2. 检测参考引用关键词
        for keyword in self.reference_keywords:
            pattern = re.compile(re.escape(keyword))
            for match in pattern.finditer(content):
                pos = match.start()
                result.citations.append(CitationInfo(
                    citation_type="reference",
                    content=match.group(),
                    position=pos,
                    is_ucloud=True,
                ))

        # 3. 检测所有URL（用于来源渠道聚类统计）
        self._detect_all_urls(content, result)

        # 4. 回答提及 UCloud 时，知乎/CSDN/掘金/GitHub/B站等第三方来源也计入引用
        if result.ucloud_mentioned:
            seen = {(c.citation_type, c.content, c.position) for c in result.citations}
            for url_info in result.all_cited_urls:
                url = url_info.content.lower()
                if not any(domain in url for domain in THIRD_PARTY_CITATION_DOMAINS):
                    continue
                if not self._is_ucloud_related_url_context(content, url_info.position):
                    continue
                key = ("url", url_info.content, url_info.position)
                if key in seen:
                    continue
                result.citations.append(CitationInfo(
                    citation_type="url",
                    content=url_info.content,
                    position=url_info.position,
                    source_channel=url_info.source_channel,
                    is_ucloud=False,
                ))
                seen.add(key)

        result.has_citation = len(result.citations) > 0
        result.citation_count = len(result.citations)

    def _detect_recommendations(self, content: str, result: AnalysisResult):
        """检测推荐信息"""
        # 检测UCloud是否被推荐
        if not result.ucloud_mentioned:
            result.ucloud_recommended = False
            result.ucloud_recommendation_strength = "none"
            return

        # 找到UCloud首次提及的上下文（扩展到更大范围）
        first_mention = result.ucloud_mentions[0]
        pos = first_mention.position
        context_start = max(0, pos - 150)
        context_end = min(len(content), pos + 300)
        extended_context = content[context_start:context_end]

        # 检查强推荐关键词
        strength = "none"
        brand_name = self.brand_profile.brand_name or "品牌"
        for kw in self.score_config["recommendation"]["strong_keywords"]:
            if kw in extended_context:
                strength = "strong"
                result.recommendations.append(RecommendationInfo(
                    brand=brand_name,
                    strength="strong",
                    keyword=kw,
                    context=extended_context,
                ))
                break

        # 检查中等推荐关键词
        if strength == "none":
            for kw in self.score_config["recommendation"]["moderate_keywords"]:
                if kw in extended_context:
                    strength = "moderate"
                    result.recommendations.append(RecommendationInfo(
                        brand=brand_name,
                        strength="moderate",
                        keyword=kw,
                        context=extended_context,
                    ))
                    break

        # 检查对比胜出关键词
        if strength == "none":
            brand_in_ctx = any(n in extended_context for n in self.display_names)
            for kw in self.score_config["recommendation"]["comparison_win_keywords"]:
                if kw in extended_context and brand_in_ctx:
                    strength = "comparison_win"
                    result.recommendations.append(RecommendationInfo(
                        brand=brand_name,
                        strength="comparison_win",
                        keyword=kw,
                        context=extended_context,
                    ))
                    break

        result.ucloud_recommended = strength in ("strong", "moderate", "comparison_win")
        result.ucloud_recommendation_strength = strength
        result.has_recommendation = len(result.recommendations) > 0

    def _analyze_sentiment(self, content: str, result: AnalysisResult):
        """情感分析"""
        if not result.ucloud_mentioned:
            result.sentiment_score = 0.5
            result.sentiment_label = "neutral"
            return

        try:
            from snownlp import SnowNLP
            # 提取UCloud提及周围的上下文进行情感分析
            contexts = []
            for mention in result.ucloud_mentions[:3]:  # 最多取前3个提及的上下文
                pos = mention.position
                context_start = max(0, pos - 100)
                context_end = min(len(content), pos + 200)
                contexts.append(content[context_start:context_end])

            if contexts:
                scores = []
                for ctx in contexts:
                    try:
                        s = SnowNLP(ctx)
                        scores.append(s.sentiments)
                    except:
                        scores.append(0.5)
                avg_score = sum(scores) / len(scores)
            else:
                avg_score = 0.5

            result.sentiment_score = round(avg_score, 4)

            # 根据阈值判定情感标签
            thresholds = self.score_config["sentiment"]
            if avg_score > thresholds["positive_threshold"]:
                result.sentiment_label = "positive"
            elif avg_score < thresholds["negative_threshold"]:
                result.sentiment_label = "negative"
            else:
                result.sentiment_label = "neutral"

        except ImportError:
            # 如果没有安装snownlp，使用基于规则的简单情感分析
            result.sentiment_score = self._rule_based_sentiment(content, result)
            if result.sentiment_score > 0.6:
                result.sentiment_label = "positive"
            elif result.sentiment_score < 0.4:
                result.sentiment_label = "negative"
            else:
                result.sentiment_label = "neutral"

    def _rule_based_sentiment(self, content: str, result: AnalysisResult) -> float:
        """基于规则的情感分析（snownlp不可用时的备选方案）"""
        if not result.ucloud_mentions:
            return 0.5

        positive_words = [
            "好", "优秀", "出色", "推荐", "稳定", "靠谱", "性价比高",
            "不错", "值得", "优势", "领先", "专业", "强大", "全面",
            "好评", "满意", "首选", "便捷", "灵活", "安全",
        ]
        negative_words = [
            "差", "不好", "问题", "不稳定", "贵", "慢", "坑",
            "不推荐", "失望", "故障", "宕机", "投诉", "吐槽",
            "劣势", "不足", "欠缺", "弱",
        ]

        score = 0.5
        # 检查UCloud提及附近的情感词
        for mention in result.ucloud_mentions[:3]:
            pos = mention.position
            context_start = max(0, pos - 100)
            context_end = min(len(content), pos + 200)
            context = content[context_start:context_end]

            for w in positive_words:
                if w in context:
                    score += 0.05
            for w in negative_words:
                if w in context:
                    score -= 0.05

        return max(0.0, min(1.0, score))

    def _calculate_position_weight(self, content: str, result: AnalysisResult):
        """计算位置权重"""
        if not result.ucloud_mentions:
            result.position_weight = 0.0
            return

        first_pos = result.ucloud_first_position
        total_len = len(content)

        if total_len == 0:
            result.position_weight = 1.0
            return

        # 根据首次出现位置计算相对位置
        relative_pos = first_pos / total_len

        weights = self.score_config["position_weight"]
        if relative_pos <= 0.1:
            result.position_weight = weights.get("top_10_percent", 1.5)
        elif relative_pos <= 0.2:
            result.position_weight = weights.get("top_20_percent", 1.2)
        elif relative_pos <= 0.4:
            result.position_weight = weights.get("top_40_percent", 1.0)
        else:
            result.position_weight = weights.get("beyond_40_percent", 0.8)

    def _calculate_rank(self, content: str, result: AnalysisResult):
        """计算UCloud在推荐列表中的排名"""
        if not result.ucloud_mentioned:
            result.ucloud_rank = None
            return

        # 收集所有品牌的首次出现位置
        brand_positions = {}

        # 被测品牌首次位置（用固定占位键，避免硬编码品牌名）
        _TARGET = "__target__"
        if result.ucloud_mentions:
            brand_positions[_TARGET] = result.ucloud_mentions[0].position

        # 竞品首次位置
        for competitor, mentions in result.competitor_mentions.items():
            if mentions:
                brand_positions[competitor] = mentions[0].position

        # 按位置排序
        sorted_brands = sorted(brand_positions.items(), key=lambda x: x[1])

        # 找到被测品牌的排名
        for rank, (brand, _) in enumerate(sorted_brands, 1):
            if brand == _TARGET:
                result.ucloud_rank = rank
                break

    def _detect_all_urls(self, content: str, result: AnalysisResult):
        """检测响应中所有URL，标注来源渠道（用于引用来源渠道聚类统计）"""
        from config import resolve_channel

        # 通用URL正则
        url_pattern = re.compile(r'https?://[^\s<>"\')\]，。、；：！？】}]+')
        seen_positions = set()

        # 先标记已有UCloud引用的位置，避免重复
        for c in result.citations:
            if c.citation_type == "url":
                seen_positions.add(c.position)

        for match in url_pattern.finditer(content):
            pos = match.start()
            url = match.group().rstrip(".,;:!?)]}>》）】")

            # 跳过已作为UCloud引用收录的URL
            if pos in seen_positions:
                # 但需要补充source_channel到已有的UCloud引用
                for c in result.citations:
                    if c.citation_type == "url" and c.position == pos and not c.source_channel:
                        c.source_channel = resolve_channel(url)
                continue

            channel = resolve_channel(url)
            is_uc = self.brand_profile.is_official_url(url)

            result.all_cited_urls.append(CitationInfo(
                citation_type="url",
                content=url,
                position=pos,
                source_channel=channel,
                is_ucloud=is_uc,
            ))

    def _incorporate_search_results(self, content: str, result: AnalysisResult,
                                     search_results: list):
        """将 API 返回的联网搜索引用来源合并到引用列表

        各模型 API 返回的 search_results 包含搜索引用的 URL、标题等元数据，
        这些 URL 可能不在模型回复正文中直接出现，但属于模型的引用来源。
        将其补充到 all_cited_urls 和 citations 中（去重）。

        search_results 格式:
            [{"index": int, "title": str, "url": str, "site_name": str}, ...]
        """
        from config import resolve_channel
        from urllib.parse import urlparse

        def _url_base(u):
            """提取 URL 的 scheme+netloc+path（去掉 query/fragment 和尾部斜杠）用于去重"""
            u = u.lower().rstrip("/")
            try:
                p = urlparse(u)
                base = f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
                return base
            except Exception:
                return u

        # 正文和已有引用中出现的 URL（用 base 形式去重）
        content_urls_in_text = set()
        for c in result.all_cited_urls:
            content_urls_in_text.add(_url_base(c.content))
        for c in result.citations:
            if c.citation_type == "url":
                content_urls_in_text.add(_url_base(c.content))

        for i, sr in enumerate(search_results):
            url = sr.get("url", "")
            if not url:
                continue

            url_base = _url_base(url)
            # 去重：如果正文已包含该 URL（路径级别匹配），跳过
            if url_base in content_urls_in_text:
                continue

            channel = resolve_channel(url)
            is_uc = self.brand_profile.is_official_url(url)

            # 使用负数 position 标记为 API 搜索引用（非正文位置）
            # 按顺序递减，确保唯一性
            position = -(i + 1) * 10

            citation = CitationInfo(
                citation_type="url",
                content=url,
                position=position,
                source_channel=channel,
                is_ucloud=is_uc,
            )

            # 添加到 all_cited_urls
            result.all_cited_urls.append(citation)

            # API 搜索引用：这些 URL 是模型联网搜索时返回的来源，
            # 与回答内容直接相关，无需额外判断 ucloud_mentioned 或上下文。
            if is_uc:
                result.citations.append(CitationInfo(
                    citation_type="url",
                    content=url,
                    position=position,
                    source_channel=channel,
                    is_ucloud=True,
                ))
            else:
                result.citations.append(CitationInfo(
                    citation_type="url",
                    content=url,
                    position=position,
                    source_channel=channel,
                    is_ucloud=False,
                ))

            # 注册到去重集合，防止后续搜索结果重复
            content_urls_in_text.add(url_base)

        # 更新引用统计
        result.has_citation = len(result.citations) > 0
        result.citation_count = len(result.citations)
