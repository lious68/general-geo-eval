"""
UCloud GEO Web - 异步评测执行器
后台运行评测任务，通过 WebSocket 推送进度
"""
import os
import sys
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# 添加 core 模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from database import (
    create_run, update_run_status, save_analysis_result, save_geo_scores,
    get_questions, get_setting, get_db, get_run, get_brand_profile
)
from model_clients import ModelClient
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator

logger = logging.getLogger(__name__)


def _on_task_done(task: asyncio.Task):
    """后台评测任务完成回调：捕获异常并记录日志"""
    # 从 _active_tasks 中移除
    for run_id, t in list(_active_tasks.items()):
        if t is task:
            _active_tasks.pop(run_id, None)
            break
    try:
        exc = task.exception()
        if exc:
            logger.error(f"Eval background task failed with exception: {exc}", exc_info=exc)
    except asyncio.CancelledError:
        logger.warning("Eval background task was cancelled")
    except Exception as e:
        logger.error(f"Error retrieving task exception: {e}")


# 全局任务管理
_active_tasks: Dict[str, asyncio.Task] = {}


async def cancel_evaluation(run_id: str) -> bool:
    """强制取消运行中的评测任务

    如果 task 在内存中，调用 task.cancel()；
    即使 task 不在内存中（如服务重启后），也更新数据库状态为 cancelled。
    """
    task = _active_tasks.get(run_id)
    if task is not None:
        task.cancel()

    # 无论 task 是否在内存，都更新数据库状态
    run = await get_run(run_id)
    if not run:
        return False
    if run["status"] not in ("running", "pending"):
        return False

    await update_run_status(run_id, "cancelled")
    return True


