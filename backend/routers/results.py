"""结果查询路由"""
import json
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import database as db
from services.chart_builder import (
    build_radar_option, build_bar_option, build_coverage_option,
    build_sentiment_option, build_heatmap_option,
)

router = APIRouter(prefix="/api/results", tags=["results"])

# ── 第三方内容平台域名（知乎/CSDN/GitHub 等有具体内容的站点）──
THIRD_PARTY_CONTENT_DOMAINS = [
    "zhihu.com", "zhuanlan.zhihu.com",
    "csdn.net", "blog.csdn.net",
    "juejin.cn", "segmentfault.com", "jianshu.com",
    "cnblogs.com", "infoq.cn", "oschina.net", "oscimg.com",
    "github.com", "gitee.com",
    "bilibili.com",
    "stackoverflow.com", "readthedocs.io",
    "mp.weixin.qq.com",
    "51cto.com",
]

# ── URL 引用类型分类 ──
def _classify_url_type(url: str) -> str:
    """判断一条 URL 是「可能的信息来源」还是「AI生成的引用」。

    规则：
    - 第三方内容平台（知乎/CSDN/GitHub等）上有具体路径的页面 → "可能的信息来源"
    - 首页级、产品页、API endpoint、云厂商官网 → "AI生成的引用"
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")

        # 第三方内容平台 + 有具体路径 → 可能的信息来源
        is_third = any(d in domain for d in THIRD_PARTY_CONTENT_DOMAINS)
        if is_third and len(path) > 5 and path not in ("", "/"):
            return "可能的信息来源"

        # API endpoint / 代码示例中的 endpoint → AI生成的引用
        if domain.startswith("api.") or "/v1/" in path or "/api/" in path:
            return "AI生成的引用"

        # 首页级（空路径或极短路径）→ AI生成的引用
        if path in ("", "/") or len(path) <= 5:
            return "AI生成的引用"

        # 其余：产品页、定价页、文档首页等，都属于AI生成的引用
        return "AI生成的引用"
    except Exception:
        return "AI生成的引用"


def _resolve_citation_channel(url_info: dict) -> str:
    """判定引用构成通道。优先取 citation_channel 字段；无此字段时用 position fallback：
    position < 0 → web_search，position >= 0 → pretraining，无 position → undetected。"""
    channel = url_info.get("citation_channel")
    if channel and channel in ("pretraining", "user_provided", "web_search", "undetected"):
        return channel

    # Fallback：基于 position 判定（兼容已有数据）
    pos = url_info.get("position")
    if pos is not None:
        try:
            if int(pos) < 0:
                return "web_search"
            else:
                return "pretraining"
        except (TypeError, ValueError):
            pass

    return "undetected"


def _extract_cited_urls(r: dict, cache_map: dict = None) -> list:
    """从一条 analysis_result 解析出供前端渲染的引用链接清单。

    all_cited_urls 在库里是 JSON 字符串（或已解析数组），取其中 citation_type=url
    的项，按 content(URL) 去重，返回 [{content, is_ucloud, source_channel, mentions_uc}]。
    供前端结果展示区把引用渲染成可点链接，而不只是 raw_content 纯文本。

    mentions_uc = 该 URL 网页正文是否出现 UCloud/优刻得（来自 url_uc_cache 缓存）：
      True/False/None(未检测)。cache_map 为预取的 {url: mentions_uc}，避免逐条查库。
    """
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
    seen = set()
    out = []
    for u in urls_list:
        if not isinstance(u, dict):
            continue
        if u.get("citation_type") and u.get("citation_type") != "url":
            continue
        c = u.get("content") or u.get("url") or ""
        if not c or not str(c).startswith("http"):
            continue
        if c in seen:
            continue
        seen.add(c)
        # mentions_uc：优先用行内已注入的，否则查 cache_map，否则 None（前端显示"未检测"）
        mu = u.get("mentions_uc")
        if mu is None and cache_map is not None:
            mu = cache_map.get(c)
        out.append({
            "content": c,
            "is_ucloud": bool(u.get("is_ucloud")),
            "source_channel": u.get("source_channel") or _resolve_domain_label(c),
            "mentions_uc": mu,  # True/False/None
            "position": u.get("position"),
            "citation_channel": _resolve_citation_channel(u),
        })
    return out


def _resolve_domain_label(url: str) -> str:
    """从 URL 提取域名，作为'其他'类的细化标签。"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if ":" in domain:
            domain = domain.split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            return "其他"
        # 尝试用 core/config 的映射
        try:
            from config import URL_CHANNEL_MAPPING
        except ImportError:
            import os, sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
            from config import URL_CHANNEL_MAPPING

        if domain in URL_CHANNEL_MAPPING:
            return URL_CHANNEL_MAPPING[domain]
        # 父域名匹配
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            parent = ".".join(parts[i:])
            if parent in URL_CHANNEL_MAPPING:
                return URL_CHANNEL_MAPPING[parent]
        # 没匹配上就用域名本身作为标签
        return domain
    except Exception:
        return "其他"


