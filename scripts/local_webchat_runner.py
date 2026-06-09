"""
本地 Playwright WebChat runner — 用于在本地运行无法通过 API 调用的模型评测

用法:
    python scripts/local_webchat_runner.py --models kimi ernie --questions all --output results.json

说明:
    - 使用 core/web_chat_clients.py 中的 Playwright 客户端
    - 使用 core/analyzer.py 中的 ResponseAnalyzer 分析响应
    - 输出格式与服务端 analysis_results + geo_scores 完全一致
    - 生成的 JSON 文件可通过前端「上传本地结果」功能导入服务器
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

# ── 常量 ──
SEP = "=" * 72
MODEL_NAMES = {
    "deepseek": "DeepSeek",
    "ernie": "文心一言",
    "doubao": "豆包",
    "kimi": "Kimi",
    "qwen": "千问",
}


def _setup_headed_mode(headed: bool):
    """控制浏览器是否显示窗口。

    WebChatClientBase.initialize() 检查 DISPLAY 环境变量：
    - 有 DISPLAY → headed（显示窗口）
    - 无 DISPLAY → headless（后台运行）
    Windows 默认无 DISPLAY，所以需要手动设置。
    """
    if headed:
        os.environ["DISPLAY"] = ":0"
        print("  🖥️  浏览器窗口模式已启用（能看到浏览器窗口）")
    else:
        print("  🌑 后台模式（不显示浏览器窗口）")


# 添加项目路径（必须在设置环境变量之后，因为 import 时会初始化客户端）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator
from analyzer import AnalysisResult
from database import get_questions as db_get_questions


def _analysis_to_dict(a) -> Dict:
    """AnalysisResult → dict (与 eval_runner._analysis_to_dict 一致)"""
    return {
        "question_id": a.question_id,
        "model_key": a.model_key,
        "model_name": a.model_name,
        "ucloud_mentioned": a.ucloud_mentioned,
        "ucloud_mention_count": a.ucloud_mention_count,
        "ucloud_rank": a.ucloud_rank,
        "has_citation": a.has_citation,
        "citation_count": a.citation_count,
        "ucloud_recommended": a.ucloud_recommended,
        "recommendation_strength": a.ucloud_recommendation_strength,
        "sentiment_score": a.sentiment_score,
        "sentiment_label": a.sentiment_label,
        "position_weight": a.position_weight,
        "response_length": a.response_length,
        "raw_content": a.raw_content,
        "competitor_mentions": {k: [{"keyword": m.keyword, "position": m.position} for m in v]
                                for k, v in a.competitor_mentions.items()},
        "citations": [{"citation_type": c.citation_type, "content": c.content,
                        "position": c.position, "source_channel": c.source_channel,
                        "is_ucloud": c.is_ucloud}
                       for c in a.citations],
        "all_cited_urls": [{"citation_type": c.citation_type, "content": c.content,
                            "position": c.position, "source_channel": c.source_channel,
                            "is_ucloud": c.is_ucloud}
                           for c in a.all_cited_urls],
        "error_message": a.error_message,
    }


def _empty_result(question_id: str, model_key: str, error: str) -> Dict:
    """空结果 (与 eval_runner._empty_result 一致)"""
    return {
        "question_id": question_id,
        "model_key": model_key,
        "model_name": MODEL_NAMES.get(model_key, model_key),
        "ucloud_mentioned": False,
        "ucloud_mention_count": 0,
        "ucloud_rank": None,
        "has_citation": False,
        "citation_count": 0,
        "ucloud_recommended": False,
        "recommendation_strength": "none",
        "sentiment_score": 0.5,
        "sentiment_label": "neutral",
        "position_weight": 0.0,
        "response_length": 0,
        "raw_content": "",
        "competitor_mentions": {},
        "citations": [],
        "all_cited_urls": [],
        "error_message": error,
    }


def _scores_to_dict(s) -> Dict:
    """GEOScores → dict (与 eval_runner._scores_to_dict 一致)"""
    return {
        "geo_score": s.geo_score,
        "coverage_rate": s.coverage_rate,
        "mention_rate": s.mention_rate,
        "citation_rate": s.citation_rate,
        "recommendation_rate": s.recommendation_rate,
        "sentiment_score": s.sentiment_score,
        "avg_rank": s.avg_rank,
        "total_questions": s.total_questions,
        "valid_responses": s.valid_responses,
    }


def _dict_to_analysis(d: Dict):
    """dict → AnalysisResult (与 eval_runner._dict_to_analysis 一致)"""
    return AnalysisResult(
        question_id=d["question_id"],
        model_key=d["model_key"],
        model_name=d["model_name"],
        ucloud_mentioned=bool(d["ucloud_mentioned"]),
        ucloud_mention_count=d["ucloud_mention_count"],
        ucloud_rank=d.get("ucloud_rank"),
        has_citation=bool(d["has_citation"]),
        citation_count=d["citation_count"],
        ucloud_recommended=bool(d["ucloud_recommended"]),
        ucloud_recommendation_strength=d["recommendation_strength"],
        sentiment_score=d["sentiment_score"],
        sentiment_label=d["sentiment_label"],
        position_weight=d["position_weight"],
        response_length=d["response_length"],
        raw_content=d.get("raw_content", ""),
    )


# ── 主逻辑 ──

async def run_local_eval(
    model_keys: List[str],
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    delay: float = 8.0,
    output_path: str = "local_results.json",
    questions: Optional[List[Dict]] = None,
):
    """执行本地 WebChat 评测

    Args:
        questions: 预加载的问题列表（--config 模式下从配置文件直接传入）
    """

    print(SEP)
    print("  UCloud GEO — 本地 Playwright WebChat Runner")
    print(SEP)
    print(f"  模型: {', '.join(model_keys)}")
    print(f"  输出: {output_path}")
    print(f"  延迟: {delay}s")
    print()

    # 1. 获取问题列表
    print("[1/5] 加载问题列表...")
    if questions:
        # 从配置文件直接传入（--config 模式）
        print("  来源: 任务配置文件")
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
    else:
        questions = await _load_questions(question_ids, categories)
    if not questions:
        print("  错误: 没有可评估的问题")
        return
    print(f"  加载 {len(questions)} 个问题")

    # 2. 初始化浏览器客户端
    print("[2/5] 初始化 WebChat 客户端...")
    clients = {}
    for mk in model_keys:
        print(f"  初始化 {MODEL_NAMES.get(mk, mk)} ({mk})...")
        client = create_web_chat_client(mk)
        if not client.is_configured:
            print(f"    ⚠️ 无认证状态，跳过 (需先运行 setup_webchat_auth.py 登录)")
            continue
        ok = await client.initialize()
        if not ok:
            print(f"    ⚠️ 浏览器启动失败，跳过")
            continue
        print(f"    ✅ 浏览器就绪")
        clients[mk] = client

    if not clients:
        print("  错误: 没有可用的 WebChat 客户端")
        return
    print(f"  可用: {', '.join(MODEL_NAMES.get(k, k) for k in clients)}")

    # 3. 执行评测
    print("[3/5] 开始评测...")
    analyzer = ResponseAnalyzer()
    calculator = MetricsCalculator()
    total = len(questions) * len(model_keys)
    completed = 0
    all_results: Dict[str, List] = {mk: [] for mk in model_keys}

    for mk in model_keys:
        client = clients.get(mk)
        model_name = MODEL_NAMES.get(mk, mk)
        if client:
            print(f"\n  --- {model_name} ---")
        else:
            print(f"\n  --- {model_name} (跳过，无认证) ---")

        for q in questions:
            completed += 1
            qid = q["id"]
            qtext = q["question"][:50]

            if client:
                try:
                    response = await client.chat(q["question"])
                    if response.get("error"):
                        print(f"    [{completed}/{total}] {qid} ❌ {response['error'][:80]}")
                        result = _empty_result(qid, mk, response["error"])
                    else:
                        content = response.get("content", "")
                        analysis = analyzer.analyze(
                            question_id=qid,
                            model_key=mk,
                            model_name=model_name,
                            content=content,
                            error=response.get("error"),
                        )
                        result = _analysis_to_dict(analysis)
                        ucloud = "✅" if analysis.ucloud_mentioned else "—"
                        cit = f"📎{analysis.citation_count}" if analysis.has_citation else ""
                        rec = f"⭐{analysis.ucloud_recommendation_strength}" if analysis.ucloud_recommended else ""
                        print(f"    [{completed}/{total}] {qid} {ucloud} {cit} {rec} ({len(content)}字)")
                except Exception as e:
                    print(f"    [{completed}/{total}] {qid} ❌ {str(e)[:80]}")
                    result = _empty_result(qid, mk, str(e))
            else:
                print(f"    [{completed}/{total}] {qid} ⏭️ 跳过")
                result = _empty_result(qid, mk, "WebChat 未配置登录状态")

            all_results[mk].append(result)

            if delay > 0:
                await asyncio.sleep(delay)

    # 4. 计算评分
    print("\n[4/5] 计算 GEO 评分...")
    geo_scores: Dict[str, Dict[str, Any]] = {}  # mk -> {None: scores, "category": scores}

    for mk in model_keys:
        if not all_results[mk]:
            continue

        model_name = MODEL_NAMES.get(mk, mk)
        results = [_dict_to_analysis(r) for r in all_results[mk]]
        scores = calculator.calculate_scores(results)
        geo_scores[mk] = {None: _scores_to_dict(scores)}

        print(f"  {model_name}: GEO={scores.geo_score:.1f} "
              f"覆盖={scores.coverage_rate:.2f} "
              f"引用={scores.citation_rate:.2f} "
              f"推荐={scores.recommendation_rate:.2f}")

        # 按品类计算
        categories_map = {}
        for r in all_results[mk]:
            qid = r["question_id"]
            for q in questions:
                if q["id"] == qid:
                    cat = q["category"]
                    categories_map.setdefault(cat, []).append(r)
                    break

        for cat, cat_results in categories_map.items():
            cat_analysis = [_dict_to_analysis(r) for r in cat_results]
            cat_scores = calculator.calculate_scores(cat_analysis)
            geo_scores[mk][cat] = _scores_to_dict(cat_scores)

    # 5. 导出结果
    print("\n[5/5] 导出结果...")
    output = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "mode": "webchat_local",
            "model_keys": model_keys,
            "total_questions": len(questions),
            "total_results": sum(len(v) for v in all_results.values()),
        },
        "questions": questions,
        "analysis_results": {mk: all_results[mk] for mk in model_keys},
        "geo_scores": geo_scores,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 结果已保存: {output_path}")
    print(f"  文件大小: {os.path.getsize(output_path) / 1024:.1f} KB")

    # 关闭浏览器
    print("\n关闭浏览器...")
    for mk, client in clients.items():
        await client.close()
    print("完成。")


async def _load_questions(
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict]:
    """加载问题列表（从数据库或本地文件）"""
    try:
        # 尝试从数据库加载
        questions = await db_get_questions(
            category=categories[0] if categories and len(categories) == 1 else None,
            active_only=True,
        )
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
        return questions
    except Exception:
        pass

    # 数据库不可用时，从 core/questions.py 加载
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
        from questions import QUESTIONS
        questions = [
            {
                "id": q.id,
                "category": q.category,
                "question_type": q.question_type,
                "question": q.question,
                "tags": q.tags,
                "difficulty": q.difficulty,
            }
            for q in QUESTIONS
        ]
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
        return questions
    except ImportError:
        print("  错误: 无法加载问题列表")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="本地 Playwright WebChat Runner",
        epilog="""
