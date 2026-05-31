"""
UCloud GEO 评估 - 搜索结果导入适配器
将 Deep Research 等外部搜索结果导入评估框架，
转换为标准 AnalysisResult 格式，参与指标计算。

用法:
    # 从JSON文件导入
    python import_search_results.py --file search_results.json

    # 从命令行参数导入单条结果
    python import_search_results.py --model deepseek --question "推荐国内云服务器" --response "..."
"""
import os
import sys
import json
import argparse

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from analyzer import ResponseAnalyzer, AnalysisResult
from metrics import MetricsCalculator
from config import MODELS, BRAND_KEYWORDS


def parse_search_result(model_key: str, question: str, response_text: str,
                        question_id: str = "search_01",
                        analyzer: ResponseAnalyzer = None) -> AnalysisResult:
    """
    将搜索结果转换为标准 AnalysisResult

    Args:
        model_key: 模型标识 (deepseek/ernie/doubao/kimi/qwen)
        question: 评估问题
        response_text: 模型回答文本
        question_id: 问题ID
        analyzer: 分析器实例
    """
    if analyzer is None:
        analyzer = ResponseAnalyzer()

    model_name = MODELS.get(model_key, {}).get("name", model_key)

    result = analyzer.analyze(
        question_id=question_id,
        model_key=model_key,
        model_name=model_name,
        content=response_text,
    )

    return result


def import_from_file(filepath: str) -> dict:
    """
    从JSON文件批量导入搜索结果

    JSON格式:
    {
        "results": [
            {
                "model": "deepseek",
                "question": "推荐国内云服务器",
                "response": "根据我的了解，国内主流云服务商...",
                "question_id": "search_01"
            },
            ...
        ]
    }
    """
    analyzer = ResponseAnalyzer()
    calculator = MetricsCalculator()

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_results = {}

    for item in data.get("results", []):
        model_key = item.get("model", "unknown")
        question = item.get("question", "")
        response = item.get("response", "")
        question_id = item.get("question_id", "search_00")

        result = parse_search_result(
            model_key=model_key,
            question=question,
            response_text=response,
            question_id=question_id,
            analyzer=analyzer,
        )

        if model_key not in all_results:
            all_results[model_key] = []
        all_results[model_key].append(result)

    # 计算指标
    comparisons = calculator.compare_models(all_results)

    # 输出结果
    print("\n" + "=" * 80)
    print("UCloud GEO 搜索结果评估")
    print("=" * 80)

    for comp in comparisons:
        s = comp.scores
        print(f"\n{comp.model_name}:")
        print(f"  GEO综合得分: {s.geo_score}")
        print(f"  覆盖率: {s.coverage_rate * 100:.1f}%")
        print(f"  提及率: {s.mention_rate:.2f}")
        print(f"  引用率: {s.citation_rate * 100:.1f}%")
        print(f"  推荐率: {s.recommendation_rate * 100:.1f}%")
        print(f"  情感值: {s.sentiment_score:.2f}")

    return all_results


def import_from_text(model_key: str, question: str, response_text: str) -> AnalysisResult:
    """从命令行参数导入单条结果"""
    analyzer = ResponseAnalyzer()
    result = parse_search_result(model_key, question, response_text, analyzer=analyzer)

    print(f"\n{'='*50}")
    print(f"模型: {result.model_name}")
    print(f"问题: {question[:50]}...")
    print(f"{'='*50}")
    print(f"  UCloud提及: {'是 (x' + str(result.ucloud_mention_count) + ')' if result.ucloud_mentioned else '否'}")
    print(f"  引用: {'是' if result.has_citation else '否'}")
    print(f"  推荐: {'是 (' + result.ucloud_recommendation_strength + ')' if result.ucloud_recommended else '否'}")
    print(f"  情感: {result.sentiment_score} ({result.sentiment_label})")
    print(f"  排名: {result.ucloud_rank or 'N/A'}")
    print(f"  位置权重: {result.position_weight}")

    return result


def main():
    parser = argparse.ArgumentParser(description="UCloud GEO 搜索结果导入")
    parser.add_argument("--file", type=str, help="JSON文件路径")
    parser.add_argument("--model", type=str, help="模型标识")
    parser.add_argument("--question", type=str, help="评估问题")
    parser.add_argument("--response", type=str, help="模型回答文本")
    args = parser.parse_args()

    if args.file:
        import_from_file(args.file)
    elif args.model and args.question and args.response:
        import_from_text(args.model, args.question, args.response)
    else:
        print("用法:")
        print("  python import_search_results.py --file search_results.json")
        print("  python import_search_results.py --model deepseek --question '推荐云服务器' --response '...'")


if __name__ == "__main__":
    main()
