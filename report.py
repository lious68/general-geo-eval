"""
UCloud GEO 评估框架 - 报告生成与可视化
生成HTML报告、Excel数据表、图表等
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

from config import OUTPUT_DIR, REPORTS_DIR, CHARTS_DIR
from metrics import GEOScores, ModelComparison, CategoryScores, MetricsCalculator
from analyzer import AnalysisResult

logger = logging.getLogger(__name__)


class ReportGenerator:
    """报告生成器"""

    def __init__(self):
        self.calculator = MetricsCalculator()

    def generate_full_report(
        self,
        all_results: Dict[str, List[AnalysisResult]],
        categories: Dict[str, List[str]] = None,
        question_types: Dict[str, List[str]] = None,
    ) -> str:
        """生成完整评估报告"""
        # 1. 跨模型对比
        comparisons = self.calculator.compare_models(all_results, categories)

        # 2. 生成数据
        report_data = {
            "title": "UCloud GEO 评估报告",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": self._generate_summary(comparisons),
            "model_comparison": self._generate_model_comparison(comparisons),
            "category_analysis": self._generate_category_analysis(comparisons),
            "detail_table": self._generate_detail_table(all_results),
            "recommendations": self._generate_recommendations(comparisons),
        }

        # 3. 保存JSON
        json_path = os.path.join(REPORTS_DIR, "geo_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)

        # 4. 生成HTML报告
        html_path = self._generate_html_report(report_data, comparisons)

        # 5. 生成Excel
        excel_path = self._generate_excel(all_results, comparisons)

        # 6. 生成图表
        self._generate_charts(comparisons, all_results)

        logger.info(f"Report generated: {html_path}")
        return html_path

    def _generate_summary(self, comparisons: List[ModelComparison]) -> Dict:
        """生成摘要"""
        if not comparisons:
            return {}

        # 找出各指标最佳模型
        best_coverage = max(comparisons, key=lambda x: x.scores.coverage_rate)
        best_mention = max(comparisons, key=lambda x: x.scores.mention_rate)
        best_citation = max(comparisons, key=lambda x: x.scores.citation_rate)
        best_recommendation = max(comparisons, key=lambda x: x.scores.recommendation_rate)
        best_sentiment = max(comparisons, key=lambda x: x.scores.sentiment_score)
        best_geo = max(comparisons, key=lambda x: x.scores.geo_score)

        return {
            "total_models": len(comparisons),
            "best_geo_score": {
                "model": best_geo.model_name,
                "score": best_geo.scores.geo_score,
            },
            "best_coverage": {
                "model": best_coverage.model_name,
                "value": f"{best_coverage.scores.coverage_rate * 100:.1f}%",
            },
            "best_mention": {
                "model": best_mention.model_name,
                "value": best_mention.scores.mention_rate,
            },
            "best_citation": {
                "model": best_citation.model_name,
                "value": f"{best_citation.scores.citation_rate * 100:.1f}%",
            },
            "best_recommendation": {
                "model": best_recommendation.model_name,
                "value": f"{best_recommendation.scores.recommendation_rate * 100:.1f}%",
            },
            "best_sentiment": {
                "model": best_sentiment.model_name,
                "value": best_sentiment.scores.sentiment_score,
            },
        }

    def _generate_model_comparison(self, comparisons: List[ModelComparison]) -> List[Dict]:
        """生成模型对比数据"""
        rows = []
        for comp in comparisons:
            rows.append({
                "排名": comparisons.index(comp) + 1,
                "模型": comp.model_name,
                "GEO综合得分": comp.scores.geo_score,
                "覆盖率": f"{comp.scores.coverage_rate * 100:.1f}%",
                "提及率": comp.scores.mention_rate,
                "引用率": f"{comp.scores.citation_rate * 100:.1f}%",
                "推荐率": f"{comp.scores.recommendation_rate * 100:.1f}%",
                "情感值": comp.scores.sentiment_score,
                "平均排名": comp.scores.avg_rank,
            })
        return rows

    def _generate_category_analysis(self, comparisons: List[ModelComparison]) -> Dict:
        """生成品类分析"""
        category_data = {}
        for comp in comparisons:
            for cat_score in comp.category_scores:
                cat = cat_score.category
                if cat not in category_data:
                    category_data[cat] = {}
                category_data[cat][comp.model_name] = {
                    "GEO得分": cat_score.scores.geo_score,
                    "覆盖率": f"{cat_score.scores.coverage_rate * 100:.1f}%",
                    "推荐率": f"{cat_score.scores.recommendation_rate * 100:.1f}%",
                }
        return category_data

    def _generate_detail_table(self, all_results: Dict[str, List[AnalysisResult]]) -> List[Dict]:
        """生成详细数据表"""
        rows = []
        for model_key, results in all_results.items():
            for r in results:
                rows.append({
                    "模型": r.model_name,
                    "问题ID": r.question_id,
                    "是否提及UCloud": "是" if r.ucloud_mentioned else "否",
                    "提及次数": r.ucloud_mention_count,
                    "是否引用": "是" if r.has_citation else "否",
                    "是否推荐": "是" if r.ucloud_recommended else "否",
                    "推荐强度": r.ucloud_recommendation_strength,
                    "情感分数": r.sentiment_score,
                    "情感标签": r.sentiment_label,
                    "排名": r.ucloud_rank,
                    "位置权重": r.position_weight,
                    "响应长度": r.response_length,
                    "是否有错误": "是" if r.has_error else "否",
                })
        return rows

    def _generate_recommendations(self, comparisons: List[ModelComparison]) -> List[str]:
        """生成优化建议"""
        recs = []

        # 分析整体情况
        if comparisons:
            top = comparisons[0]
            overall_coverage = top.scores.coverage_rate

            if overall_coverage < 0.3:
                recs.append("🔴 覆盖率严重不足：UCloud在AI模型回答中被提及的比例低于30%，"
                           "建议加强在技术博客、开发者社区、百科词条等AI训练数据来源中的内容布局。")

            if overall_coverage < 0.5:
                recs.append("🟡 覆盖率有待提升：建议在知乎、CSDN、掘金等技术社区增加UCloud产品评测和使用教程。")

            # 情感分析建议
            avg_sentiment = np.mean([c.scores.sentiment_score for c in comparisons])
            if avg_sentiment < 0.5:
                recs.append("🔴 情感倾向偏负面：AI模型对UCloud的评价偏消极，"
                           "建议关注并改善用户评价和口碑。")
            elif avg_sentiment < 0.6:
                recs.append("🟡 情感倾向中性偏正：可以加强正面案例和成功故事的传播。")

            # 推荐率建议
            avg_rec = np.mean([c.scores.recommendation_rate for c in comparisons])
            if avg_rec < 0.2:
                recs.append("🔴 推荐率较低：AI模型较少主动推荐UCloud，"
                           "建议在对比评测、选型指南类内容中突出UCloud的差异化优势。")

            # 引用率建议
            avg_cite = np.mean([c.scores.citation_rate for c in comparisons])
            if avg_cite < 0.1:
                recs.append("🟡 引用率偏低：AI模型很少引用UCloud官方数据或链接，"
                           "建议发布更多公开数据报告、白皮书等可引用内容。")

        recs.append("💡 通用建议：")
        recs.append("  - 在技术社区（CSDN、知乎、掘金）发布高质量技术文章")
        recs.append("  - 制作产品对比评测视频和图文内容")
        recs.append("  - 完善百度百科、维基百科等百科词条")
        recs.append("  - 发布行业报告和白皮书，提供可引用的数据")
        recs.append("  - 鼓励用户在社区分享使用体验")
        recs.append("  - 优化官网SEO，确保产品页面信息完整且结构化")

        return recs

    def _generate_html_report(self, report_data: Dict, comparisons: List[ModelComparison]) -> str:
        """生成HTML可视化报告"""
        html = self._build_html(report_data, comparisons)
        html_path = os.path.join(REPORTS_DIR, "geo_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return html_path

    def _build_html(self, report_data: Dict, comparisons: List[ModelComparison]) -> str:
        """构建HTML报告内容"""
        summary = report_data["summary"]
        model_rows = report_data["model_comparison"]
        category_data = report_data["category_analysis"]
        recommendations = report_data["recommendations"]

        # 模型对比表格行
        model_table_rows = ""
        for row in model_rows:
            rank_badge = {1: "🥇", 2: "🥈", 3: "🥉"}.get(row["排名"], f"#{row['排名']}")
            model_table_rows += f"""
            <tr>
                <td>{rank_badge}</td>
                <td><strong>{row['模型']}</strong></td>
                <td class="score">{row['GEO综合得分']}</td>
                <td>{row['覆盖率']}</td>
                <td>{row['提及率']}</td>
                <td>{row['引用率']}</td>
                <td>{row['推荐率']}</td>
                <td>{row['情感值']}</td>
                <td>{row['平均排名']}</td>
            </tr>"""

        # 品类分析表格
        category_sections = ""
        for cat, models in category_data.items():
            rows = ""
            for model_name, data in models.items():
                rows += f"""
                <tr>
                    <td>{model_name}</td>
                    <td class="score">{data['GEO得分']}</td>
                    <td>{data['覆盖率']}</td>
                    <td>{data['推荐率']}</td>
                </tr>"""
            category_sections += f"""
            <div class="category-card">
                <h3>{cat}</h3>
                <table>
                    <thead><tr><th>模型</th><th>GEO得分</th><th>覆盖率</th><th>推荐率</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>"""

        # 建议列表
        rec_items = ""
        for rec in recommendations:
            rec_items += f"<li>{rec}</li>"

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_data['title']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: white;
            padding: 40px;
            border-radius: 16px;
            margin-bottom: 30px;
            text-align: center;
        }}
        .header h1 {{ font-size: 32px; margin-bottom: 10px; }}
        .header .subtitle {{ font-size: 16px; opacity: 0.8; }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            text-align: center;
        }}
        .summary-card .label {{ font-size: 14px; color: #666; margin-bottom: 8px; }}
        .summary-card .value {{ font-size: 28px; font-weight: 700; color: #1a1a2e; }}
        .summary-card .model {{ font-size: 13px; color: #0f3460; margin-top: 4px; }}
        .section {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .section h2 {{
            font-size: 22px;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 2px solid #eef2f7;
            color: #1a1a2e;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th {{
            background: #f8f9fc;
            padding: 12px 16px;
            text-align: left;
            font-weight: 600;
            color: #444;
            border-bottom: 2px solid #eef2f7;
        }}
        td {{
            padding: 12px 16px;
            border-bottom: 1px solid #f0f2f5;
        }}
        tr:hover {{ background: #f8f9fc; }}
        .score {{ font-weight: 700; color: #0f3460; font-size: 16px; }}
        .category-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 16px;
        }}
        .category-card {{
            background: #f8f9fc;
            border-radius: 10px;
            padding: 20px;
        }}
        .category-card h3 {{ font-size: 16px; margin-bottom: 12px; color: #1a1a2e; }}
        .recommendations ul {{
            list-style: none;
            padding: 0;
        }}
        .recommendations li {{
            padding: 10px 16px;
            margin-bottom: 8px;
            background: #f8f9fc;
            border-radius: 8px;
            border-left: 4px solid #0f3460;
        }}
        .chart-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .chart-container img {{
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 {report_data['title']}</h1>
            <div class="subtitle">生成时间：{report_data['date']}</div>
        </div>

        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">最佳GEO得分</div>
                <div class="value">{summary.get('best_geo_score', {}).get('score', 'N/A')}</div>
                <div class="model">{summary.get('best_geo_score', {}).get('model', '')}</div>
            </div>
            <div class="summary-card">
                <div class="label">最高覆盖率</div>
                <div class="value">{summary.get('best_coverage', {}).get('value', 'N/A')}</div>
                <div class="model">{summary.get('best_coverage', {}).get('model', '')}</div>
            </div>
            <div class="summary-card">
                <div class="label">最高推荐率</div>
                <div class="value">{summary.get('best_recommendation', {}).get('value', 'N/A')}</div>
                <div class="model">{summary.get('best_recommendation', {}).get('model', '')}</div>
            </div>
            <div class="summary-card">
                <div class="label">最高情感值</div>
                <div class="value">{summary.get('best_sentiment', {}).get('value', 'N/A')}</div>
                <div class="model">{summary.get('best_sentiment', {}).get('model', '')}</div>
            </div>
        </div>

        <div class="section">
            <h2>📊 模型对比排名</h2>
            <table>
                <thead>
                    <tr>
                        <th>排名</th><th>模型</th><th>GEO得分</th>
                        <th>覆盖率</th><th>提及率</th><th>引用率</th>
                        <th>推荐率</th><th>情感值</th><th>平均排名</th>
                    </tr>
                </thead>
                <tbody>{model_table_rows}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>📂 品类分析</h2>
            <div class="category-grid">{category_sections}</div>
        </div>

        <div class="section chart-container">
            <h2>📈 可视化图表</h2>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px">
                <div><h4>GEO综合得分对比</h4><img src="../charts/geo_scores.png" alt="GEO Scores" style="width:100%"></div>
                <div><h4>多维度雷达图</h4><img src="../charts/radar_chart.png" alt="Radar Chart" style="width:100%"></div>
                <div><h4>核心指标对比</h4><img src="../charts/coverage_comparison.png" alt="Coverage" style="width:100%"></div>
                <div><h4>情感分布</h4><img src="../charts/sentiment_distribution.png" alt="Sentiment" style="width:100%"></div>
            </div>
        </div>

        <div class="section recommendations">
            <h2>💡 优化建议</h2>
            <ul>{rec_items}</ul>
        </div>

        <div class="footer">
            UCloud GEO Evaluation System · Powered by Claude Code
        </div>
    </div>
</body>
</html>"""
        return html

    def _generate_excel(self, all_results: Dict[str, List[AnalysisResult]],
                        comparisons: List[ModelComparison]) -> str:
        """生成Excel数据表"""
        excel_path = os.path.join(REPORTS_DIR, "geo_data.xlsx")

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            # Sheet 1: 模型对比总览
            comp_data = []
            for comp in comparisons:
                comp_data.append({
                    "排名": comparisons.index(comp) + 1,
                    "模型": comp.model_name,
                    "GEO综合得分": comp.scores.geo_score,
                    "覆盖率": comp.scores.coverage_rate,
                    "提及率": comp.scores.mention_rate,
                    "引用率": comp.scores.citation_rate,
                    "推荐率": comp.scores.recommendation_rate,
                    "强推荐率": comp.scores.strong_recommend_rate,
                    "情感值": comp.scores.sentiment_score,
                    "平均排名": comp.scores.avg_rank,
                    "位置权重": comp.scores.avg_position_weight,
                })
            pd.DataFrame(comp_data).to_excel(writer, sheet_name="模型对比", index=False)

            # Sheet 2: 详细数据
            detail_data = report_data = self._generate_detail_table(all_results)
            pd.DataFrame(detail_data).to_excel(writer, sheet_name="详细数据", index=False)

            # Sheet 3: 品类分析
            cat_data = []
            for comp in comparisons:
                for cat_score in comp.category_scores:
                    cat_data.append({
                        "模型": comp.model_name,
                        "品类": cat_score.category,
                        "GEO得分": cat_score.scores.geo_score,
                        "覆盖率": cat_score.scores.coverage_rate,
                        "推荐率": cat_score.scores.recommendation_rate,
                        "情感值": cat_score.scores.sentiment_score,
                    })
            if cat_data:
                pd.DataFrame(cat_data).to_excel(writer, sheet_name="品类分析", index=False)

        return excel_path

    def _generate_charts(self, comparisons: List[ModelComparison],
                         all_results: Dict[str, List[AnalysisResult]]):
        """生成可视化图表"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
        except ImportError:
            logger.warning("matplotlib not available, skipping chart generation")
            return

        # 图表1: 各模型GEO综合得分对比
        self._chart_geo_scores(comparisons)

        # 图表2: 各指标雷达图
        self._chart_radar(comparisons)

        # 图表3: 覆盖率对比
        self._chart_coverage(comparisons)

        # 图表4: 情感分布
        self._chart_sentiment(all_results)

    def _chart_geo_scores(self, comparisons: List[ModelComparison]):
        """GEO综合得分柱状图"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        names = [c.model_name for c in comparisons]
        scores = [c.scores.geo_score for c in comparisons]

        fig, ax = plt.subplots(figsize=(10, 6))
        colors = ["#0f3460", "#16213e", "#1a1a2e", "#533483", "#e94560"]
        bars = ax.bar(names, scores, color=colors[:len(names)], width=0.6, edgecolor="white")

        for bar, score in zip(bars, scores):
            ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + 1,
                    f"{score:.1f}", ha="center", va="bottom", fontweight="bold", fontsize=14)

        ax.set_title("UCloud GEO 综合得分 - 各模型对比", fontsize=16, fontweight="bold", pad=20)
        ax.set_ylabel("GEO Score", fontsize=13)
        ax.set_ylim(0, max(scores) * 1.2 + 5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        path = os.path.join(CHARTS_DIR, "geo_scores.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()

    def _chart_radar(self, comparisons: List[ModelComparison]):
        """各指标雷达图"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        categories = ["覆盖率", "提及率", "引用率", "推荐率", "情感值"]
        N = len(categories)
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        colors = ["#0f3460", "#e94560", "#533483", "#f5a623", "#7ed321"]

        for i, comp in enumerate(comparisons):
            values = [
                comp.scores.coverage_rate,
                min(comp.scores.mention_rate / 3.0, 1.0),
                comp.scores.citation_rate,
                comp.scores.recommendation_rate,
                comp.scores.sentiment_score,
            ]
            values += values[:1]
            ax.plot(angles, values, "o-", linewidth=2, label=comp.model_name,
                    color=colors[i % len(colors)])
            ax.fill(angles, values, alpha=0.1, color=colors[i % len(colors)])

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=12)
        ax.set_ylim(0, 1)
        ax.set_title("UCloud GEO 多维度雷达图", fontsize=16, fontweight="bold", y=1.08)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=11)

        plt.tight_layout()
        path = os.path.join(CHARTS_DIR, "radar_chart.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()

    def _chart_coverage(self, comparisons: List[ModelComparison]):
        """覆盖率分组柱状图"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        names = [c.model_name for c in comparisons]
        metrics = {
            "覆盖率": [c.scores.coverage_rate * 100 for c in comparisons],
            "引用率": [c.scores.citation_rate * 100 for c in comparisons],
            "推荐率": [c.scores.recommendation_rate * 100 for c in comparisons],
        }

        x = np.arange(len(names))
        width = 0.25
        colors = ["#0f3460", "#e94560", "#533483"]

        fig, ax = plt.subplots(figsize=(12, 6))
        for i, (label, values) in enumerate(metrics.items()):
            bars = ax.bar(x + i * width, values, width, label=label, color=colors[i])
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + 0.5,
                        f"{val:.1f}%", ha="center", va="bottom", fontsize=10)

        ax.set_title("UCloud GEO 核心指标对比", fontsize=16, fontweight="bold", pad=20)
        ax.set_ylabel("百分比 (%)", fontsize=13)
        ax.set_xticks(x + width)
        ax.set_xticklabels(names, fontsize=12)
        ax.legend(fontsize=12)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        path = os.path.join(CHARTS_DIR, "coverage_comparison.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()

    def _chart_sentiment(self, all_results: Dict[str, List[AnalysisResult]]):
        """情感分布图"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))

        model_names = []
        sentiment_data = {"positive": [], "neutral": [], "negative": []}

        for model_key, results in all_results.items():
            if not results:
                continue
            name = results[0].model_name
            model_names.append(name)
            mentioned = [r for r in results if r.ucloud_mentioned and not r.has_error]
            total = len(mentioned) if mentioned else 1
            sentiment_data["positive"].append(
                sum(1 for r in mentioned if r.sentiment_label == "positive") / total * 100
            )
            sentiment_data["neutral"].append(
                sum(1 for r in mentioned if r.sentiment_label == "neutral") / total * 100
            )
            sentiment_data["negative"].append(
                sum(1 for r in mentioned if r.sentiment_label == "negative") / total * 100
            )

        x = np.arange(len(model_names))
        width = 0.6

        p1 = ax.bar(x, sentiment_data["positive"], width, label="正面", color="#7ed321")
        p2 = ax.bar(x, sentiment_data["neutral"], width,
                     bottom=sentiment_data["positive"], label="中性", color="#f5a623")
        p3 = ax.bar(x, sentiment_data["negative"], width,
                     bottom=[a + b for a, b in zip(sentiment_data["positive"], sentiment_data["neutral"])],
                     label="负面", color="#e94560")

        ax.set_title("UCloud 情感分布 - 各模型对比", fontsize=16, fontweight="bold", pad=20)
        ax.set_ylabel("百分比 (%)", fontsize=13)
        ax.set_xticks(x)
        ax.set_xticklabels(model_names, fontsize=12)
        ax.legend(fontsize=12)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        plt.tight_layout()
        path = os.path.join(CHARTS_DIR, "sentiment_distribution.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
