"""
UCloud GEO Web - 异步评测执行器
后台运行评测任务，通过 WebSocket 推送进度
"""
import os
import sys
import uuid
import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

# 添加 core 模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from database import (
    create_run, update_run_status, save_analysis_result, save_geo_scores,
    get_questions, get_setting, get_db
)
from model_clients import ModelClient
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator

logger = logging.getLogger(__name__)

UCLOUD_QUESTION_PATTERN = re.compile(r"u\s*cloud|优\s*刻\s*得|优刻得", re.IGNORECASE)


def _is_natural_question(question: str, category: str = "") -> bool:
    """非引导型且题干不自带 UCloud/优刻得 字眼时，视为自然问题。"""
    if category == "引导型":
        return False
    return not UCLOUD_QUESTION_PATTERN.search(question or "")

# 全局任务管理
_active_tasks: Dict[str, asyncio.Task] = {}


async def start_evaluation(
    name: str,
    model_keys: List[str],
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    temperature: float = 0.7,
    delay: float = 1.0,
    ws_manager=None,
) -> str:
    """启动异步评测任务"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    # 获取问题列表
    db = await get_db()
    try:
        if question_ids:
            q_list = []
            for qid in question_ids:
                cursor = await db.execute("SELECT * FROM questions WHERE id=? AND is_active=1", (qid,))
                row = await cursor.fetchone()
                if row:
                    q_list.append(dict(row))
        elif categories:
            placeholders = ",".join("?" * len(categories))
            cursor = await db.execute(
                f"SELECT * FROM questions WHERE category IN ({placeholders}) AND is_active=1",
                categories
            )
            q_list = [dict(r) for r in await cursor.fetchall()]
        else:
            cursor = await db.execute("SELECT * FROM questions WHERE is_active=1")
            q_list = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not q_list:
        raise ValueError("没有可评估的问题")

    # 过滤有API Key的模型
    available_models = []
    for mk in model_keys:
        api_key_env = {
            "deepseek": "DEEPSEEK_API_KEY",
            "ernie": "ERNIE_API_KEY",
            "doubao": "DOUBAO_API_KEY",
            "kimi": "KIMI_API_KEY",
            "qwen": "QWEN_API_KEY",
        }.get(mk, "")
        # 从数据库读取API Key
        saved_key = await get_setting(f"api_key_{mk}", "")
        env_key = os.getenv(api_key_env, "")
        if saved_key or (env_key and not env_key.startswith("your_")):
            available_models.append(mk)

    if not available_models:
        raise ValueError("没有可用的模型（API Key未配置）")

    actual_q_ids = [q["id"] for q in q_list]
    await create_run(run_id, name, available_models, actual_q_ids, {
        "temperature": temperature, "delay": delay
    })

    # 启动后台任务
    task = asyncio.create_task(
        _run_evaluation(run_id, available_models, q_list, temperature, delay, ws_manager)
    )
    _active_tasks[run_id] = task

    return run_id


async def _run_evaluation(
    run_id: str,
    model_keys: List[str],
    questions: List[Dict],
    temperature: float,
    delay: float,
    ws_manager=None,
):
    """执行评测的核心逻辑"""
    await update_run_status(run_id, "running")
    analyzer = ResponseAnalyzer()
    calculator = MetricsCalculator()

    total = len(questions) * len(model_keys)
    completed = 0

    # 按模型分组的结果
    all_results: Dict[str, List] = {mk: [] for mk in model_keys}

    try:
        for mk in model_keys:
            # 创建模型客户端
            client = await _create_model_client(mk, temperature)
            if not client or not client.is_configured:
                # 跳过不可用的模型
                for q in questions:
                    result_dict = _empty_result(q["id"], mk, "API key not configured")
                    await save_analysis_result(run_id, result_dict)
                    all_results[mk].append(result_dict)
                    completed += 1
                continue

            for q in questions:
                try:
                    # 发送请求
                    response = client.chat(q["question"])

                    # 分析响应
                    analysis = analyzer.analyze(
                        question_id=q["id"],
                        model_key=mk,
                        model_name=client.name,
                        content=response.get("content", ""),
                        error=response.get("error"),
                    )

                    result_dict = _analysis_to_dict(analysis)
                    await save_analysis_result(run_id, result_dict)
                    all_results[mk].append(result_dict)

                except Exception as e:
                    logger.error(f"Error querying {mk} for {q['id']}: {e}")
                    result_dict = _empty_result(q["id"], mk, str(e))
                    await save_analysis_result(run_id, result_dict)
                    all_results[mk].append(result_dict)

                completed += 1
                await update_run_status(run_id, "running", completed)

                # WebSocket 推送进度
                if ws_manager:
                    await ws_manager.broadcast(run_id, {
                        "type": "progress",
                        "run_id": run_id,
                        "completed": completed,
                        "total": total,
                        "current_model": mk,
                        "current_question": q["id"],
                    })

                if delay > 0:
                    await asyncio.sleep(delay)

        # 计算GEO评分
        for mk in model_keys:
            if not all_results[mk]:
                continue

            # 全局评分：提及率/TOP3 仅统计自然问题；引用率/情感值统计全部有效问题
            from analyzer import AnalysisResult
            results = [_dict_to_analysis(r) for r in all_results[mk]]
            scores = calculator.calculate_scores(results)
            scores_dict = _scores_to_dict(scores)
            model_name = results[0].model_name if results else (all_results[mk][0].get("model_name") if all_results[mk] else mk)
            await save_geo_scores(run_id, mk, model_name, None, scores_dict)

            # 品类评分
            categories = {}
            for r in all_results[mk]:
                qid = r["question_id"]
                for q in questions:
                    if q["id"] == qid:
                        cat = q["category"]
                        if cat not in categories:
                            categories[cat] = []
                        categories[cat].append(r)
                        break

            for cat, cat_results in categories.items():
                cat_analysis = [_dict_to_analysis(r) for r in cat_results]
                cat_scores = calculator.calculate_scores(cat_analysis)
                cat_dict = _scores_to_dict(cat_scores)
                await save_geo_scores(run_id, mk, model_name, cat, cat_dict)

        await update_run_status(run_id, "completed", completed)

        if ws_manager:
            await ws_manager.broadcast(run_id, {
                "type": "completed",
                "run_id": run_id,
            })

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        await update_run_status(run_id, "failed")
        if ws_manager:
            await ws_manager.broadcast(run_id, {
                "type": "failed",
                "run_id": run_id,
                "error": str(e),
            })


async def _create_model_client(model_key: str, temperature: float = 0.7) -> Optional[ModelClient]:
    """创建模型客户端（优先从数据库读取API Key、base_url、model）"""
    import config as cfg

    saved_key = await get_setting(f"api_key_{model_key}", "")
    saved_url = await get_setting(f"base_url_{model_key}", "")
    saved_model = await get_setting(f"model_{model_key}", "")

    # 用数据库配置覆盖 config
    if saved_key:
        os.environ[cfg.MODELS[model_key]["api_key_env"]] = saved_key
    if saved_url:
        cfg.MODELS[model_key]["base_url"] = saved_url
    if saved_model:
        cfg.MODELS[model_key]["model"] = saved_model

    client = ModelClient(model_key)
    return client


def _analysis_to_dict(a) -> Dict:
    """AnalysisResult → dict"""
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


def _dict_to_analysis(d: Dict):
    """dict → AnalysisResult"""
    from analyzer import AnalysisResult
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


def _empty_result(question_id: str, model_key: str, error: str) -> Dict:
    """空结果"""
    return {
        "question_id": question_id,
        "model_key": model_key,
        "model_name": model_key,
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
    """GEOScores → dict"""
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
