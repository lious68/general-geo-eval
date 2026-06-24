"""
UCloud GEO 评估框架 - 指标计算引擎
计算提及率、引用率、TOP3推荐率、情感值等核心GEO指标

口径与 backend/database.py get_scores() 保持一致：
- 提及率 / TOP3推荐率：分母仅自然问题（排除引导型、题干含UCloud/优刻得的）
- 引用率 / 情感值：分母为全部有效问题
- 引用率分子：使用有效引用口径（含UCloud官方引用 + UCloud相关第三方来源引用）
- 情感值：全部有效响应的平均值
"""
import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from analyzer import AnalysisResult, THIRD_PARTY_CITATION_DOMAINS
from brand_profile import BrandProfile, is_natural_question, default_brand_profile

logger = logging.getLogger(__name__)


def _has_effective_citation(result: AnalysisResult) -> bool:
    """判断是否有有效引用（与 database.py 口径一致）

    有效引用 = UCloud官方引用 OR (回答提及UCloud时的第三方来源引用)

    官方引用：citations 或 all_cited_urls 中任一 is_ucloud 即计入。
    必须同时扫 all_cited_urls —— analyzer 对【子域名】UCloud 官方 URL
    （astraflow.ucloud.cn / docs.ucloud.cn / www-waf.ucloud.cn 等）只放进
    all_cited_urls（url_patterns 仅匹配 ucloud.cn / ucloud.com / ucloudstack.com
    根域，子域名进不了 citations），只扫 citations 会漏判这类官方引用。
    """
    for c in result.citations:
        if c.is_ucloud:
            return True
    for c in result.all_cited_urls:
        if c.is_ucloud:
            return True
    # 第三方来源引用：回答提及了 UCloud 且有第三方域名引用
    if result.ucloud_mentioned:
        for c in result.citations:
            if c.citation_type == "url" and not c.is_ucloud:
                url = c.content.lower()
                if any(domain in url for domain in THIRD_PARTY_CITATION_DOMAINS):
                    return True
    return False


@dataclass
class GEOScores:
    """GEO综合评分"""
    # 核心指标（4个基础指标 + GEO综合分）
    coverage_rate: float = 0.0        # 提及率（UCloud被提及的自然问题占比）
    mention_rate: float = 0.0         # 原提及频次指标（已不参与GEO综合得分）
    citation_rate: float = 0.0        # 引用率（有效引用占比）
    recommendation_rate: float = 0.0  # TOP3推荐率
    sentiment_score: float = 0.0      # 情感值

    # 细分指标
    avg_mention_count: float = 0.0    # 平均提及次数
    avg_position_weight: float = 0.0  # 平均位置权重
    avg_rank: float = 0.0            # 平均排名
    strong_recommend_rate: float = 0.0  # 强推荐率
    moderate_recommend_rate: float = 0.0 # 中等推荐率

    # 综合GEO分数
    geo_score: float = 0.0

    # 样本信息
    total_questions: int = 0
    valid_responses: int = 0
    error_responses: int = 0


@dataclass
class CategoryScores:
    """按品类分组的评分"""
    category: str
    scores: GEOScores
    question_count: int


@dataclass
class ModelComparison:
    """跨模型对比"""
    model_key: str
    model_name: str
    scores: GEOScores
    category_scores: List[CategoryScores]


