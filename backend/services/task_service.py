"""Task 领域服务：任务→模型→问题 三级架构的服务端逻辑。

职责：
  - 建任务（固定总题集）
  - 建下载批次（生成 v2 配置 JSON）
  - 导入本地 runner 结果（按 (task_id,model,question) 去重覆盖 + 重算评分）
  - 构建任务详情（覆盖率矩阵 + 批次列表）
"""
import os
import sys
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from metrics import MetricsCalculator
from analyzer import AnalysisResult, CitationInfo
from brand_profile import default_brand_profile

logger = logging.getLogger(__name__)


async def _push_webhook(task_id: str, batch_id: str, run_id: str) -> bool:
    """建批次后 fire-and-forget 推送 webhook 到 Win 守护进程。失败不改状态（留 config_downloaded）。"""
    win_url = os.environ.get("WEBHOOK_WIN_URL", "")
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not win_url or not secret:
        logger.warning("WEBHOOK_WIN_URL/WEBHOOK_SECRET 未配置，跳过推送")
        return False
    payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "config_url": f"/api/tasks/{task_id}/batches/{batch_id}/config",
    }
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{win_url}/webhook/batch",
                             json=payload,
                             headers={"X-Webhook-Secret": secret},
                             timeout=5)
            r.raise_for_status()
        await db.set_batch_status(run_id, "pushed")
        return True
    except Exception as e:
        logger.warning(f"webhook 推送失败 (batch={batch_id}): {e}；批次留 config_downloaded，可重推")
        return False


async def repush_batch(task_id: str, batch_id: str) -> bool:
    """手动重推：按 batch_id 找 run_id 再推一次。"""
    run = await db.get_run_by_batch_id(batch_id)
    if not run:
        raise ValueError("批次不存在")
    return await _push_webhook(task_id, batch_id, run["id"])


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


async def create_task_with_questions(name: str, question_ids: List[str],
                                     categories: Optional[List[str]] = None,
                                     brand_id: str = None) -> Dict:
    """建任务，固定总题集。brand_id 未指定时从 question_ids 推断（取第一题所属品牌），推断失败则 current。"""
    if brand_id is None and question_ids:
        # 按题所属品牌推断任务品牌，避免切换 current 时建错品牌的任务
        conn = await db.get_db()
        try:
            placeholders = ",".join("?" * len(question_ids))
            cursor = await conn.execute(
                f"SELECT brand_id FROM questions WHERE id IN ({placeholders}) LIMIT 1",
                question_ids,
            )
            row = await cursor.fetchone()
            if row and row["brand_id"]:
                brand_id = row["brand_id"]
        finally:
            await conn.close()
    task_id = _new_id("task")
    return await db.create_task(task_id, name, question_ids, categories, brand_id=brand_id)


async def resolve_question_ids(question_ids: Optional[List[str]],
                               categories: Optional[List[str]],
                               brand_id: str = None) -> List[str]:
    """从品类或显式 id 解析出固定总题集 id 列表。brand_id 默认 current。"""
    questions = await db.get_questions(
        category=categories[0] if categories and len(categories) == 1 else None,
        active_only=True, brand_id=brand_id,
    )
    if categories:
        questions = [q for q in questions if q["category"] in categories]
    if question_ids:
        questions = [q for q in questions if q["id"] in question_ids]
    return [q["id"] for q in questions]


