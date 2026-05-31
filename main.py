"""
UCloud GEO 评估框架 - 主执行脚本
用法:
    python main.py                    # 完整评估（需要API keys）
    python main.py --demo             # 演示模式（使用模拟数据）
    python main.py --models deepseek qwen  # 只评估指定模型
    python main.py --quick            # 快速评估（前10题）
"""
import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime

# Windows 终端 UTF-8 编码修复
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from typing import Dict, List

from config import MODELS, OUTPUT_DIR, RAW_RESPONSES_DIR, REPORTS_DIR
from questions import QUESTIONS, get_categories, get_question_types, EvalQuestion
from model_clients import create_all_clients, query_all_models, ModelClient
from analyzer import ResponseAnalyzer, AnalysisResult
from metrics import MetricsCalculator, GEOScores
from report import ReportGenerator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(OUTPUT_DIR, "eval.log"), encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


class GEOEvaluator:
    """GEO评估执行器"""

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode
        self.analyzer = ResponseAnalyzer()
        self.calculator = MetricsCalculator()
        self.report_generator = ReportGenerator()
        self.clients: Dict[str, ModelClient] = {}
        self.all_results: Dict[str, List[AnalysisResult]] = {}

    def initialize(self, model_keys: List[str] = None):
        """初始化模型客户端"""
        if self.demo_mode:
            logger.info("🎮 演示模式：使用模拟数据")
            return

        self.clients = create_all_clients()

        # 过滤模型
        if model_keys:
            self.clients = {k: v for k, v in self.clients.items() if k in model_keys}

        # 检查可用模型
        available = {k: v for k, v in self.clients.items() if v.is_configured}
        if not available:
            logger.error("❌ 没有可用的模型！请在 .env 文件中配置 API keys")
            logger.info("复制 .env.example 为 .env 并填入你的 API keys")
            sys.exit(1)

        logger.info(f"✅ 可用模型: {', '.join(v.name for v in available.values())}")
        # 移除未配置的模型
        self.clients = available

    def run_evaluation(self, questions: List[EvalQuestion] = None,
                       delay: float = 1.0) -> Dict[str, List[AnalysisResult]]:
        """执行评估"""
        if questions is None:
            questions = QUESTIONS

        logger.info(f"🚀 开始评估，共 {len(questions)} 个问题")

        if self.demo_mode:
            return self._run_demo(questions)

        all_results = {}

        for model_key, client in self.clients.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"📊 评估模型: {client.name}")
            logger.info(f"{'='*60}")

            model_results = []

            for i, q in enumerate(questions):
                logger.info(f"  [{i+1}/{len(questions)}] Q:{q.id} - {q.question[:50]}...")

                # 发送请求
                response = client.chat(q.question)
                time.sleep(delay)  # 避免限频

                # 保存原始响应
                self._save_raw_response(model_key, q.id, response)

                # 分析响应
                analysis = self.analyzer.analyze(
                    question_id=q.id,
                    model_key=model_key,
                    model_name=client.name,
                    content=response.get("content", ""),
                    error=response.get("error"),
                )
                model_results.append(analysis)

                # 简要输出
                if analysis.ucloud_mentioned:
                    logger.info(f"    ✅ 提及UCloud (x{analysis.ucloud_mention_count}), "
                               f"推荐: {analysis.ucloud_recommendation_strength}, "
                               f"情感: {analysis.sentiment_label}")
                else:
                    logger.info(f"    ❌ 未提及UCloud")

            all_results[model_key] = model_results

        self.all_results = all_results
        return all_results

    def _run_demo(self, questions: List[EvalQuestion]) -> Dict[str, List[AnalysisResult]]:
        """演示模式：使用模拟数据"""
        import random
        random.seed(42)

        all_results = {}

        demo_models = list(MODELS.keys())

        for model_key in demo_models:
            model_name = MODELS[model_key]["name"]
            model_results = []

            # 不同模型有不同的UCloud提及概率（模拟真实差异）
            mention_probs = {
                "deepseek": 0.55,   # DeepSeek 对国内云厂商覆盖较全
                "ernie": 0.45,      # 文心偏向百度生态
                "doubao": 0.40,     # 豆包偏向字节生态
                "kimi": 0.50,       # Kimi 较中立
                "qwen": 0.60,       # 通义千问对国内厂商覆盖较好
            }
            mention_prob = mention_probs.get(model_key, 0.5)
            recommend_prob = mention_prob * 0.4  # 被推荐的概率约为提及概率的40%

            for q in questions:
                mentioned = random.random() < mention_prob
                recommended = mentioned and random.random() < recommend_prob
                cited = mentioned and random.random() < 0.15  # 引用率通常较低

                if mentioned:
                    mention_count = random.randint(1, 4)
                    first_pos = random.randint(0, max(1, int(random.gauss(200, 100))))
                    sentiment_score = round(random.gauss(0.6, 0.15), 4)
                    sentiment_score = max(0.1, min(0.95, sentiment_score))
                    sentiment_label = "positive" if sentiment_score > 0.6 else ("negative" if sentiment_score < 0.4 else "neutral")
                    position_weight = 1.5 if first_pos < 100 else (1.2 if first_pos < 200 else (1.0 if first_pos < 400 else 0.8))
                    rank = random.randint(1, 5)

                    rec_strength = "none"
                    if recommended:
                        rec_strength = random.choice(["strong", "moderate", "comparison_win"])
                else:
                    mention_count = 0
                    first_pos = None
                    sentiment_score = 0.5
                    sentiment_label = "neutral"
                    position_weight = 0.0
                    rank = None
                    rec_strength = "none"

                analysis = AnalysisResult(
                    question_id=q.id,
                    model_key=model_key,
                    model_name=model_name,
                    response_length=random.randint(300, 2000),
                    has_error=False,
                    ucloud_mentioned=mentioned,
                    ucloud_mention_count=mention_count,
                    ucloud_first_position=first_pos,
                    ucloud_rank=rank,
                    has_citation=cited,
                    citation_count=1 if cited else 0,
                    ucloud_recommended=recommended,
                    ucloud_recommendation_strength=rec_strength,
                    sentiment_score=sentiment_score,
                    sentiment_label=sentiment_label,
                    position_weight=position_weight,
                    raw_content=f"[模拟响应] {q.question}",
                )
                model_results.append(analysis)

            all_results[model_key] = model_results

        self.all_results = all_results
        return all_results

    def generate_report(self) -> str:
        """生成评估报告"""
        if not self.all_results:
            logger.error("没有评估结果，请先运行评估")
            return ""

        # 构建品类映射
        categories = {}
        for q in QUESTIONS:
            if q.category not in categories:
                categories[q.category] = []
            categories[q.category].append(q.id)

        # 生成报告
        report_path = self.report_generator.generate_full_report(
            self.all_results,
            categories=categories,
        )

        return report_path

    def print_summary(self):
        """打印评估摘要"""
        if not self.all_results:
            return

        print("\n" + "=" * 80)
        print("🎯 UCloud GEO 评估结果摘要")
        print("=" * 80)

        comparisons = self.calculator.compare_models(self.all_results)

        print(f"\n{'排名':<6}{'模型':<12}{'GEO得分':<10}{'覆盖率':<10}{'提及率':<10}"
              f"{'引用率':<10}{'推荐率':<10}{'情感值':<10}{'平均排名':<10}")
        print("-" * 86)

        for i, comp in enumerate(comparisons, 1):
            badge = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f" #{i}")
            s = comp.scores
            print(f"{badge:<6}{comp.model_name:<12}{s.geo_score:<10.1f}"
                  f"{s.coverage_rate*100:<9.1f}%"
                  f"{s.mention_rate:<10.2f}"
                  f"{s.citation_rate*100:<9.1f}%"
                  f"{s.recommendation_rate*100:<9.1f}%"
                  f"{s.sentiment_score:<10.2f}"
                  f"{s.avg_rank:<10.1f}")

        # 各模型评分卡
        for comp in comparisons:
            scorecard = self.calculator.generate_scorecard(comp.scores)
            print(f"\n{'─'*40}")
            print(f"📊 {comp.model_name} 评分卡")
            print(f"{'─'*40}")
            print(f"  GEO综合得分: {scorecard['GEO综合得分']}")
            print(f"  覆盖率: {scorecard['覆盖率']['百分比']} - {scorecard['覆盖率']['说明']}")
            print(f"  推荐率: {scorecard['推荐率']['百分比']} (强推荐: {scorecard['推荐率']['强推荐率']})")
            print(f"  情感值: {scorecard['情感值']['值']} ({scorecard['情感值']['标签']})")

    def _save_raw_response(self, model_key: str, question_id: str, response: Dict):
        """保存原始响应到文件"""
        filename = f"{model_key}_{question_id}.json"
        filepath = os.path.join(RAW_RESPONSES_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="UCloud GEO 评估框架")
    parser.add_argument("--demo", action="store_true", help="演示模式（使用模拟数据）")
    parser.add_argument("--models", nargs="+", help="指定评估的模型 (deepseek, ernie, doubao, kimi, qwen)")
    parser.add_argument("--quick", action="store_true", help="快速评估（仅前10题）")
    parser.add_argument("--delay", type=float, default=1.0, help="API请求间隔（秒）")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    # 选择问题集
    questions = QUESTIONS
    if args.quick:
        questions = QUESTIONS[:10]
        logger.info(f"⚡ 快速模式：仅评估前 {len(questions)} 题")

    # 创建评估器
    evaluator = GEOEvaluator(demo_mode=args.demo)
    evaluator.initialize(model_keys=args.models)

    # 执行评估
    start_time = time.time()
    results = evaluator.run_evaluation(questions, delay=args.delay)
    elapsed = time.time() - start_time

    # 打印摘要
    evaluator.print_summary()

    # 生成报告
    report_path = evaluator.generate_report()

    print(f"\n{'='*80}")
    print(f"✅ 评估完成！耗时 {elapsed:.1f} 秒")
    print(f"📄 HTML报告: {report_path}")
    print(f"📊 Excel数据: {os.path.join(REPORTS_DIR, 'geo_data.xlsx')}")
    print(f"📈 图表目录: {os.path.join(OUTPUT_DIR, 'charts')}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
