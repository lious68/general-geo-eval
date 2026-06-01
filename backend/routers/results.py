"""结果查询路由"""
import json
from fastapi import APIRouter, HTTPException, Query
import database as db
from services.chart_builder import (
    build_radar_option, build_bar_option, build_coverage_option,
    build_sentiment_option, build_heatmap_option,
)

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("/{run_id}/scores")
async def get_scores(run_id: str, category: str = None):
    """获取GEO评分"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    scores = await db.get_scores(run_id, category)
    return {"success": True, "data": scores}


@router.get("/{run_id}/details")
async def get_details(run_id: str, model_key: str = None, category: str = None,
                      page: int = 1, page_size: int = 50):
    """获取详细结果"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    results = await db.get_results(run_id, model_key, category)
    total = len(results)
    start = (page - 1) * page_size
    items = results[start:start + page_size]
    return {"success": True, "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/{run_id}/charts")
async def get_charts(run_id: str):
    """获取图表配置JSON"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    # 获取全局评分
    scores = await db.get_scores(run_id)
    # 获取品类评分
    cat_scores_raw = await db.get_scores(run_id, category="__all__")
    # 获取所有品类评分
    import database as _db
    db_conn = await _db.get_db()
    try:
        cursor = await db_conn.execute(
            "SELECT * FROM geo_scores WHERE run_id=? AND category IS NOT NULL", (run_id,)
        )
        all_cat_scores = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db_conn.close()

    # 获取详细结果用于情感图
    all_results = await db.get_results(run_id)
    results_by_model = {}
    for r in all_results:
        mk = r["model_key"]
        if mk not in results_by_model:
            results_by_model[mk] = []
        results_by_model[mk].append(r)

    charts = {
        "radar": build_radar_option(scores) if scores else {},
        "bar": build_bar_option(scores) if scores else {},
        "coverage": build_coverage_option(scores) if scores else {},
        "sentiment": build_sentiment_option(results_by_model) if results_by_model else {},
        "heatmap": build_heatmap_option(all_cat_scores) if all_cat_scores else {},
    }
    return {"success": True, "data": charts}


@router.get("/{run_id}/citations")
async def get_citation_details(run_id: str, model_key: str = None):
    """获取引用详情：哪些问题产生了UCloud引用，及具体引用内容

    仅返回 has_citation=1 的记录（贡献了GEO引用率的）
    """
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    all_results = await db.get_results(run_id, model_key)

    # 按模型分组
    by_model = {}
    for r in all_results:
        # 仅保留有UCloud引用的记录
        if not r.get("has_citation"):
            continue

        mk = r["model_key"]
        if mk not in by_model:
            by_model[mk] = {"model_name": r.get("model_name", mk), "citation_questions": []}

        # 解析 citations JSON
        citations_raw = r.get("citations", "[]")
        if isinstance(citations_raw, str):
            try:
                citations_list = json.loads(citations_raw)
            except (json.JSONDecodeError, TypeError):
                citations_list = []
        elif isinstance(citations_raw, list):
            citations_list = citations_raw
        else:
            citations_list = []

        by_model[mk]["citation_questions"].append({
            "question_id": r["question_id"],
            "question_text": "",  # 后续关联 questions 表补充
            "citations": citations_list,
        })

    # 关联 questions 表补充问题文本
    db_conn = await db.get_db()
    try:
        for mk_data in by_model.values():
            for q in mk_data["citation_questions"]:
                cursor = await db_conn.execute(
                    "SELECT question FROM questions WHERE id=?", (q["question_id"],)
                )
                row = await cursor.fetchone()
                if row:
                    q["question_text"] = row["question"]
    finally:
        await db_conn.close()

    return {"success": True, "data": by_model}


@router.get("/{run_id}/citation-channels")
async def get_citation_channel_clustering(run_id: str, model_key: str = None):
    """引用来源渠道聚类统计

    仅统计 ucloud_mentioned=1 的响应中的URL（对GEO评分有贡献），
    按 URL 域名的来源渠道聚类汇总
    """
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    all_results = await db.get_results(run_id, model_key)

    by_model = {}
    for r in all_results:
        # 仅统计UCloud被提及的响应（对GEO评分有贡献）
        if not r.get("ucloud_mentioned"):
            continue

        mk = r["model_key"]
        if mk not in by_model:
            by_model[mk] = {
                "model_name": r.get("model_name", mk),
                "channels": {},  # channel_name -> {count, sample_urls}
            }

        # 解析 all_cited_urls JSON
        urls_raw = r.get("all_cited_urls", "[]")
        if isinstance(urls_raw, str):
            try:
                urls_list = json.loads(urls_raw)
            except (json.JSONDecodeError, TypeError):
                urls_list = []
        elif isinstance(urls_raw, list):
            urls_list = urls_raw
        else:
            urls_list = []

        for url_info in urls_list:
            if url_info.get("citation_type") != "url":
                continue
            channel = url_info.get("source_channel", "其他") or "其他"
            url_content = url_info.get("content", "")

            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "sample_urls": []}
            by_model[mk]["channels"][channel]["count"] += 1
            # 最多保留5个示例URL
            if len(by_model[mk]["channels"][channel]["sample_urls"]) < 5:
                by_model[mk]["channels"][channel]["sample_urls"].append(url_content)

        # 也统计 citations 中 UCloud 的引用
        cits_raw = r.get("citations", "[]")
        if isinstance(cits_raw, str):
            try:
                cits_list = json.loads(cits_raw)
            except (json.JSONDecodeError, TypeError):
                cits_list = []
        elif isinstance(cits_raw, list):
            cits_list = cits_raw
        else:
            cits_list = []

        for cit in cits_list:
            if cit.get("citation_type") != "url":
                continue
            channel = cit.get("source_channel", "其他") or "其他"
            url_content = cit.get("content", "")

            # UCloud引用可能在 all_cited_urls 中被跳过了（位置去重），这里补上
            # 检查是否已统计
            existing_urls = by_model[mk]["channels"].get(channel, {}).get("sample_urls", [])
            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "sample_urls": []}
            # 避免重复计数：通过URL内容去重
            if url_content not in existing_urls or by_model[mk]["channels"][channel]["count"] == 0:
                by_model[mk]["channels"][channel]["count"] += 1
                if len(by_model[mk]["channels"][channel]["sample_urls"]) < 5 and url_content not in existing_urls:
                    by_model[mk]["channels"][channel]["sample_urls"].append(url_content)

    # 转换 channels dict 为列表并排序
    for mk_data in by_model.values():
        channels_list = [
            {"channel": ch, "count": info["count"], "sample_urls": info["sample_urls"]}
            for ch, info in mk_data["channels"].items()
        ]
        channels_list.sort(key=lambda x: x["count"], reverse=True)
        mk_data["channels"] = channels_list

    return {"success": True, "data": by_model}


@router.get("/{run_id}/question-drilldown")
async def get_question_drilldown(run_id: str, model_key: str):
    """问题级下钻：获取某渠道每道题的指标计数（分子/分母）和回答摘要"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    all_results = await db.get_results(run_id, model_key)
    if not all_results:
        return {"success": True, "data": {"model_name": model_key, "total_questions": 0, "questions": []}}

    model_name = all_results[0].get("model_name", model_key)

    # 关联 questions 表获取题目文本、品类、类型
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {"text": row["question"], "category": row["category"], "type": row["question_type"]}
    finally:
        await db_conn.close()

    questions = []
    for r in all_results:
        qid = r["question_id"]
        q_info = question_map.get(qid, {})
        has_error = r.get("error_message") and r["error_message"] != ""

        # 构建指标计数（分子/分母）
        denom = 1  # 每题每个模型只回答一次
        coverage_num = 1 if r.get("ucloud_mentioned") and not has_error else 0
        citation_num = 1 if r.get("has_citation") and not has_error else 0
        recommend_num = 1 if r.get("ucloud_recommended") and not has_error else 0
        strength = r.get("recommendation_strength", "none") or "none"

        # 回答摘要
        raw = r.get("raw_content", "") or ""
        summary = raw[:200] + ("..." if len(raw) > 200 else "") if raw else ""

        questions.append({
            "question_id": qid,
            "question_text": q_info.get("text", qid),
            "category": q_info.get("category", ""),
            "question_type": q_info.get("type", ""),
            "metrics": {
                "coverage": {"numerator": coverage_num, "denominator": denom if not has_error else 0,
                             "value": f"{coverage_num}/{denom}" if not has_error else "-"},
                "citation": {"numerator": citation_num, "denominator": denom if not has_error else 0,
                             "value": f"{citation_num}/{denom}" if not has_error else "-"},
                "recommendation": {"numerator": recommend_num, "denominator": denom if not has_error else 0,
                                   "value": f"{recommend_num}/{denom}" if not has_error else "-",
                                   "strength": strength},
                "sentiment": {"score": round(r.get("sentiment_score", 0.5), 4),
                              "label": r.get("sentiment_label", "neutral")},
            },
            "mention_count": r.get("ucloud_mention_count", 0),
            "position_weight": r.get("position_weight", 0),
            "ucloud_rank": r.get("ucloud_rank"),
            "response_summary": summary,
            "has_error": has_error,
            "error_message": r.get("error_message") if has_error else None,
        })

    return {"success": True, "data": {"model_name": model_name, "total_questions": len(questions), "questions": questions}}


@router.post("/{run_id}/backfill-citations")
async def backfill_citations(run_id: str):
    """从 raw_content 重新提取引用详情并回填 citations/all_cited_urls 列"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    count = await db.backfill_citations(run_id)
    return {"success": True, "data": {"backfilled": count}}


@router.get("/compare")
async def compare_runs(run_id_1: str = Query(...), run_id_2: str = Query(...)):
    """对比两次评测"""
    scores1 = await db.get_scores(run_id_1)
    scores2 = await db.get_scores(run_id_2)
    return {"success": True, "data": {"run_1": scores1, "run_2": scores2}}