async def create_batch_config(task_id: str, model_keys: List[str],
                              per_model_question_ids: Dict[str, List[str]],
                              delay: float = 8.0) -> Dict:
    """在 task 下建下载批次，返回 v2 配置 JSON（供前端下载、本地 runner 消费）。

    per_model_question_ids: {model_key: [question_id, ...]}，每模型独立题区间（总题集子集）。
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    total_qids = set(task["question_ids"])

    # 校验 model_keys 中每个模型都有对应的题区间配置
    for mk in model_keys:
        if mk not in per_model_question_ids:
            raise ValueError(f"模型 {mk} 缺少题区间配置")

    # 校验每模型题区间都是总题集子集
    for mk, qids in per_model_question_ids.items():
        if mk not in model_keys:
            raise ValueError(f"模型 {mk} 未在 model_keys 中")
        bad = [q for q in qids if q not in total_qids]
        if bad:
            raise ValueError(f"模型 {mk} 的题区间含任务总题集外的题: {bad[:3]}")

    # 取完整题对象（units 并集）— 按 task.brand_id 取，防跨品牌时 current 不同导致题集缺失
    union_qids = sorted({q for qids in per_model_question_ids.values() for q in qids})
    all_questions = await db.get_questions(active_only=True, brand_id=task.get("brand_id") or "ucloud")
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in union_qids if qid in q_map]

    batch_id = _new_id("batch")
    run_id = _new_id("run")
    # 品牌档案随配置透传给本地 runner，按 task 所属品牌取（多品牌不串口径）
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    config = {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "brand_id": task.get("brand_id") or "ucloud",
        "batch_id": batch_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model_question_ids[mk]} for mk in model_keys],
        "questions": questions,
        "delay": delay,
        "brand_profile": brand_profile.to_dict(),
    }
    # 持久化完整 v2 配置，便于以后重下/重跑
    await db.add_task_batch(
        run_id=run_id, task_id=task_id, batch_id=batch_id,
        name=task["name"], model_keys=model_keys,
        question_ids=union_qids,
        per_model=per_model_question_ids,
        config=config,
    )
    # 建批次成功后主动推送 webhook（失败不阻塞，留 config_downloaded 可重推）
    try:
        await _push_webhook(task_id, batch_id, run_id)
    except Exception as e:
        logger.warning(f"create_batch_config 推送异常: {e}")
    return config


async def get_batch_config(task_id: str, batch_id: str) -> Dict:
    """取某批次的 v2 配置（优先返回已持久化的完整配置；旧批次只有片段则就地重建）。"""
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    batches = await db.list_task_batches(task_id)
    b = next((x for x in batches if x.get("batch_id") == batch_id), None)
    if not b:
        raise ValueError("批次不存在")

    cfg = b.get("config") or {}
    if cfg.get("version") == 2 and cfg.get("units"):
        return cfg

    # 兼容旧批次：仅存了片段 {delay, per_model_question_ids}，就地重建完整 v2 配置
    per_model = cfg.get("per_model_question_ids") or {}
    model_keys = b.get("model_keys") or list(per_model.keys())
    union_qids = sorted({q for qs in per_model.values() for q in qs}) or (b.get("question_ids") or [])
    all_questions = await db.get_questions(active_only=True, brand_id=task.get("brand_id") or "ucloud")
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in union_qids if qid in q_map]
    # 兼容旧批次重建
    return {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "brand_id": task.get("brand_id") or "ucloud",
        "batch_id": batch_id,
        "run_id": b.get("id"),
        "generated_at": b.get("started_at") or datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model.get(mk, [])} for mk in model_keys],
        "questions": questions,
        "delay": cfg.get("delay", 8.0),
        "brand_profile": db.get_brand_profile_by_id(task.get("brand_id") or "ucloud").to_dict(),
    }


async def import_batch_results(task_id: str, data: Dict, batch_id: Optional[str] = None,
                               file_name: Optional[str] = None,
                               file_size: Optional[int] = None) -> Dict:
    """导入本地 runner 结果 JSON，按 (task_id,model,question) 去重覆盖，重算 task 评分。

    data 形如 {"meta": {"task_id","batch_id","run_id",...},
              "questions": [...], "analysis_results": {mk: [result,...]}}

    batch_id: 若传入则 pin 到该批次（覆盖 meta.batch_id），保证结果计数归属正确。
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    meta = data.get("meta") or {}
    batch_id = batch_id or meta.get("batch_id") or "batch_unknown"
    run_id = meta.get("run_id") or f"run_{batch_id}"

    analysis_results = data.get("analysis_results") or {}
    total_qids = set(task["question_ids"])

    inserted = 0
    for mk, results in analysis_results.items():
        for r in results:
            if r.get("question_id") not in total_qids:
                continue  # 固定题集外的题丢弃
            r["model_key"] = r.get("model_key", mk)
            await db.save_task_analysis_result(task_id, batch_id, run_id, r)
            inserted += 1

    # 重算 task 评分（覆盖）
    await recalculate_task_scores(task_id)

    # 记一条导入审计日志（数据已落库，记成功痕迹）
    try:
        await db.add_batch_import_log(task_id, batch_id, run_id, inserted, file_name, file_size)
    except Exception:
        pass  # 审计日志写失败不影响导入结果

    return {"task_id": task_id, "batch_id": batch_id, "results_inserted": inserted}