async def start_evaluation(
    name: str,
    model_keys: List[str],
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    temperature: float = 0.7,
    delay: float = 1.0,
    ws_manager=None,
    mode: str = "api",
    enable_search: bool = False,
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

    if mode == "api" and not available_models:
        raise ValueError("没有可用的模型（API Key未配置）")

    actual_q_ids = [q["id"] for q in q_list]
    await create_run(run_id, name, available_models if mode == "api" else model_keys,
                     actual_q_ids, {
        "temperature": temperature, "delay": delay, "mode": mode, "enable_search": enable_search
    }, mode=mode)

    # 启动后台任务
    task = asyncio.create_task(
        _run_evaluation(run_id, available_models if mode == "api" else model_keys,
                        q_list, temperature, delay, ws_manager, mode, enable_search)
    )
    task.add_done_callback(_on_task_done)
    _active_tasks[run_id] = task

    return run_id


async def _run_evaluation(
    run_id: str,
    model_keys: List[str],
    questions: List[Dict],
    temperature: float,
    delay: float,
    ws_manager=None,
    mode: str = "api",
    enable_search: bool = False,
):
    """执行评测的核心逻辑（三级任务调度：任务 → 模型 → 问题）

    复用 core/scheduler.EvalScheduler：
      - 单元级持久化（task_units 表）+ 断点续跑
      - 跨模型交错 + 逐模型限流配额 + 封号信号检测与自动退避 + 单题多次重试
    本函数只负责：构造 client_factory、on_unit_done/on_progress 回调、运行后计算 geo_scores。
    """
    logger.info(f"[EVAL {run_id}] Starting evaluation: mode={mode}, models={model_keys}, questions={len(questions)}")
    await update_run_status(run_id, "running")
    brand_profile = get_brand_profile()
    analyzer = ResponseAnalyzer(brand_profile=brand_profile)
    calculator = MetricsCalculator()

    from scheduler import EvalScheduler
    from task_units import SqliteUnitStore
    from webchat_policy import get_model_policy
    import os as _os

    # 单元存储：与 evaluation_runs 同库（data/geo.db）
    _db_path = _os.path.join(_os.path.dirname(__file__), "..", "data", "geo.db")
    store = SqliteUnitStore(_db_path)

    # 按模型分组的结果（供 geo_scores 计算；on_unit_done 填充）
    all_results: Dict[str, List] = {mk: [] for mk in model_keys}
    _q_map = {q["id"]: q for q in questions}
    completed = 0
    total = len(questions) * len(model_keys)

    # ---- 回调 ----
    async def on_unit_done(unit, response):
        nonlocal completed
        content = response.get("content", "")
        error = response.get("error")
        model_name = unit.model_name or response.get("model_name") or unit.model_key
        # 保留远端的 search_results 特性（API 路径合并返回的引用来源）
        analysis = analyzer.analyze(
            question_id=unit.question_id,
            model_key=unit.model_key,
            model_name=model_name,
            content=content,
            error=error,
            search_results=response.get("search_results"),
        )
        result_dict = _analysis_to_dict(analysis)
        await save_analysis_result(run_id, result_dict)
        all_results[unit.model_key].append(result_dict)
        completed += 1
        await update_run_status(run_id, "running", completed)

    async def on_progress(event):
        etype = event.get("type")
        if ws_manager and etype == "progress":
            # 沿用前端既有进度协议
            await ws_manager.broadcast(run_id, {
                "type": "progress",
                "run_id": run_id,
                "completed": event.get("completed", completed),
                "total": event.get("total", total),
                "counts": event.get("counts"),
            })
        elif ws_manager and etype in ("model_skipped", "throttled"):
            logger.info(f"[EVAL {run_id}] {etype}: {event}")

    # ---- 客户端工厂（webchat / api 各一）----
    async def client_factory_webchat(mk):
        from web_chat_clients import create_web_chat_client
        return create_web_chat_client(mk)

    async def client_factory_api(mk):
        return await _create_model_client(mk, temperature)

    client_factory = client_factory_webchat if mode == "webchat" else client_factory_api

    # ---- 逐模型策略：用户 delay 与平台保护 delay 取较大者，绝不缩小 DeepSeek 间隔 ----
    extra_policy: Dict[str, dict] = {}
    for mk in model_keys:
        pol = get_model_policy(mk)
        if delay and delay > 0:
            extra_policy[mk] = {"inter_unit_delay": max(pol.get("inter_unit_delay", 0), float(delay))}

    scheduler = EvalScheduler(
        run_id=run_id,
        models=model_keys,
        questions=questions,
        store=store,
        client_factory=client_factory,
        on_unit_done=on_unit_done,
        on_progress=on_progress,
        extra_policy=extra_policy,
    )

    try:
        # 运行调度（webchat 浏览器由各 worker 在 client_factory 内初始化/关闭）
        await scheduler.run()

        # 补齐被跳过（未配置/登录失效）的模型单元为空结果，保证评测覆盖完整
        for mk in model_keys:
            seen = {r["question_id"] for r in all_results[mk]}
            for q in questions:
                if q["id"] not in seen:
                    reason = ("WebChat 未配置登录状态" if mode == "webchat"
                              else "API key not configured / skipped")
                    rd = _empty_result(q["id"], mk, reason)
                    await save_analysis_result(run_id, rd)
                    all_results[mk].append(rd)
                    completed += 1

        # 计算 GEO 评分（与落库顺序无关）
        for mk in model_keys:
            if not all_results[mk]:
                continue

            # 全局评分：提及率/TOP3 仅统计自然问题；引用率/情感值统计全部有效问题
            results = [_dict_to_analysis(r) for r in all_results[mk]]
            scores = calculator.calculate_scores(results, questions=questions, brand_profile=brand_profile)
            scores_dict = _scores_to_dict(scores)
            model_name = results[0].model_name if results else mk
            await save_geo_scores(run_id, mk, model_name, None, scores_dict)

            # 品类评分
            categories = {}
            for r in all_results[mk]:
                qid = r["question_id"]
                q = _q_map.get(qid)
                if q:
                    categories.setdefault(q["category"], []).append(r)

            for cat, cat_results in categories.items():
                cat_analysis = [_dict_to_analysis(r) for r in cat_results]
                cat_questions = [q for q in questions if q.get("category") == cat]
                cat_scores = calculator.calculate_scores(cat_analysis, questions=cat_questions, brand_profile=brand_profile)
                await save_geo_scores(run_id, mk, model_name, cat, _scores_to_dict(cat_scores))

        await update_run_status(run_id, "completed", completed)

        if ws_manager:
            await ws_manager.broadcast(run_id, {
                "type": "completed",
                "run_id": run_id,
            })

    except asyncio.CancelledError:
        logger.warning(f"[EVAL {run_id}] Evaluation was cancelled by user")
        await update_run_status(run_id, "cancelled", completed)
        if ws_manager:
            await ws_manager.broadcast(run_id, {
                "type": "cancelled",
                "run_id": run_id,
            })

    except Exception as e:
        logger.error(f"[EVAL {run_id}] Evaluation failed: {e}", exc_info=True)
        await update_run_status(run_id, "failed")
        if ws_manager:
            await ws_manager.broadcast(run_id, {
                "type": "failed",
                "run_id": run_id,
                "error": str(e),
            })

    finally:
        # 浏览器由各 worker 在 client_factory→scheduler 内自行关闭；
        # 这里仅兜底记录。
        logger.info(f"[EVAL {run_id}] finished, completed={completed}/{total}")



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