@router.get("/{run_id}/scores")
async def get_scores(run_id: str, category: str = None, task_id: Optional[str] = None):
    """获取GEO评分"""
    if task_id:
        rows = await db.get_task_scores(task_id, category)
        return {"success": True, "data": rows}
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")
    scores = await db.get_scores(run_id, category)
    return {"success": True, "data": scores}


@router.get("/{run_id}/details")
async def get_details(run_id: str, model_key: str = None, category: str = None,
                      page: int = 1, page_size: int = 50, task_id: Optional[str] = None):
    """获取详细结果"""
    if task_id:
        rows = await db.get_task_results(task_id, model_key)
        return {"success": True, "data": rows}
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    results = await db.get_results(run_id, model_key, category)
    total = len(results)
    start = (page - 1) * page_size
    items = results[start:start + page_size]
    return {"success": True, "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/{run_id}/charts")
async def get_charts(run_id: str, task_id: Optional[str] = None):
    """获取图表配置JSON"""
    if task_id:
        scores = await db.get_task_scores(task_id)
        import database as _db
        db_conn = await _db.get_db()
        try:
            cursor = await db_conn.execute(
                "SELECT * FROM geo_scores WHERE task_id=? AND category IS NOT NULL", (task_id,)
            )
            all_cat_scores = [dict(r) for r in await cursor.fetchall()]
        finally:
            await db_conn.close()
        all_results = await db.get_task_results(task_id)
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

    # 关联 questions 表补充问题文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    # 按模型分组
    by_model = {}
    for r in all_results:
        q_info = question_map.get(r["question_id"], {})
        question_text = q_info.get("text", "")
        citations_list = db.get_effective_citations(r)
        if not citations_list:
            continue

        mk = r["model_key"]
        if mk not in by_model:
            by_model[mk] = {"model_name": r.get("model_name", mk), "citation_questions": []}

        by_model[mk]["citation_questions"].append({
            "question_id": r["question_id"],
            "question_text": question_text,
            "citations": citations_list,
        })

    return {"success": True, "data": by_model}


