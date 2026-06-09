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
    get_questions, get_setting, get_db, get_run
)
from model_clients import ModelClient
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator

logger = logging.getLogger(__name__)

UCLOUD_QUESTION_PATTERN = re.compile(r"u\s*cloud|优\s*刻\s*得|优刻得", re.IGNORECASE)


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


def _is_natural_question(question: str, category: str = "") -> bool:
    """非引导型且题干不自带 UCloud/优刻得 字眼时，视为自然问题。"""
    if category == "引导型":
        return False
    return not UCLOUD_QUESTION_PATTERN.search(question or "")

async def calculate_and_save_geo_scores(run_id: str, model_key: str, model_name: str,
                                         all_results: List[Dict], questions: List[Dict]):
    """计算并保存 GEO 评分（全局 + 品类），供 eval_runner、import API、agent 共用"""
    from analyzer import AnalysisResult
    calculator = MetricsCalculator()

    if not all_results:
        return

    # 全局评分
    results = [_dict_to_analysis(r) for r in all_results]
    scores = calculator.calculate_scores(results)
    scores_dict = _scores_to_dict(scores)
    await save_geo_scores(run_id, model_key, model_name, None, scores_dict)

    # 品类评分
    categories = {}
    for r in all_results:
        qid = r["question_id"]
        for q in questions:
            if q["id"] == qid:
                cat = q.get("category", "未分类")
                categories.setdefault(cat, []).append(r)
                break

    for cat, cat_results in categories.items():
        cat_analysis = [_dict_to_analysis(r) for r in cat_results]
        cat_scores = calculator.calculate_scores(cat_analysis)
        cat_dict = _scores_to_dict(cat_scores)
        await save_geo_scores(run_id, model_key, model_name, cat, cat_dict)


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
        "temperature": temperature, "delay": delay, "mode": mode
    }, mode=mode)

    # WebChat 模式：委托给本地 Agent
    if mode == "webchat":
        from routers.agent import get_connected_agent, send_task_to_agent

        agent = get_connected_agent()
        if not agent:
            raise ValueError("WebChat 模式需要本地 Agent，请先在本地启动 Agent 脚本")

        # 加载 auth_states
        auth_states = {}
        from web_chat_auth import load_auth_state
        for mk in model_keys:
            state = load_auth_state(mk)
            if state:
                auth_states[mk] = state

        # 构建简化的问题列表（只发必要字段，减小 WS 消息体积）
        questions_simple = [
            {"id": q["id"], "question": q["question"], "category": q.get("category", "")}
            for q in q_list
        ]

        await send_task_to_agent(agent, {
            "type": "task.assign",
            "run_id": run_id,
            "name": name,
            "model_keys": model_keys,
            "questions": questions_simple,
            "delay": delay,
            "auth_states": auth_states,
        })
        logger.info(f"[EVAL {run_id}] Task assigned to Agent {agent.agent_id}")
        return run_id

    # API 模式：启动后台任务
    task = asyncio.create_task(
        _run_evaluation(run_id, available_models if mode == "api" else model_keys,
                        q_list, temperature, delay, ws_manager, mode)
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
):
    """执行评测的核心逻辑"""
    logger.info(f"[EVAL {run_id}] Starting evaluation: mode={mode}, models={model_keys}, questions={len(questions)}")
    await update_run_status(run_id, "running")
    analyzer = ResponseAnalyzer()
    calculator = MetricsCalculator()

    # WebChat 模式的浏览器客户端管理
    webchat_clients: Dict[str, Any] = {}
    if mode == "webchat":
        logger.info(f"[EVAL {run_id}] WebChat mode: initializing browser clients for {model_keys}")
        from web_chat_clients import create_web_chat_client
        for mk in model_keys:
            logger.info(f"[EVAL {run_id}] WebChat {mk}: creating client...")
            client = create_web_chat_client(mk)
            if not client.is_configured:
                logger.warning(f"[EVAL {run_id}] WebChat {mk}: 无认证状态，跳过")
                continue
            logger.info(f"[EVAL {run_id}] WebChat {mk}: launching browser...")
            initialized = await client.initialize()
            if not initialized:
                logger.warning(f"[EVAL {run_id}] WebChat {mk}: 浏览器启动失败，跳过")
                continue
            logger.info(f"[EVAL {run_id}] WebChat {mk}: browser ready")
            webchat_clients[mk] = client

    total = len(questions) * len(model_keys)
    logger.info(f"[EVAL {run_id}] Total tasks: {total} ({len(questions)} questions × {len(model_keys)} models)")
    completed = 0

    # 按模型分组的结果
    all_results: Dict[str, List] = {mk: [] for mk in model_keys}

    try:
        for mk in model_keys:
            # WebChat 模式：使用浏览器客户端
            if mode == "webchat" and mk in webchat_clients:
                wc_client = webchat_clients[mk]
                for q in questions:
                    try:
                        # 让出控制权，使 CancelledError 能被及时响应
                        await asyncio.sleep(0)

                        response = await wc_client.chat(q["question"])

                        analysis = analyzer.analyze(
                            question_id=q["id"],
                            model_key=mk,
                            model_name=wc_client.name,
                            content=response.get("content", ""),
                            error=response.get("error"),
                        )

                        result_dict = _analysis_to_dict(analysis)
                        await save_analysis_result(run_id, result_dict)
                        all_results[mk].append(result_dict)

                    except Exception as e:
                        logger.error(f"WebChat error querying {mk} for {q['id']}: {e}")
                        result_dict = _empty_result(q["id"], mk, str(e))
                        await save_analysis_result(run_id, result_dict)
                        all_results[mk].append(result_dict)

                    completed += 1
                    await update_run_status(run_id, "running", completed)

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

            elif mode == "webchat" and mk not in webchat_clients:
                # 无认证状态的模型，跳过
                for q in questions:
                    result_dict = _empty_result(q["id"], mk, "WebChat 未配置登录状态")
                    await save_analysis_result(run_id, result_dict)
                    all_results[mk].append(result_dict)
                    completed += 1
                continue

            else:
                # API 模式：使用 OpenAI 兼容客户端
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
                        # 让出控制权，使 CancelledError 能被及时响应
                        await asyncio.sleep(0)

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

                # 计算GEO评分
        for mk in model_keys:
            if not all_results[mk]:
                continue
            model_name = (all_results[mk][0].get("model_name") if all_results[mk] else mk)
            await calculate_and_save_geo_scores(run_id, mk, model_name, all_results[mk], questions)

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
        # 关闭 WebChat 浏览器
        if mode == "webchat":
            for mk, wc_client in webchat_clients.items():
                await wc_client.close()
            logger.info("WebChat browsers closed")


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