用例:
  # 方式1：直接指定参数（手动模式）
  python scripts/local_webchat_runner.py --models kimi ernie --delay 10

  # 方式2：从服务器下载的任务配置运行（云联动模式）
  python scripts/local_webchat_runner.py --config task_config.json

  # 带浏览器窗口（可手动处理验证码/登录）
  python scripts/local_webchat_runner.py --config task_config.json --headed
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        help="任务配置文件路径（由服务器 /api/evaluations/export-webchat-config 生成）",
    )
    parser.add_argument(
        "--models", nargs="+",
        help="要评测的模型 (默认: kimi)",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="显示浏览器窗口（默认后台运行，--headed 可处理验证码/登录）",
    )
    parser.add_argument(
        "--questions", default="all",
        help="问题范围: all / 逗号分隔的问题ID / 品类名（--config 模式下被忽略）",
    )
    parser.add_argument(
        "--delay", type=float,
        help="每题之间的延迟秒数（--config 模式下优先使用配置中的值）",
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（默认: output/webchat_results_YYYYMMDD_HHMMSS.json）",
    )

    args = parser.parse_args()

    # 设置浏览器显示模式（必须在 import web_chat_clients 之前）
    _setup_headed_mode(args.headed)

    # 加载任务配置
    question_ids = None
    categories = None
    preloaded_questions = None
    model_keys = args.models or ["kimi"]
    delay = args.delay if args.delay is not None else 8.0
    output_path = args.output

    if args.config:
        # 从配置文件加载（云联动模式）
        print(f"  📥 从配置文件加载: {args.config}")
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)

        model_keys = config["task"]["model_keys"]
        delay = config["task"].get("delay", delay)
        preloaded_questions = config.get("questions")  # 配置里的问题数据
        question_ids = config.get("question_ids")
        categories = config.get("categories")

        # 默认输出文件名带任务名
        if not output_path:
            task_name = config["task"].get("name", "webchat")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in task_name)
            output_path = f"output/webchat_{safe_name}_{timestamp}.json"

        print(f"  任务: {config['task'].get('name', 'N/A')}")
        print(f"  模型: {', '.join(model_keys)}")
        print(f"  问题: {len(preloaded_questions) if preloaded_questions else '全部'} 个")
        print(f"  延迟: {delay}s")
        print()
    else:
        # 手动模式
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"output/webchat_results_{timestamp}.json"

        if args.questions != "all":
            if "," in args.questions:
                question_ids = args.questions.split(",")
            else:
                categories = [args.questions]

    asyncio.run(run_local_eval(
        model_keys=model_keys,
        question_ids=question_ids,
        categories=categories,
        delay=delay,
        output_path=output_path,
        questions=preloaded_questions if args.config else None,
    ))


if __name__ == "__main__":
    main()