@router.get("/{run_id}/citation-channels")
async def get_citation_channel_clustering(run_id: str, model_key: str = None,
                                          task_id: Optional[str] = None):
    """引用来源渠道聚类统计

    仅统计 ucloud_mentioned=1 的响应中的URL（对GEO评分有贡献），
    按 URL 域名的来源渠道聚类汇总，附带每条引用的问题和完整URL

    task_id 模式：按大任务聚合该模型的全部 analysis_results（跨批次，
    (task_id,model,question) 唯一去重），run_id 传 "0" 占位、不做 run 存在性校验。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 关联 questions 表获取题目文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    by_model = {}
    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库）
    _chan_all_urls = set()
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        _u = item.get("content") or item.get("url") or ""
                        if _u and str(_u).startswith("http"):
                            _chan_all_urls.add(_u)
    _uc_chan_map = await db.get_url_uc_cached_map(list(_chan_all_urls)) if _chan_all_urls else {}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        mk = r["model_key"]
        qid = r["question_id"]
        q_info = question_map.get(qid, {})

        if mk not in by_model:
            by_model[mk] = {
                "model_name": r.get("model_name", mk),
                "channels": {},  # channel_name -> {count, question_details}
            }

        # 解析 all_cited_urls JSON — 统计所有URL引用来源
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

        seen_urls_this_question = set()

        for url_info in urls_list:
            if url_info.get("citation_type") != "url":
                continue
            channel = url_info.get("source_channel", "其他") or "其他"
            url_content = url_info.get("content", "")

            # 细化"其他"类
            if channel == "其他":
                channel = _resolve_domain_label(url_content)

            if url_content in seen_urls_this_question:
                continue
            seen_urls_this_question.add(url_content)

            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "question_details": []}
            by_model[mk]["channels"][channel]["count"] += 1
            by_model[mk]["channels"][channel]["question_details"].append({
                "question_id": qid,
                "question_text": q_info.get("text", qid),
                "question_category": q_info.get("category", ""),
                "url": url_content,
                "url_type": _classify_url_type(url_content),
                "mentions_uc": _uc_chan_map.get(url_content),
            })

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

            if channel == "其他":
                channel = _resolve_domain_label(url_content)

            if url_content in seen_urls_this_question:
                continue
            seen_urls_this_question.add(url_content)

            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "question_details": []}
            by_model[mk]["channels"][channel]["count"] += 1
            by_model[mk]["channels"][channel]["question_details"].append({
                "question_id": qid,
                "question_text": q_info.get("text", qid),
                "question_category": q_info.get("category", ""),
                "url": url_content,
                "url_type": _classify_url_type(url_content),
                "mentions_uc": _uc_chan_map.get(url_content),
            })

    # 转换 channels dict 为列表并排序，同时提取 sample_urls
    for mk_data in by_model.values():
        channels_list = []
        for ch, info in mk_data["channels"].items():
            # 从 question_details 提取不重复的示例 URL（最多 6 个）
            seen = set()
            sample_urls = []
            for detail in info["question_details"]:
                url = detail.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    sample_urls.append(url)
                    if len(sample_urls) >= 6:
                        break
            channels_list.append({
                "channel": ch,
                "count": info["count"],
                "question_details": info["question_details"],
                "sample_urls": sample_urls,
            })
        channels_list.sort(key=lambda x: x["count"], reverse=True)
        mk_data["channels"] = channels_list

    return {"success": True, "data": by_model}


@router.get("/{run_id}/question-drilldown")
async def get_question_drilldown(run_id: str, model_key: str, task_id: Optional[str] = None):
    """问题级下钻：获取某渠道每道题的指标计数（分子/分母）和回答摘要。

    task_id 模式：按大任务聚合该模型的全部 analysis_results（跨批次，
    (task_id,model,question) 唯一去重），run_id 传 "0" 占位、不做 run 存在性校验。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    if not all_results:
        return {"success": True, "data": {"model_name": model_key, "total_questions": 0, "questions": []}}

    model_name = all_results[0].get("model_name", model_key)

    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库，避免逐条查）
    _all_urls = []
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        u = item.get("content") or item.get("url") or ""
                        if u and str(u).startswith("http"):
                            _all_urls.append(u)
    _uc_cache_map = await db.get_url_uc_cached_map(_all_urls) if _all_urls else {}

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

        # 判断是否为自然问题（引导型和题干含UCloud/优刻得的排除提及率/TOP3推荐率）
        q_text = q_info.get("text", "")
        q_category = q_info.get("category", "")
        is_natural = db.is_natural_question(q_text, q_category)

        # 构建指标计数（分子/分母）
        denom = 1
        coverage_num = 1 if r.get("ucloud_mentioned") and not has_error else 0
        citation_num = 1 if db.has_effective_citation(r) and not has_error else 0
        # TOP3 推荐率分子必须与顶层 metrics.py 一致：rank<=3 才算进 top3，
        # 而非 "回答里出现了推荐词"(ucloud_recommended 布尔)——否则排名#4 的题
        # 会因回答含"强烈推荐"而在抽屉显示 1/1，与顶层聚合(0.4839=15/31)对不上。
        # （0630 doubao q011: rank=4 + ucloud_recommended=1，正是此类边角。）
        rank = r.get("ucloud_rank")
        recommend_num = 1 if (rank is not None and rank <= 3) and not has_error else 0
        strength = r.get("recommendation_strength", "none") or "none"

        # 引导型/非自然问题：提及率和TOP3推荐率显示"-"
        if not is_natural:
            coverage_display = "-"
            recommend_display = "-"
        else:
            coverage_display = f"{coverage_num}/{denom}" if not has_error else "-"
            recommend_display = f"{recommend_num}/{denom}" if not has_error else "-"

        # 回答摘要（表格列用）和完整回答内容（展开区用）
        raw = r.get("raw_content", "") or ""
        summary = raw[:200] + ("..." if len(raw) > 200 else "") if raw else ""
        response_content = raw  # 完整内容，供前端折叠展示

        questions.append({
            "question_id": qid,
            "question_text": q_info.get("text", qid),
            "category": q_category,
            "question_type": q_info.get("type", ""),
            "is_natural": is_natural,
            "metrics": {
                "coverage": {"numerator": coverage_num if is_natural else 0,
                             "denominator": denom if is_natural and not has_error else 0,
                             "value": coverage_display},
                "citation": {"numerator": citation_num, "denominator": denom if not has_error else 0,
                             "value": f"{citation_num}/{denom}" if not has_error else "-"},
                "recommendation": {"numerator": recommend_num if is_natural else 0,
                                   "denominator": denom if is_natural and not has_error else 0,
                                   "value": recommend_display,
                                   "strength": strength if is_natural else "-"},
                "sentiment": {"score": round(r.get("sentiment_score", 0.5), 4),
                              "label": r.get("sentiment_label", "neutral")},
            },
            "mention_count": r.get("ucloud_mention_count", 0),
            "position_weight": r.get("position_weight", 0),
            "ucloud_rank": r.get("ucloud_rank"),
            # 原始标志字段：供前端标签展示（提及/推荐/引用N），与批次结果视图一致。
            # 引导型/非自然题的 metrics.*.numerator 被强制为 0，标签必须用原始字段
            # 才能在引导型题上正确显示"提及"等。
            "ucloud_mentioned": bool(r.get("ucloud_mentioned")),
            "ucloud_recommended": bool(r.get("ucloud_recommended")),
            "citation_count": r.get("citation_count", 0) or 0,
            "has_citation": bool(db.has_effective_citation(r)),
            "response_summary": summary,
            "response_content": response_content,
            "cited_urls": _extract_cited_urls(r, cache_map=_uc_cache_map),
            "has_error": has_error,
            "error_message": r.get("error_message") if has_error else None,
        })

    return {"success": True, "data": {"model_name": model_name, "total_questions": len(questions), "questions": questions}}


