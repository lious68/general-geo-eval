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
from datetime import datetime
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from metrics import MetricsCalculator


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


async def create_task_with_questions(name: str, question_ids: List[str],
                                     categories: Optional[List[str]] = None) -> Dict:
    """建任务，固定总题集。"""
    task_id = _new_id("task")
    return await db.create_task(task_id, name, question_ids, categories)


async def resolve_question_ids(question_ids: Optional[List[str]],
                               categories: Optional[List[str]]) -> List[str]:
    """从品类或显式 id 解析出固定总题集 id 列表。"""
    questions = await db.get_questions(
        category=categories[0] if categories and len(categories) == 1 else None,
        active_only=True,
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

    # 校验每模型题区间都是总题集子集
    for mk, qids in per_model_question_ids.items():
        if mk not in model_keys:
            raise ValueError(f"模型 {mk} 未在 model_keys 中")
        bad = [q for q in qids if q not in total_qids]
        if bad:
            raise ValueError(f"模型 {mk} 的题区间含任务总题集外的题: {bad[:3]}")

    # 取完整题对象（units 并集）
    union_qids = sorted({q for qids in per_model_question_ids.values() for q in qids})
    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in union_qids if qid in q_map]

    batch_id = _new_id("batch")
    run_id = _new_id("run")
    await db.add_task_batch(
        run_id=run_id, task_id=task_id, batch_id=batch_id,
        name=task["name"], model_keys=model_keys,
        question_ids=union_qids,
        per_model=per_model_question_ids,
        config={"delay": delay, "per_model_question_ids": per_model_question_ids},
    )

    config = {
        "version": 2,
        "task_id": task_id,
        "task_name": task["name"],
        "batch_id": batch_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(),
        "total_question_ids": task["question_ids"],
        "units": [{"model_key": mk, "question_ids": per_model_question_ids[mk]} for mk in model_keys],
        "questions": questions,
        "delay": delay,
    }
    return config


async def import_batch_results(task_id: str, data: Dict) -> Dict:
    """导入本地 runner 结果 JSON，按 (task_id,model,question) 去重覆盖，重算 task 评分。

    data 形如 {"meta": {"task_id","batch_id","run_id",...},
              "questions": [...], "analysis_results": {mk: [result,...]}}
    """
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    meta = data.get("meta") or {}
    batch_id = meta.get("batch_id") or "batch_unknown"
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

    return {"task_id": task_id, "batch_id": batch_id, "results_inserted": inserted}


async def recalculate_task_scores(task_id: str) -> None:
    """按当前 task 全部 analysis_results 重算 geo_scores 并覆盖。"""
    task = await db.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    await db.delete_task_geo_scores(task_id)

    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    # task 固定题集对应的题对象（用于自然问题过滤与品类）
    task_questions = [q_map[qid] for qid in task["question_ids"] if qid in q_map]

    results = await db.get_task_results(task_id)
    by_model: Dict[str, List[Dict]] = {}
    for r in results:
        by_model.setdefault(r["model_key"], []).append(r)

    calculator = MetricsCalculator()
    for mk, mresults in by_model.items():
        model_name = mresults[0].get("model_name") or mk
        analysis_objects = [_result_to_analysis(r) for r in mresults]
        scores = calculator.calculate_scores(analysis_objects, questions=task_questions)
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
                [_result_to_analysis(r) for r in cat_results], questions=cat_questions
            )
            await db.save_task_geo_scores(task_id, mk, model_name, cat, _scores_to_dict(cat_scores))


def _result_to_analysis(r: Dict):
    from analyzer import AnalysisResult
    return AnalysisResult(
        question_id=r["question_id"], model_key=r["model_key"],
        model_name=r.get("model_name") or r["model_key"],
        ucloud_mentioned=bool(r.get("ucloud_mentioned")),
        ucloud_mention_count=r.get("ucloud_mention_count", 0),
        ucloud_rank=r.get("ucloud_rank"),
        has_citation=bool(r.get("has_citation")),
        citation_count=r.get("citation_count", 0),
        ucloud_recommended=bool(r.get("ucloud_recommended")),
        ucloud_recommendation_strength=r.get("recommendation_strength", "none"),
        sentiment_score=r.get("sentiment_score", 0.5),
        sentiment_label=r.get("sentiment_label", "neutral"),
        position_weight=r.get("position_weight", 0.0),
        response_length=r.get("response_length", 0),
        raw_content=r.get("raw_content", ""),
    )


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
    scores = await db.get_task_scores(task_id)

    all_qids = task["question_ids"]
    all_questions = await db.get_questions(active_only=True)
    q_map = {q["id"]: q for q in all_questions}
    questions = [q_map[qid] for qid in all_qids if qid in q_map]

    total_cells = len(all_qids) * max(len(coverage), 1)
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
        models = list(coverage.keys())
        total_cells = len(all_qids) * max(len(models), 1)
        done_cells = sum(1 for mk in coverage for s in coverage[mk].values() if s == "done")
        out.append({
            **t,
            "models": models,
            "total_cells": total_cells,
            "done_cells": done_cells,
            "coverage_rate": round(done_cells / total_cells, 3) if total_cells else 0,
        })
    return out