class MetricsCalculator:
    """GEO指标计算器（口径与仪表盘 backend/database.py 一致）"""

    # 综合GEO分数的权重配置
    GEO_WEIGHTS = {
        "coverage_rate": 0.45,        # 提及率权重
        "mention_rate": 0.0,          # 原提及频次指标已不参与GEO综合得分
        "citation_rate": 0.25,        # 引用率权重
        "recommendation_rate": 0.20,  # TOP3推荐率权重
        "sentiment_score": 0.10,      # 情感值权重
    }

    def calculate_scores(self, results: List[AnalysisResult],
                         questions: List[Dict] = None,
                         brand_profile: BrandProfile = None) -> GEOScores:
        """计算一组分析结果的GEO评分

        Args:
            results: 分析结果列表
            questions: 问题列表（用于区分自然问题），格式 [{"id": ..., "question": ..., "category": ...}, ...]
                       如果不传，则按默认规则判定自然问题
            brand_profile: 被测品牌档案（自然问题过滤用）。None 时用 UCloud 默认档案。
        """
        scores = GEOScores()

        # 过滤有效结果
        valid_results = [r for r in results if not r.has_error]
        error_results = [r for r in results if r.has_error]

        scores.total_questions = len(results)
        scores.valid_responses = len(valid_results)
        scores.error_responses = len(error_results)

        if not valid_results:
            return scores

        # 区分自然问题（与仪表盘口径一致）
        # 提及率/TOP3推荐率仅统计自然问题；引用率/情感值统计全部有效问题
        question_map = {}
        if questions:
            for q in questions:
                question_map[q.get("id", "")] = q

        natural_results = []
        for r in valid_results:
            q = question_map.get(r.question_id, {})
            question_text = q.get("question", "")
            category = q.get("category", "")
            if is_natural_question(question_text, category, brand_profile):
                natural_results.append(r)

        natural_count = len(natural_results) if natural_results else len(valid_results)

        # ---- 提及率（coverage_rate）----
        # 分母：自然问题数
        # 分子：UCloud被提及的自然问题数
        if natural_results:
            mentioned_count = sum(1 for r in natural_results if r.ucloud_mentioned)
            scores.coverage_rate = round(mentioned_count / natural_count, 4)
        else:
            mentioned_count = sum(1 for r in valid_results if r.ucloud_mentioned)
            scores.coverage_rate = round(mentioned_count / len(valid_results), 4)

        # ---- 原提及率（mention_rate，不参与GEO得分）----
        weighted_mentions = []
        for r in valid_results:
            if r.ucloud_mentioned:
                weighted_mentions.append(r.ucloud_mention_count * r.position_weight)
            else:
                weighted_mentions.append(0)
        scores.mention_rate = round(
            sum(weighted_mentions) / len(valid_results), 4
        )
        scores.avg_mention_count = round(
            sum(r.ucloud_mention_count for r in valid_results) / len(valid_results), 4
        )

        # ---- 引用率 ----
        # 分母：全部有效问题
        # 分子：有效引用数（含UCloud官方引用 + UCloud相关第三方来源引用）
        cited_count = sum(1 for r in valid_results if _has_effective_citation(r))
        scores.citation_rate = round(cited_count / len(valid_results), 4)

        # ---- TOP3推荐率 ----
        # 分母：自然问题数
        # 分子：UCloud排名≤3的自然问题数
        if natural_results:
            top3_count = sum(
                1 for r in natural_results
                if r.ucloud_rank is not None and r.ucloud_rank <= 3
            )
            scores.recommendation_rate = round(top3_count / natural_count, 4)

            strong_count = sum(
                1 for r in natural_results
                if r.ucloud_recommendation_strength == "strong"
            )
            moderate_count = sum(
                1 for r in natural_results
                if r.ucloud_recommendation_strength == "moderate"
            )
            scores.strong_recommend_rate = round(strong_count / natural_count, 4)
            scores.moderate_recommend_rate = round(moderate_count / natural_count, 4)
        else:
            top3_count = sum(
                1 for r in valid_results
                if r.ucloud_rank is not None and r.ucloud_rank <= 3
            )
            scores.recommendation_rate = round(top3_count / len(valid_results), 4)

        # ---- 情感值 ----
        # 分母：全部有效问题
        # 分子：所有有效响应的情感平均值
        scores.sentiment_score = round(
            sum(r.sentiment_score for r in valid_results) / len(valid_results), 4
        )

        # ---- 位置权重 ----
        weighted_results = [r for r in valid_results if r.ucloud_mentioned]
        if weighted_results:
            scores.avg_position_weight = round(
                sum(r.position_weight for r in weighted_results) / len(weighted_results), 4
            )
        else:
            scores.avg_position_weight = 0.0

        # ---- 平均排名 ----
        ranked_results = [r for r in valid_results if r.ucloud_rank is not None]
        if ranked_results:
            scores.avg_rank = round(
                sum(r.ucloud_rank for r in ranked_results) / len(ranked_results), 2
            )
        else:
            scores.avg_rank = 0.0

        # ---- 综合GEO分数 ----
        scores.geo_score = self._calculate_geo_score(scores)

        return scores

    def _calculate_geo_score(self, scores: GEOScores) -> float:
        """计算综合GEO分数（0-100）"""
        coverage = scores.coverage_rate      # 提及率
        citation = scores.citation_rate      # 引用率
        recommendation = scores.recommendation_rate  # TOP3推荐率
        sentiment = scores.sentiment_score    # 情感值

        weighted_sum = (
            coverage * self.GEO_WEIGHTS["coverage_rate"] +
            citation * self.GEO_WEIGHTS["citation_rate"] +
            recommendation * self.GEO_WEIGHTS["recommendation_rate"] +
            sentiment * self.GEO_WEIGHTS["sentiment_score"]
        )

        geo_score = round(weighted_sum * 100, 2)
        return geo_score

    def calculate_by_category(self, results: List[AnalysisResult],
                               categories: Dict[str, List[str]]) -> List[CategoryScores]:
        """按品类计算评分"""
        category_scores = []

        for category, question_ids in categories.items():
            category_results = [
                r for r in results if r.question_id in question_ids
            ]
            if category_results:
                scores = self.calculate_scores(category_results)
                category_scores.append(CategoryScores(
                    category=category,
                    scores=scores,
                    question_count=len(category_results),
                ))

        return category_scores

    def calculate_by_question_type(self, results: List[AnalysisResult],
                                    question_types: Dict[str, List[str]]) -> List[CategoryScores]:
        """按问题类型计算评分"""
        type_scores = []

        for qtype, question_ids in question_types.items():
            type_results = [
                r for r in results if r.question_id in question_ids
            ]
            if type_results:
                scores = self.calculate_scores(type_results)
                type_scores.append(CategoryScores(
                    category=qtype,
                    scores=scores,
                    question_count=len(type_results),
                ))

        return type_scores

    def compare_models(self, all_results: Dict[str, List[AnalysisResult]],
                       categories: Dict[str, List[str]] = None) -> List[ModelComparison]:
        """跨模型对比"""
        comparisons = []

        for model_key, results in all_results.items():
            model_name = results[0].model_name if results else model_key
            scores = self.calculate_scores(results)

            cat_scores = []
            if categories:
                cat_scores = self.calculate_by_category(results, categories)

            comparisons.append(ModelComparison(
                model_key=model_key,
                model_name=model_name,
                scores=scores,
                category_scores=cat_scores,
            ))

        # 按GEO分数排序
        comparisons.sort(key=lambda x: x.scores.geo_score, reverse=True)
        return comparisons

    def generate_scorecard(self, scores: GEOScores) -> Dict[str, Any]:
        """生成评分卡"""
        return {
            "GEO综合得分": scores.geo_score,
            "提及率": {
                "值": scores.coverage_rate,
                "百分比": f"{scores.coverage_rate * 100:.1f}%",
                "说明": f"在自然问题中，UCloud被提及的比例",
            },
            "提及频次": {
                "值": scores.mention_rate,
                "平均提及次数": scores.avg_mention_count,
                "说明": "平均每条响应中UCloud的提及次数（含位置权重，不参与GEO得分）",
            },
            "引用率": {
                "值": scores.citation_rate,
                "百分比": f"{scores.citation_rate * 100:.1f}%",
                "说明": "包含有效引用（UCloud官方+相关第三方来源）的响应比例",
            },
            "TOP3推荐率": {
                "值": scores.recommendation_rate,
                "百分比": f"{scores.recommendation_rate * 100:.1f}%",
                "强推荐率": f"{scores.strong_recommend_rate * 100:.1f}%",
                "中等推荐率": f"{scores.moderate_recommend_rate * 100:.1f}%",
                "说明": "在自然问题中UCloud进入品牌推荐Top3的比例",
            },
            "情感值": {
                "值": scores.sentiment_score,
                "标签": "正面" if scores.sentiment_score > 0.6 else ("负面" if scores.sentiment_score < 0.4 else "中性"),
                "说明": "全部有效响应的平均情感倾向",
            },
            "位置权重": {
                "值": scores.avg_position_weight,
                "说明": "UCloud首次出现位置的权重（越靠前越高）",
            },
            "平均排名": {
                "值": scores.avg_rank,
                "说明": "UCloud在品牌推荐列表中的平均排名",
            },
            "样本信息": {
                "总问题数": scores.total_questions,
                "有效响应": scores.valid_responses,
                "错误响应": scores.error_responses,
            },
        }