@router.get("/{run_id}/citation-drilldown")
async def get_citation_drilldown(run_id: str, source_channel: str = Query(...),
                                 task_id: Optional[str] = None,
                                 model_key: Optional[str] = None):
    """引用源下钻：按来源渠道名称筛选，返回该来源下的所有问题及引用链接

    source_channel 为渠道名（如"UCloud官网"、"知乎"、"阿里云"等）

    task_id 模式：按大任务聚合该模型（或全部模型）的 analysis_results（跨批次去重），
    run_id 传 "0" 占位、不做 run 存在性校验；可选 model_key 过滤单一模型。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 关联 questions 表获取题目文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    by_model = {}
    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库）
    _chan_all_urls = set()
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        _u = item.get("content") or item.get("url") or ""
                        if _u and str(_u).startswith("http"):
                            _chan_all_urls.add(_u)
    _uc_chan_map = await db.get_url_uc_cached_map(list(_chan_all_urls)) if _chan_all_urls else {}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        mk = r["model_key"]
        qid = r["question_id"]
        q_info = question_map.get(qid, {})

        # 收集该条结果中匹配 source_channel 的所有 URL
        matching_urls = []

        # 从 all_cited_urls 中查找
        urls_raw = r.get("all_cited_urls", "[]")
        if isinstance(urls_raw, str):
            try:
                urls_list = json.loads(urls_raw)
            except (json.JSONDecodeError, TypeError):
                urls_list = []
        else:
            urls_list = urls_raw or []

        for url_info in urls_list:
            if url_info.get("citation_type") != "url":
                continue
            channel = url_info.get("source_channel", "其他") or "其他"
            url_content = url_info.get("content", "")
            if channel == "其他":
                channel = _resolve_domain_label(url_content)
            if channel == source_channel:
                matching_urls.append({
                    "content": url_content,
                    "is_ucloud": url_info.get("is_ucloud", False),
                    "url_type": _classify_url_type(url_content),
                    "mentions_uc": _uc_chan_map.get(url_content),
                })

        # 从 citations 中查找
        cits_raw = r.get("citations", "[]")
        if isinstance(cits_raw, str):
            try:
                cits_list = json.loads(cits_raw)
            except (json.JSONDecodeError, TypeError):
                cits_list = []
        else:
            cits_list = cits_raw or []

        for cit in cits_list:
            if cit.get("citation_type") != "url":
                continue
            channel = cit.get("source_channel", "其他") or "其他"
            url_content = cit.get("content", "")
            if channel == "其他":
                channel = _resolve_domain_label(url_content)
            if channel == source_channel:
                # 去重
                if not any(u["content"] == url_content for u in matching_urls):
                    matching_urls.append({
                        "content": url_content,
                        "is_ucloud": cit.get("is_ucloud", False),
                        "url_type": _classify_url_type(url_content),
                        "mentions_uc": _uc_chan_map.get(url_content),
                    })

        if not matching_urls:
            continue

        if mk not in by_model:
            by_model[mk] = {
                "model_name": r.get("model_name", mk),
                "questions": [],
            }

        by_model[mk]["questions"].append({
            "question_id": qid,
            "question_text": q_info.get("text", qid),
            "question_category": q_info.get("category", ""),
            "ucloud_mentioned": bool(r.get("ucloud_mentioned")),
            "urls": matching_urls,
        })

    return {"success": True, "data": by_model}


@router.post("/{run_id}/backfill-citations")
async def backfill_citations(run_id: str):
    """从 raw_content 重新提取引用详情并回填 citations/all_cited_urls 列"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    count = await db.backfill_citations(run_id)
    return {"success": True, "data": {"backfilled": count}}


