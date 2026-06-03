"""
UCloud GEO 评估框架 - 响应分析器
负责解析模型响应，提取提及、引用、推荐、情感等信息
"""
import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from config import BRAND_KEYWORDS, COMPETITOR_KEYWORDS, SCORE_CONFIG

logger = logging.getLogger(__name__)

THIRD_PARTY_CITATION_DOMAINS = [
    "zhihu.com", "csdn.net", "juejin.cn", "github.com", "bilibili.com",
    "segmentfault.com", "oschina.net", "cnblogs.com", "infoq.cn", "51cto.com",
    "mp.weixin.qq.com",
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

    def __init__(self):
        self.brand_keywords = BRAND_KEYWORDS
        self.competitor_keywords = COMPETITOR_KEYWORDS
        self.score_config = SCORE_CONFIG

    def analyze(self, question_id: str, model_key: str, model_name: str,
                content: str, error: str = None) -> AnalysisResult:
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

    def _detect_citations(self, content: str, result: AnalysisResult):
        """检测引用（URL链接和参考引用）"""
        # 1. 检测UCloud相关URL
        for pattern_str in self.score_config["citation"]["url_patterns"]:
            pattern = re.compile(pattern_str)
            for match in pattern.finditer(content):
                pos = match.start()
                url = match.group()
                from config import resolve_channel
                result.citations.append(CitationInfo(
                    citation_type="url",
                    content=url,
                    position=pos,
                    source_channel=resolve_channel(url),
                    is_ucloud=True,
                ))

        # 2. 检测参考引用关键词
        for keyword in self.score_config["citation"]["reference_keywords"]:
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
        for kw in self.score_config["recommendation"]["strong_keywords"]:
            if kw in extended_context:
                strength = "strong"
                result.recommendations.append(RecommendationInfo(
                    brand="UCloud",
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
                        brand="UCloud",
                        strength="moderate",
                        keyword=kw,
                        context=extended_context,
                    ))
                    break

        # 检查对比胜出关键词
        if strength == "none":
            for kw in self.score_config["recommendation"]["comparison_win_keywords"]:
                if kw in extended_context and ("UCloud" in extended_context or "优刻得" in extended_context):
                    strength = "comparison_win"
                    result.recommendations.append(RecommendationInfo(
                        brand="UCloud",
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

        # UCloud首次位置
        if result.ucloud_mentions:
            brand_positions["UCloud"] = result.ucloud_mentions[0].position

        # 竞品首次位置
        for competitor, mentions in result.competitor_mentions.items():
            if mentions:
                brand_positions[competitor] = mentions[0].position

        # 按位置排序
        sorted_brands = sorted(brand_positions.items(), key=lambda x: x[1])

        # 找到UCloud的排名
        for rank, (brand, _) in enumerate(sorted_brands, 1):
            if brand == "UCloud":
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
            is_uc = channel.startswith("UCloud") or "ucloud" in url.lower()

            result.all_cited_urls.append(CitationInfo(
                citation_type="url",
                content=url,
                position=pos,
                source_channel=channel,
                is_ucloud=is_uc,
            ))
