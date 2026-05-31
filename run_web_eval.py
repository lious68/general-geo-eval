"""
UCloud GEO 评估 - 基于Web搜索真实数据的评估
将搜索结果导入框架，生成完整报告
"""
import os
import sys
import json

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from questions import QUESTIONS, get_categories
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator
from report import ReportGenerator


def main():
    # 读取真实搜索数据
    data_file = os.path.join(os.path.dirname(__file__), "output", "reports", "web_research_report.json")
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    analyzer = ResponseAnalyzer()
    calculator = MetricsCalculator()
    report_gen = ReportGenerator()

    all_results = {}

    for item in data.get("results", []):
        model_key = item.get("model", "unknown")
        question = item.get("question", "")
        response = item.get("response", "")
        question_id = item.get("question_id", "web_00")

        result = analyzer.analyze(
            question_id=question_id,
            model_key=model_key,
            model_name={"deepseek": "DeepSeek", "ernie": "文心一言", "doubao": "豆包",
                       "kimi": "Kimi", "qwen": "通义千问"}.get(model_key, model_key),
            content=response,
        )

        if model_key not in all_results:
            all_results[model_key] = []
        all_results[model_key].append(result)

    # 构建品类映射
    categories = {}
    for q in QUESTIONS:
        if q.category not in categories:
            categories[q.category] = []
        categories[q.category].append(q.id)

    # 生成报告
    report_path = report_gen.generate_full_report(all_results, categories=categories)

    # 打印详细结果
    comparisons = calculator.compare_models(all_results)

    print("\n" + "=" * 90)
    print("🎯 UCloud GEO 真实数据评估结果（基于Web搜索）")
    print("=" * 90)

    print(f"\n{'排名':<6}{'模型':<12}{'GEO得分':<10}{'覆盖率':<10}{'提及率':<10}"
          f"{'引用率':<10}{'推荐率':<10}{'情感值':<10}")
    print("-" * 76)

    for i, comp in enumerate(comparisons, 1):
        badge = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f" #{i}")
        s = comp.scores
        print(f"{badge:<6}{comp.model_name:<12}{s.geo_score:<10.1f}"
              f"{s.coverage_rate*100:<9.1f}%"
              f"{s.mention_rate:<10.2f}"
              f"{s.citation_rate*100:<9.1f}%"
              f"{s.recommendation_rate*100:<9.1f}%"
              f"{s.sentiment_score:<10.2f}")

    print(f"\n📄 完整报告: {report_path}")
    return all_results


if __name__ == "__main__":
    main()
