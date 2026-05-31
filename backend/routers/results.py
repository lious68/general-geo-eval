"""结果查询路由"""
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


@router.get("/compare")
async def compare_runs(run_id_1: str = Query(...), run_id_2: str = Query(...)):
    """对比两次评测"""
    scores1 = await db.get_scores(run_id_1)
    scores2 = await db.get_scores(run_id_2)
    return {"success": True, "data": {"run_1": scores1, "run_2": scores2}}