@router.post("/{run_id}/backfill-url-uc")
async def backfill_url_uc(run_id: str, task_id: Optional[str] = None,
                          concurrency: int = 8):
    """对指定 run/task 范围内的引用 URL 抓取并回填「出现 UCloud」缓存。

    抓取每个 URL 网页正文是否含 UCloud/优刻得，结果存 url_uc_cache 表（跨 task 复用）。
    官方域名短路判 True；抓取失败标 NULL（前端显示"未检测"）。
    task_id 模式：run_id 传 "0" 占位。
    """
    if task_id:
        scope, rid, tid = "task", None, task_id
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        scope, rid, tid = "run", run_id, None

    stats = await db.backfill_url_uc(scope=scope, run_id=rid, task_id=tid,
                                     concurrency=concurrency)
    return {"success": True, "data": stats}


@router.get("/compare")
async def compare_runs(run_id_1: str = Query(...), run_id_2: str = Query(...)):
    """对比两次评测"""
    scores1 = await db.get_scores(run_id_1)
    scores2 = await db.get_scores(run_id_2)
    return {"success": True, "data": {"run_1": scores1, "run_2": scores2}}


@router.get("/{run_id}/citation-breakdown")
async def get_citation_breakdown(run_id: str, model_key: Optional[str] = None,
                                 task_id: Optional[str] = None):
    """引用构成统计：按 citation_channel 四类（预训练/用户提供/网络搜索/未检测）计数。

    只读端点，返回 {pretraining: N, user_provided: N, web_search: N, undetected: N, total: N}。
    task_id 模式：按大任务聚合该模型（或全部模型）的 analysis_results（跨批次去重），
    run_id 传 "0" 占位、不做 run 存在性校验。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 四类计数器
    counts = {"pretraining": 0, "user_provided": 0, "web_search": 0, "undetected": 0}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        # 从 all_cited_urls 解析引用，统计每条的 citation_channel
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

        seen_urls = set()
        for url_info in urls_list:
            if not isinstance(url_info, dict):
                continue
            if url_info.get("citation_type") != "url":
                continue
            url_content = url_info.get("content", "")
            if not url_content or url_content in seen_urls:
                continue
            seen_urls.add(url_content)

            channel = _resolve_citation_channel(url_info)
            counts[channel] += 1

        # 也统计 citations 字段中的引用
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
            if not isinstance(cit, dict):
                continue
            if cit.get("citation_type") != "url":
                continue
            url_content = cit.get("content", "")
            if not url_content or url_content in seen_urls:
                continue
            seen_urls.add(url_content)

            channel = _resolve_citation_channel(cit)
            counts[channel] += 1

    total = sum(counts.values())
    return {
        "success": True,
        "data": {
            "pretraining": counts["pretraining"],
            "user_provided": counts["user_provided"],
            "web_search": counts["web_search"],
            "undetected": counts["undetected"],
            "total": total,
        },
    }


@router.get("/{run_id}/quality-check")
async def get_quality_check(run_id: str, model_key: Optional[str] = None,
                            task_id: Optional[str] = None):
    """抓取质量检查：逐题判定空回声/串题/首页噪声/搜索面板截断/过短/错误。

    只读, 不改 DB/评分。复用 core/webchat_quality.classify（与 CLI 脚本
    check_webchat_results.py 同源, 避免双份漂移）。
    task_id 模式: 按大任务聚合该模型(或全部模型)的 analysis_results,
        run_id 传 "0" 占位、不做 run 存在性校验（与 question-drilldown 同形）。
    model_key 不传: 查该 task/run 全部模型。
    """
    from webchat_quality import classify

    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    if not all_results:
        return {"success": True, "data": {"total": 0, "bad_count": 0, "by_model": {}, "bad": []}}

    # 关联 questions 表获取全题题干（串题判定需全题比对）
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = (row["question"] or "").strip()
    finally:
        await db_conn.close()

    # 按模型分组
    by_model_dict = {}
    for r in all_results:
        by_model_dict.setdefault(r.get("model_key", ""), []).append(r)

    by_model = {}
    bad_list = []
    for mk, results in by_model_dict.items():
        total = len(results)
        bad = 0
        types = {}
        for r in sorted(results, key=lambda x: x.get("question_id", "")):
            qid = r.get("question_id", "")
            raw = r.get("raw_content", "") or ""
            err = r.get("error_message", "") or ""
            qtext = question_map.get(qid, "")
            label, detail = classify(qid, raw, err, qtext, question_map, mk)
            if label != "OK":
                bad += 1
                types[label] = types.get(label, 0) + 1
                bad_list.append({
                    "model": mk,
                    "qid": qid,
                    "question_text": qtext,
                    "type": label,
                    "len": len(raw.strip()),
                    "head": raw[:60].replace("\n", " "),
                    "detail": detail,
                })
        by_model[mk] = {"total": total, "bad": bad, "types": types}

    return {
        "success": True,
        "data": {
            "total": sum(v["total"] for v in by_model.values()),
            "bad_count": len(bad_list),
            "by_model": by_model,
            "bad": bad_list,
        },
    }