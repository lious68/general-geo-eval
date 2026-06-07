"""
UCloud GEO 评估框架 - 指标计算引擎
计算覆盖率、提及率、引用率、推荐率、情感值等核心GEO指标
"""
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from analyzer import AnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class GEOScores:
    """GEO综合评分"""
    # 核心指标
    coverage_rate: float = 0.0        # 覆盖率
    mention_rate: float = 0.0         # 提及率
    citation_rate: float = 0.0        # 引用率
    recommendation_rate: float = 0.0  # 推荐率
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
    """GEO指标计算器"""

    # 综合GEO分数的权重配置
    GEO_WEIGHTS = {
        "coverage_rate": 0.45,        # 提及率权重（UCloud被提及的有效响应占比）
        "mention_rate": 0.0,          # 原提及频次指标已不参与GEO综合得分
        "citation_rate": 0.25,        # 引用率权重
        "recommendation_rate": 0.20,  # TOP3推荐率权重
        "sentiment_score": 0.10,      # 情感值权重
    }

    def _is_natural_question_id(self, question_id: str) -> bool:
        """按默认题号识别自然问题：Q1-Q10（q001-q010）为引导型。"""
        qid = (question_id or "").lower()
        if qid.startswith("q") and qid[1:].isdigit():
            return int(qid[1:]) > 10
        return True

    def calculate_scores(self, results: List[AnalysisResult]) -> GEOScores:
        """计算一组分析结果的GEO评分"""
        scores = GEOScores()

        # 过滤有效结果
        valid_results = [r for r in results if not r.has_error]
        error_results = [r for r in results if r.has_error]

        scores.total_questions = len(results)
        scores.valid_responses = len(valid_results)
        scores.error_responses = len(error_results)

        if not valid_results:
            return scores

        natural_results = [r for r in valid_results if self._is_natural_question_id(r.question_id)]

        # ---- 覆盖率 ----
        # UCloud被提及的自然问题数 / 自然有效问题总数
        if natural_results:
            mentioned_count = sum(1 for r in natural_results if r.ucloud_mentioned)
            scores.coverage_rate = round(mentioned_count / len(natural_results), 4)
        else:
            scores.coverage_rate = 0.0

        # ---- 提及率 ----
        # 平均每条自然响应中的UCloud提及次数（含位置权重调整）
        weighted_mentions = []
        for r in natural_results:
            if r.ucloud_mentioned:
                weighted_mentions.append(r.ucloud_mention_count * r.position_weight)
            else:
                weighted_mentions.append(0)
        scores.mention_rate = round(
            sum(weighted_mentions) / len(natural_results), 4
        ) if natural_results else 0.0
        scores.avg_mention_count = round(
            sum(r.ucloud_mention_count for r in natural_results) / len(natural_results), 4
        ) if natural_results else 0.0

        # ---- 引用率 ----
        # 包含UCloud引用的响应数 / 全部有效响应总数
        cited_count = sum(1 for r in valid_results if r.has_citation)
        scores.citation_rate = round(cited_count / len(valid_results), 4)

        # ---- TOP3 推荐率 ----
        # UCloud进入品牌推荐列表Top3的自然响应数 / 自然有效响应总数
        top3_count = sum(
            1 for r in natural_results
            if r.ucloud_rank is not None and r.ucloud_rank <= 3
        )
        scores.recommendation_rate = round(top3_count / len(natural_results), 4) if natural_results else 0.0

        # 细分推荐强度
        strong_count = sum(
            1 for r in natural_results
            if r.ucloud_recommendation_strength == "strong"
        )
        moderate_count = sum(
            1 for r in natural_results
            if r.ucloud_recommendation_strength == "moderate"
        )
        scores.strong_recommend_rate = round(strong_count / len(natural_results), 4) if natural_results else 0.0
        scores.moderate_recommend_rate = round(moderate_count / len(natural_results), 4) if natural_results else 0.0

        # ---- 情感值 ----
        # 全部有效响应的情感平均值
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
        # 各指标归一化到0-1范围
        coverage = scores.coverage_rate  # 0-1，仪表盘显示为提及率
        citation = scores.citation_rate  # 0-1
        recommendation = scores.recommendation_rate  # 0-1，TOP3推荐率
        sentiment = scores.sentiment_score  # 0-1

        # 加权求和
        weighted_sum = (
            coverage * self.GEO_WEIGHTS["coverage_rate"] +
            citation * self.GEO_WEIGHTS["citation_rate"] +
            recommendation * self.GEO_WEIGHTS["recommendation_rate"] +
            sentiment * self.GEO_WEIGHTS["sentiment_score"]
        )

        # 转换为0-100
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
            "覆盖率": {
                "值": scores.coverage_rate,
                "百分比": f"{scores.coverage_rate * 100:.1f}%",
                "说明": f"在{scores.valid_responses}个有效问题中，UCloud被提及的比例",
            },
            "提及率": {
                "值": scores.mention_rate,
                "平均提及次数": scores.avg_mention_count,
                "说明": "平均每条响应中UCloud的提及次数（含位置权重）",
            },
            "引用率": {
                "值": scores.citation_rate,
                "百分比": f"{scores.citation_rate * 100:.1f}%",
                "说明": "包含UCloud引用/链接的响应比例",
            },
            "推荐率": {
                "值": scores.recommendation_rate,
                "百分比": f"{scores.recommendation_rate * 100:.1f}%",
                "强推荐率": f"{scores.strong_recommend_rate * 100:.1f}%",
                "中等推荐率": f"{scores.moderate_recommend_rate * 100:.1f}%",
                "说明": "UCloud被推荐的响应比例",
            },
            "情感值": {
                "值": scores.sentiment_score,
                "标签": "正面" if scores.sentiment_score > 0.6 else ("负面" if scores.sentiment_score < 0.4 else "中性"),
                "说明": "UCloud被提及时的平均情感倾向",
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