async def get_batch_results(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的全部分析结果（带题目原文）。"""
    return await db.get_batch_results(task_id, batch_id)


async def get_batch_import_logs(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的导入审计日志（时间倒序）。"""
    return await db.get_batch_import_logs(task_id, batch_id)


async def recalculate_task_scores(task_id: str) -> None:
    """按当前 task 全部 analysis_results 重算 geo_scores 并覆盖。"""
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    await db.delete_task_geo_scores(task_id)

    all_questions = await db.get_questions(active_only=True, brand_id=task.get("brand_id") or "ucloud")
    q_map = {q["id"]: q for q in all_questions}
    # task 固定题集对应的题对象（用于自然问题过滤与品类）
    task_questions = [q_map[qid] for qid in task["question_ids"] if qid in q_map]

    results = await db.get_task_results(task_id)
    by_model: Dict[str, List[Dict]] = {}
    for r in results:
        by_model.setdefault(r["model_key"], []).append(r)

    calculator = MetricsCalculator()
    # 多品牌：评分按 task 所属品牌口径算，不依赖全局 current（防切品牌串口径）
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    for mk, mresults in by_model.items():
        model_name = mresults[0].get("model_name") or mk
        analysis_objects = [_result_to_analysis(r) for r in mresults]
        scores = calculator.calculate_scores(analysis_objects, questions=task_questions, brand_profile=brand_profile)
        await db.save_task_geo_scores(task_id, mk, model_name, None, _scores_to_dict(scores))

        # 品类
        cat_map: Dict[str, List[Dict]] = {}
        for r in mresults:
            q = q_map.get(r["question_id"])
            if q:
                cat_map.setdefault(q["category"], []).append(r)
        for cat, cat_results in cat_map.items():
            cat_questions = [q for q in task_questions if q.get("category") == cat]
            cat_scores = calculator.calculate_scores(
                [_result_to_analysis(r) for r in cat_results], questions=cat_questions,
                brand_profile=brand_profile,
            )
            await db.save_task_geo_scores(task_id, mk, model_name, cat, _scores_to_dict(cat_scores))


def _result_to_analysis(r: Dict):
    return AnalysisResult(
        question_id=r["question_id"], model_key=r["model_key"],
        model_name=r.get("model_name") or r["model_key"],
        ucloud_mentioned=bool(r.get("ucloud_mentioned")),
        ucloud_mention_count=r.get("ucloud_mention_count", 0),
        ucloud_rank=r.get("ucloud_rank"),
        has_citation=bool(r.get("has_citation")),
        citations=_parse_citation_infos(r.get("citations")),
        citation_count=r.get("citation_count", 0),
        all_cited_urls=_parse_citation_infos(r.get("all_cited_urls")),
        ucloud_recommended=bool(r.get("ucloud_recommended")),
        ucloud_recommendation_strength=r.get("recommendation_strength", "none"),
        sentiment_score=r.get("sentiment_score", 0.5),
        sentiment_label=r.get("sentiment_label", "neutral"),
        position_weight=r.get("position_weight", 0.0),
        response_length=r.get("response_length", 0),
        raw_content=r.get("raw_content", ""),
    )


def _parse_citation_infos(raw):
    """DB 行的 citations/all_cited_urls（JSON 字符串或 list）→ List[CitationInfo]。

    必须重建，否则 MetricsCalculator._has_effective_citation 因 result.citations 为空
    而恒判无引用 → task citation_rate 恒 0。
    """
    import json as _json
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        try:
            pos = int(c.get("position", 0))
        except (TypeError, ValueError):
            pos = 0
        out.append(CitationInfo(
            citation_type=c.get("citation_type", "url"),
            content=c.get("content", ""),
            position=pos,
            source_channel=c.get("source_channel", ""),
            is_ucloud=bool(c.get("is_ucloud", False)),
        ))
    return out


def _scores_to_dict(s) -> Dict:
    return {
        "geo_score": s.geo_score, "coverage_rate": s.coverage_rate,
        "mention_rate": s.mention_rate, "citation_rate": s.citation_rate,
        "recommendation_rate": s.recommendation_rate, "sentiment_score": s.sentiment_score,
        "avg_rank": s.avg_rank, "total_questions": s.total_questions,
        "valid_responses": s.valid_responses,
    }


async def build_task_detail(task_id: str) -> Optional[Dict]:
    task = await db.get_task(task_id)
    if not task:
        return None
    coverage = await db.get_task_coverage(task_id)
    batches = await db.list_task_batches(task_id)
    # 给每个批次注入已导入结果条数（analysis_results 按 batch_id 分组计数）
    result_counts = await db.count_task_results_by_batch(task_id)
    last_imports = await db.get_last_import_times(task_id)
    for b in batches:
        b["result_count"] = result_counts.get(b.get("batch_id"), 0)
        b["last_import_at"] = last_imports.get(b.get("batch_id"))
    scores = await db.get_task_scores(task_id)

    all_qids = task["question_ids"]
    all_questions = await db.get_questions(active_only=True, brand_id=task.get("brand_id") or "ucloud")
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in all_qids if qid in q_map]

    # 模型集 = 已导入结果模型 ∪ 已下载批次模型（批次已下但未导入的模型也应显示为全 missing 行）
    batch_models: List[str] = []
    for b in batches:
        for mk in (b.get("model_keys") or []):
            if mk not in batch_models:
                batch_models.append(mk)
    matrix_models = list(coverage.keys())
    for mk in batch_models:
        if mk not in matrix_models:
            matrix_models.append(mk)
            coverage.setdefault(mk, {})
    # 为每个矩阵模型补齐固定题集的 missing
    for mk in matrix_models:
        for qid in all_qids:
            coverage[mk].setdefault(qid, "missing")

    total_cells = len(all_qids) * len(matrix_models)
    done_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "done")
    return {
        "task": task,
        "questions": questions,
        "coverage": coverage,
        "batches": batches,
        "scores": scores,
        "summary": {
            "total_cells": total_cells,
            "done_cells": done_cells,
            "missing_cells": total_cells - done_cells,
            "coverage_rate": round(done_cells / total_cells, 3) if total_cells else 0,
        },
    }


async def build_task_list_summary() -> List[Dict]:
    tasks = await db.list_tasks()
    out = []
    for t in tasks:
        coverage = await db.get_task_coverage(t["id"])
        all_qids = t["question_ids"]
        batches = await db.list_task_batches(t["id"])
        models = list(coverage.keys())
        for b in batches:
            for mk in (b.get("model_keys") or []):
                if mk not in models:
                    models.append(mk)
        total_cells = len(all_qids) * len(models)
        done_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "done")
        missing_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "missing")
        out.append({
            **t,
            "models": models,
            "total_cells": total_cells,
            "done_cells": done_cells,
            "missing_cells": missing_cells,
            "coverage_rate": round(done_cells / total_cells, 3) if total_cells else 0,
        })
    return out
