"""
UCloud GEO Web - 数据库层
SQLite 异步数据库，管理评测、结果、问题、设置
"""
import os
import sys
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

# core 模块（品牌档案 + 自然问题判定）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from brand_profile import (
    BrandProfile,
    default_brand_profile,
    is_natural_question as is_natural_question_bp,
    build_keyword_pattern,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "geo.db")

# 多品牌：按 brand_id 缓存档案；current_brand_id 指向当前选中品牌。
_BRAND_PROFILE_CACHE: Dict[str, BrandProfile] = {}


def _active_brand_profile() -> BrandProfile:
    """同步辅助：返回 current 品牌档案（缓存未就绪时 fallback UCloud 默认）。
    仅供不能 await 的同步循环（如 is_ucloud_related_citation）兜底用，
    主路径请用 get_brand_profile / get_brand_profile_by_id。"""
    return _BRAND_PROFILE_CACHE.get(_sync_current_brand_id()) or default_brand_profile()


def _sync_current_brand_id() -> str:
    """同步读 current_brand_id 缓存值（由 refresh_brand_cache 预填到 _CURRENT_BRAND_ID_SYNC）。"""
    return _CURRENT_BRAND_ID_SYNC or "ucloud"


_CURRENT_BRAND_ID_SYNC: str = "ucloud"


def get_brand_profile(brand_id: Optional[str] = None) -> BrandProfile:
    """取某品牌档案；brand_id 为 None 时取 current_brand_id。
    缓存未命中时 fallback UCloud 默认（不抛异常，保证同步调用安全）。"""
    bid = brand_id or _sync_current_brand_id()
    return _BRAND_PROFILE_CACHE.get(bid) or default_brand_profile()


def get_brand_profile_by_id(brand_id: str) -> BrandProfile:
    """显式按 brand_id 取档案（评分重算用，不依赖 current）。未命中 fallback default。"""
    return _BRAND_PROFILE_CACHE.get(brand_id) or default_brand_profile()


async def get_current_brand_id() -> str:
    """异步读 current_brand_id（app_settings）。"""
    return await get_setting("current_brand_id", "ucloud") or "ucloud"


async def set_current_brand_id(brand_id: str):
    """设 current_brand_id 并同步到 _CURRENT_BRAND_ID_SYNC 缓存。"""
    global _CURRENT_BRAND_ID_SYNC
    await set_setting("current_brand_id", brand_id)
    _CURRENT_BRAND_ID_SYNC = brand_id


async def refresh_brand_cache():
    """启动/品牌 CRUD 后重载所有 active 品牌档案到缓存 + 同步 current_brand_id。"""
    global _CURRENT_BRAND_ID_SYNC
    _BRAND_PROFILE_CACHE.clear()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, brand_profile_json FROM brands WHERE is_active=1")
        rows = await cursor.fetchall()
    finally:
        await db.close()
    for r in rows:
        try:
            _BRAND_PROFILE_CACHE[r["id"]] = BrandProfile.from_dict(json.loads(r["brand_profile_json"]))
        except (ValueError, TypeError):
            pass
    if not _BRAND_PROFILE_CACHE:
        _BRAND_PROFILE_CACHE["ucloud"] = default_brand_profile()
    _CURRENT_BRAND_ID_SYNC = await get_current_brand_id()


# 向后兼容别名（旧调用方仍可用）
async def refresh_brand_profile_cache():
    await refresh_brand_cache()


THIRD_PARTY_CITATION_DOMAINS = [
    "zhihu.com", "csdn.net", "juejin.cn", "github.com", "bilibili.com",
    "segmentfault.com", "oschina.net", "cnblogs.com", "infoq.cn", "51cto.com",
    "mp.weixin.qq.com",
    # 补充常见中文技术/资讯社区
    "jianshu.com", "oscimg.com", "weibo.com", "36kr.com",
    "stackoverflow.com", "gitee.com", "readthedocs.io",
    "tianyancha.com", "qcc.com",
    # 自媒体平台（头条/百家号/搜狐号/网易号）
    "toutiao.com", "baijiahao.baidu.com", "sohu.com", "163.com",
]


def is_ucloud_related_citation(row: Dict[str, Any], item: Dict[str, Any], window: int = 180,
                               profile: Optional[BrandProfile] = None) -> bool:
    """判断第三方引用 URL 附近上下文是否在讲被测品牌。

    对于 API 返回的搜索引用（position < 0），直接视为有效引用，
    因为 API 搜索结果本身就是模型回答的来源，与回答主题相关。
    """
    if item.get("is_ucloud"):
        return True
    # API 搜索引用（position 为负数）直接视为与被测品牌相关
    position = item.get("position")
    if position is not None:
        try:
            pos = int(position)
            if pos < 0:
                return True
        except (TypeError, ValueError):
            pass
    content = row.get("raw_content") or ""
    if not content or position is None:
        return False
    try:
        pos = int(position)
    except (TypeError, ValueError):
        return False
    context = content[max(0, pos - window): min(len(content), pos + window)]
    p = profile or _active_brand_profile()
    pattern = build_keyword_pattern(p.context_keywords())
    return bool(pattern.search(context))


def get_effective_citations(row: Dict[str, Any], profile: Optional[BrandProfile] = None) -> List[Dict[str, Any]]:
    """返回按新引用口径计入的引用明细。"""
    raw_citations = row.get("citations") or "[]"
    raw_urls = row.get("all_cited_urls") or "[]"
    try:
        citations = json.loads(raw_citations) if isinstance(raw_citations, str) else (raw_citations or [])
    except (json.JSONDecodeError, TypeError):
        citations = []
    try:
        urls = json.loads(raw_urls) if isinstance(raw_urls, str) else (raw_urls or [])
    except (json.JSONDecodeError, TypeError):
        urls = []

    effective = []
    for cit in citations or []:
        if not isinstance(cit, dict):
            continue
        if cit.get("citation_type") == "url" and not is_ucloud_related_citation(row, cit, profile=profile):
            continue
        effective.append(cit)
    # 从 all_cited_urls 中补充有效引用
    # 已在 citations 中的 API 搜索引用（position < 0）无需重复处理
    seen = {
        (c.get("citation_type"), c.get("content"), c.get("position"))
        for c in effective if isinstance(c, dict)
    }
    for item in urls or []:
        if not isinstance(item, dict) or item.get("citation_type") != "url":
            continue
        key = ("url", item.get("content"), item.get("position"))
        if key in seen:
            continue
        # API 搜索引用（position < 0）已经过 analyzer 认定，直接计入
        try:
            pos = int(item.get("position", 0))
            is_api_search = pos < 0
        except (TypeError, ValueError):
            is_api_search = False

        if is_api_search:
            effective.append({**item, "is_ucloud": bool(item.get("is_ucloud", False))})
            seen.add(key)
            continue

        # 正文中出现的 URL：仅当回答提及被测品牌时，
        # 且来自第三方来源域名、且上下文与被测品牌相关，才计入
        if not row.get("ucloud_mentioned"):
            continue
        url = (item.get("content") or "").lower()
        if not any(domain in url for domain in THIRD_PARTY_CITATION_DOMAINS):
            continue
        if not is_ucloud_related_citation(row, item, profile=profile):
            continue
        effective.append({**item, "is_ucloud": bool(item.get("is_ucloud", False))})
        seen.add(key)
    return effective


def has_effective_citation(row: Dict[str, Any], profile: Optional[BrandProfile] = None) -> bool:
    """按新口径判断是否有有效引用：官方引用，或提及被测品牌时的第三方来源引用。"""
    return len(get_effective_citations(row, profile=profile)) > 0


def _natural_question_filter_sql(alias: str = "q") -> str:
    """[已废弃] 排除引导型及题干自带品牌词的问题。

    早期 SQL 版自然问题过滤，写死了 UCloud/优刻得。当前自然问题判定统一走
    is_natural_question()（基于品牌档案），此函数保留仅供历史参考，不再被调用。
    """
    q = f"{alias}.question"
    c = f"{alias}.category"
    return (
        f"(({c} IS NULL OR {c} != '引导型') AND (({q} IS NULL) OR ("
        f"LOWER(REPLACE({q}, ' ', '')) NOT LIKE '%ucloud%' "
        f"AND REPLACE({q}, ' ', '') NOT LIKE '%优刻得%')))"
    )


def is_natural_question(question: str, category: str = "",
                        profile: Optional[BrandProfile] = None) -> bool:
    """非引导型且题干不含被测品牌词时，视为自然问题（品牌档案来自缓存）。"""
    p = profile or _active_brand_profile()
    return is_natural_question_bp(question, category, p)


def is_natural_question_text(question: str) -> bool:
    """题干不含被测品牌词时，视为自然问题。"""
    return is_natural_question(question)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT DEFAULT 'pending',
    model_keys TEXT,
    question_ids TEXT,
    total_questions INTEGER,
    completed_questions INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    config TEXT,
    mode TEXT DEFAULT 'api'
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES evaluation_runs(id),
    question_id TEXT,
    model_key TEXT,
    model_name TEXT,
    ucloud_mentioned INTEGER DEFAULT 0,
    ucloud_mention_count INTEGER DEFAULT 0,
    ucloud_rank INTEGER,
    has_citation INTEGER DEFAULT 0,
    citation_count INTEGER DEFAULT 0,
    ucloud_recommended INTEGER DEFAULT 0,
    recommendation_strength TEXT DEFAULT 'none',
    sentiment_score REAL DEFAULT 0.5,
    sentiment_label TEXT DEFAULT 'neutral',
    position_weight REAL DEFAULT 0.0,
    response_length INTEGER DEFAULT 0,
    raw_content TEXT DEFAULT '',
    competitor_mentions TEXT DEFAULT '{}',
    error_message TEXT,
    citations TEXT DEFAULT '[]',
    all_cited_urls TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geo_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES evaluation_runs(id),
    model_key TEXT,
    model_name TEXT,
    category TEXT,
    geo_score REAL DEFAULT 0,
    coverage_rate REAL DEFAULT 0,
    mention_rate REAL DEFAULT 0,
    citation_rate REAL DEFAULT 0,
    recommendation_rate REAL DEFAULT 0,
    sentiment_score REAL DEFAULT 0,
    avg_rank REAL DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    valid_responses INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS batch_import_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    run_id TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    results_inserted INTEGER DEFAULT 0,
    file_name TEXT,
    file_size INTEGER
);
CREATE INDEX IF NOT EXISTS idx_bil_batch ON batch_import_logs(task_id, batch_id, imported_at);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    username TEXT,
    role TEXT DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    category TEXT,
    question_type TEXT,
    question TEXT,
    tags TEXT DEFAULT '[]',
    difficulty TEXT DEFAULT 'medium',
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 三级任务架构：任务 → 模型 → 问题 单元表
-- 每个 (run_id, model_key, question_id) 单元自带状态，是断点续跑的唯一事实来源。
-- scheduler（core/scheduler.py）通过 core/task_units.SqliteUnitStore 落库；
-- 此表也让 server 端可异步查询评测进度。
CREATE TABLE IF NOT EXISTS task_units (
    run_id      TEXT NOT NULL,
    model_key   TEXT NOT NULL,
    question_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending|running|done|failed|skipped
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT DEFAULT '',
    content     TEXT DEFAULT '',
    raw_response TEXT DEFAULT '',
    model_name  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT '',
    PRIMARY KEY (run_id, model_key, question_id)
);
CREATE INDEX IF NOT EXISTS idx_task_units_run_status ON task_units(run_id, status);

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    question_ids  TEXT NOT NULL,
    categories    TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'active',
    notes         TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS brands (
    id                 TEXT PRIMARY KEY,
    brand_name         TEXT NOT NULL,
    company_name       TEXT DEFAULT '',
    website           TEXT DEFAULT '',
    industry          TEXT DEFAULT '',
    brand_profile_json TEXT NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active         INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_brands_active ON brands(is_active);
"""


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    """初始化数据库（建表 + 导入默认数据）"""
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        await db.commit()

        # 迁移：添加 citations 和 all_cited_urls 列
        await _migrate_add_columns(db)

        # 检查是否已有问题数据
        cursor = await db.execute("SELECT COUNT(*) FROM questions")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await _import_default_questions(db)
    finally:
        await db.close()

    # 预置 ucloud 品牌 + current_brand_id（多品牌迁移：幂等）
    db = await get_db()
    try:
        await _ensure_default_brand(db)
    finally:
        await db.close()

    # 加载被测品牌档案到缓存（自然问题/引用上下文判定用）
    await refresh_brand_cache()


async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """判断某列是否已存在（ADD COLUMN 幂等前置检查）。"""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return any(r["name"] == column for r in rows)


async def _migrate_add_columns(db: aiosqlite.Connection):
    """安全添加新列（兼容已有数据库）"""
    for col in ["citations", "all_cited_urls"]:
        try:
            await db.execute(f"ALTER TABLE analysis_results ADD COLUMN {col} TEXT DEFAULT '[]'")
            await db.commit()
        except aiosqlite.OperationalError:
            pass  # 列已存在

    # 添加 mode 列到 evaluation_runs
    try:
        await db.execute("ALTER TABLE evaluation_runs ADD COLUMN mode TEXT DEFAULT 'api'")
        await db.commit()
    except aiosqlite.OperationalError:
        pass  # 列已存在

    # 添加 username/role 列到 admin_sessions
    for col_name, col_default in [("username", None), ("role", "'admin'")]:
        try:
            default_clause = f" DEFAULT {col_default}" if col_default else ""
            await db.execute(f"ALTER TABLE admin_sessions ADD COLUMN {col_name} TEXT{default_clause}")
            await db.commit()
        except aiosqlite.OperationalError:
            pass  # 列已存在

    # 自动将旧 admin_password_hash 迁移为 admin 用户
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        user_count = (await cursor.fetchone())[0]
        if user_count == 0:
            cursor = await db.execute("SELECT value FROM app_settings WHERE key='admin_password_hash'")
            row = await cursor.fetchone()
            if row and row["value"]:
                await db.execute(
                    "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    ("admin", row["value"], "admin")
                )
                await db.commit()
    except Exception:
        pass

    # tasks 改造：evaluation_runs / analysis_results / geo_scores 加 task_id, batch_id
    for table, cols in [
        ("evaluation_runs", [("task_id", "TEXT"), ("batch_id", "TEXT")]),
        ("analysis_results", [("task_id", "TEXT"), ("batch_id", "TEXT")]),
        ("geo_scores", [("task_id", "TEXT")]),
    ]:
        for col_name, col_type in cols:
            if not await column_exists(db, table, col_name):
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                await db.commit()

    # analysis_results 上 (task_id, model_key, question_id) 唯一索引（NULL task_id 行互异，不受约束）
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ar_task_model_q "
        "ON analysis_results(task_id, model_key, question_id)"
    )
    await db.commit()

    # 多品牌：questions/tasks/runs/results/scores 加 brand_id（默认 ucloud）+ 索引
    for table in ["questions", "tasks", "evaluation_runs", "analysis_results", "geo_scores"]:
        if not await column_exists(db, table, "brand_id"):
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN brand_id TEXT DEFAULT 'ucloud'"
            )
            await db.commit()
    await db.execute("CREATE INDEX IF NOT EXISTS idx_questions_brand ON questions(brand_id, is_active)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_brand ON tasks(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_brand ON evaluation_runs(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_results_brand ON analysis_results(brand_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_scores_brand ON geo_scores(brand_id)")
    await db.commit()


async def _ensure_default_brand(db: aiosqlite.Connection):
    """幂等预置 ucloud 品牌 + current_brand_id。已有 brands 行则不覆盖。"""
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    from brand_profile import default_brand_profile

    cur = await db.execute("SELECT COUNT(*) FROM brands")
    n = (await cur.fetchone())[0]
    if n == 0:
        profile = default_brand_profile()
        await db.execute(
            "INSERT OR IGNORE INTO brands (id, brand_name, company_name, website, industry, brand_profile_json, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("ucloud", profile.brand_name, profile.company_name,
             profile.website, profile.industry, profile.to_json())
        )
        await db.commit()
    # current_brand_id 默认 ucloud
    await db.execute(
        "INSERT INTO app_settings (key, value) VALUES ('current_brand_id', 'ucloud') "
        "ON CONFLICT(key) DO NOTHING"
    )
    await db.commit()


async def _import_default_questions(db: aiosqlite.Connection):
    """导入默认问题集"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    from questions import QUESTIONS

    for q in QUESTIONS:
        await db.execute(
            "INSERT OR IGNORE INTO questions (id, category, question_type, question, tags, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
            (q.id, q.category, q.question_type, q.question, json.dumps(q.tags, ensure_ascii=False), q.difficulty)
        )
    await db.commit()


# ============ 评测运行 ============

async def create_run(run_id: str, name: str, model_keys: List[str],
                     question_ids: List[str], config: Dict = None, mode: str = "api"):
    """创建评测运行"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO evaluation_runs (id, name, status, model_keys, question_ids, total_questions, config, mode)
               VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)""",
            (run_id, name, json.dumps(model_keys), json.dumps(question_ids),
             len(question_ids) * len(model_keys), json.dumps(config or {}), mode)
        )
        await db.commit()
    finally:
        await db.close()


async def update_run_status(run_id: str, status: str, completed: int = None):
    """更新评测状态"""
    db = await get_db()
    try:
        if status == "running" and completed is None:
            await db.execute(
                "UPDATE evaluation_runs SET status=?, started_at=? WHERE id=?",
                (status, datetime.now().isoformat(), run_id)
            )
        elif status == "completed":
            # 确保 started_at 已设置（导入场景可能为 NULL）
            await db.execute(
                """UPDATE evaluation_runs
                   SET status=?, completed_at=?, completed_questions=COALESCE(?,completed_questions),
                       started_at=COALESCE(started_at, ?)
                   WHERE id=?""",
                (status, datetime.now().isoformat(), completed, datetime.now().isoformat(), run_id)
            )
        elif status == "failed":
            await db.execute(
                "UPDATE evaluation_runs SET status=? WHERE id=?",
                (status, run_id)
            )
        elif status == "cancelled":
            await db.execute(
                "UPDATE evaluation_runs SET status=?, completed_at=?, completed_questions=COALESCE(?,completed_questions) WHERE id=?",
                (status, datetime.now().isoformat(), completed, run_id)
            )
        else:
            await db.execute(
                "UPDATE evaluation_runs SET status=?, completed_questions=COALESCE(?,completed_questions) WHERE id=?",
                (status, completed, run_id)
            )
        await db.commit()
    finally:
        await db.close()


async def get_runs(limit: int = 50, offset: int = 0) -> List[Dict]:
    """获取评测列表"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluation_runs ORDER BY COALESCE(started_at, completed_at) DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_run(run_id: str) -> Optional[Dict]:
    """获取单个评测"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM evaluation_runs WHERE id=?", (run_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def delete_run(run_id: str):
    """删除评测及相关结果"""
    db = await get_db()
    try:
        await db.execute("DELETE FROM analysis_results WHERE run_id=?", (run_id,))
        await db.execute("DELETE FROM geo_scores WHERE run_id=?", (run_id,))
        await db.execute("DELETE FROM evaluation_runs WHERE id=?", (run_id,))
        await db.commit()
    finally:
        await db.close()


# ============ 分析结果 ============

async def save_analysis_result(run_id: str, result: Dict):
    """保存单条分析结果"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO analysis_results
               (run_id, question_id, model_key, model_name,
                ucloud_mentioned, ucloud_mention_count, ucloud_rank,
                has_citation, citation_count,
                ucloud_recommended, recommendation_strength,
                sentiment_score, sentiment_label, position_weight,
                response_length, raw_content, competitor_mentions, error_message,
                citations, all_cited_urls)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, result["question_id"], result["model_key"], result["model_name"],
             int(result["ucloud_mentioned"]), result["ucloud_mention_count"], result.get("ucloud_rank"),
             int(result["has_citation"]), result["citation_count"],
             int(result["ucloud_recommended"]), result["recommendation_strength"],
             result["sentiment_score"], result["sentiment_label"], result["position_weight"],
             result["response_length"], result.get("raw_content", ""),
             json.dumps(result.get("competitor_mentions", {}), ensure_ascii=False),
             result.get("error_message"),
             json.dumps(result.get("citations", []), ensure_ascii=False),
             json.dumps(result.get("all_cited_urls", []), ensure_ascii=False))
        )
        await db.commit()
    finally:
        await db.close()


async def save_geo_scores(run_id: str, model_key: str, model_name: str,
                          category: Optional[str], scores: Dict):
    """保存GEO评分"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO geo_scores
               (run_id, model_key, model_name, category,
                geo_score, coverage_rate, mention_rate, citation_rate,
                recommendation_rate, sentiment_score, avg_rank,
                total_questions, valid_responses)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, model_key, model_name, category,
             scores["geo_score"], scores["coverage_rate"], scores["mention_rate"],
             scores["citation_rate"], scores["recommendation_rate"],
             scores["sentiment_score"], scores["avg_rank"],
             scores["total_questions"], scores["valid_responses"])
        )
        await db.commit()
    finally:
        await db.close()


async def get_results(run_id: str, model_key: str = None,
                      category: str = None) -> List[Dict]:
    """获取评测结果"""
    db = await get_db()
    try:
        query = "SELECT * FROM analysis_results WHERE run_id=?"
        params = [run_id]
        if model_key:
            query += " AND model_key=?"
            params.append(model_key)
        if category:
            query += " AND question_id IN (SELECT id FROM questions WHERE category=?)"
            params.append(category)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_scores(run_id: str, category: str = None) -> List[Dict]:
    """获取GEO评分"""
    db = await get_db()
    try:
        query = "SELECT * FROM geo_scores WHERE run_id=?"
        params = [run_id]
        if category:
            query += " AND category=?"
            params.append(category)
        else:
            query += " AND category IS NULL"
        cursor = await db.execute(query, params)
        rows = [dict(r) for r in await cursor.fetchall()]

        # 动态按最新口径回填指标，历史评测无需重跑：
        # - 提及率 / TOP3 推荐率：分母只算自然问题
        # - 引用率 / 情感值：分母使用全部有效问题
        for row in rows:
            metrics_query = """
                SELECT
                    ar.*,
                    q.question,
                    q.category
                FROM analysis_results ar
                JOIN questions q ON q.id = ar.question_id
                WHERE ar.run_id=?
                  AND ar.model_key=?
                  AND (ar.error_message IS NULL OR ar.error_message='')
            """
            metrics_params = [run_id, row["model_key"]]
            if row.get("category"):
                metrics_query += " AND q.category=?"
                metrics_params.append(row["category"])

            metrics_cursor = await db.execute(metrics_query, metrics_params)
            metric_rows = [dict(r) for r in await metrics_cursor.fetchall()]
            all_valid_count = len(metric_rows)
            natural_rows = [
                r for r in metric_rows
                if is_natural_question(r.get("question", ""), r.get("category", ""))
            ]
            natural_valid_count = len(natural_rows)

            row["valid_responses"] = all_valid_count
            if natural_valid_count:
                mentioned_count = sum(1 for r in natural_rows if r.get("ucloud_mentioned"))
                top3_count = sum(
                    1 for r in natural_rows
                    if r.get("ucloud_rank") is not None and r.get("ucloud_rank") <= 3
                )
                rank_values = [r.get("ucloud_rank") for r in natural_rows if r.get("ucloud_rank") is not None]
                row["coverage_rate"] = round(mentioned_count / natural_valid_count, 4)
                row["recommendation_rate"] = round(top3_count / natural_valid_count, 4)
                row["avg_rank"] = round(sum(rank_values) / len(rank_values), 2) if rank_values else 0
            else:
                row["coverage_rate"] = 0
                row["recommendation_rate"] = 0
                row["avg_rank"] = 0

            if all_valid_count:
                citation_count = sum(1 for r in metric_rows if has_effective_citation(r))
                sentiment_values = [r.get("sentiment_score") or 0 for r in metric_rows]
                row["citation_rate"] = round(citation_count / all_valid_count, 4)
                row["sentiment_score"] = round(sum(sentiment_values) / all_valid_count, 4)
            else:
                row["citation_rate"] = 0
                row["sentiment_score"] = 0

            row["geo_score"] = round((
                (row.get("coverage_rate") or 0) * 0.45 +
                (row.get("citation_rate") or 0) * 0.25 +
                (row.get("recommendation_rate") or 0) * 0.20 +
                (row.get("sentiment_score") or 0) * 0.10
            ) * 100, 2)

        return rows
    finally:
        await db.close()


# ============ 问题管理 ============

async def get_questions(category: str = None, question_type: str = None,
                       active_only: bool = True, brand_id: str = None) -> List[Dict]:
    """获取问题列表。brand_id 为 None 时取 current 品牌。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        query = "SELECT * FROM questions WHERE brand_id=?"
        params = [brand_id]
        if active_only:
            query += " AND is_active=1"
        if category:
            query += " AND category=?"
            params.append(category)
        if question_type:
            query += " AND question_type=?"
            params.append(question_type)
        query += " ORDER BY id"
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def upsert_question(q: Dict, brand_id: str = None):
    """新增或更新问题。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO questions (id, category, question_type, question, tags, difficulty, is_active, brand_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(id) DO UPDATE SET
               category=excluded.category, question_type=excluded.question_type,
               question=excluded.question, tags=excluded.tags, difficulty=excluded.difficulty,
               brand_id=excluded.brand_id""",
            (q["id"], q["category"], q["question_type"], q["question"],
             json.dumps(q.get("tags", []), ensure_ascii=False), q.get("difficulty", "medium"), brand_id)
        )
        await db.commit()
    finally:
        await db.close()


async def delete_question(question_id: str):
    """删除问题"""
    db = await get_db()
    try:
        await db.execute("UPDATE questions SET is_active=0 WHERE id=?", (question_id,))
        await db.commit()
    finally:
        await db.close()


async def deactivate_all_questions(brand_id: str = None):
    """把某品牌的全部问题置为 inactive（生成新题集前清场）。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute("UPDATE questions SET is_active=0 WHERE brand_id=?", (brand_id,))
        await db.commit()
    finally:
        await db.close()


async def save_brand_profile(profile: BrandProfile, brand_id: str = None):
    """更新某品牌档案到 brands 表并刷新缓存。
    brand_id 为 None 时更新 current 品牌。同时镜像 brand_keywords 兼容旧接口。"""
    bid = brand_id or await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE brands SET brand_profile_json=?, brand_name=?, company_name=?, website=?, industry=? "
            "WHERE id=?",
            (profile.to_json(), profile.brand_name, profile.company_name,
             profile.website, profile.industry, bid)
        )
        await db.commit()
    finally:
        await db.close()
    await set_setting("brand_keywords", json.dumps(profile.keywords, ensure_ascii=False))
    _BRAND_PROFILE_CACHE[bid] = profile


# ============ 品牌库（多品牌） ============

async def list_brands() -> List[Dict]:
    """列出所有 active 品牌，含题集数/任务数摘要。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT b.id, b.brand_name, b.company_name, b.website, b.industry, "
            "b.created_at, b.is_active, "
            "(SELECT COUNT(*) FROM questions WHERE brand_id=b.id AND is_active=1) AS question_count, "
            "(SELECT COUNT(*) FROM tasks WHERE brand_id=b.id AND status='active') AS task_count "
            "FROM brands b WHERE b.is_active=1 ORDER BY b.created_at ASC"
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_brand(brand_id: str) -> Optional[Dict]:
    """取单品牌（含 brand_profile dict）。仅返回 active。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM brands WHERE id=? AND is_active=1", (brand_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        b = dict(row)
        try:
            b["brand_profile"] = json.loads(b["brand_profile_json"])
        except (ValueError, TypeError):
            b["brand_profile"] = {}
        return b
    finally:
        await db.close()


async def create_brand(brand_id: str, profile: BrandProfile) -> Dict:
    """新建品牌。id 冲突抛 ValueError。"""
    db = await get_db()
    try:
        existing = await db.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,))
        if await existing.fetchone():
            raise ValueError(f"品牌 id '{brand_id}' 已存在")
        await db.execute(
            "INSERT INTO brands (id, brand_name, company_name, website, industry, brand_profile_json, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (brand_id, profile.brand_name, profile.company_name,
             profile.website, profile.industry, profile.to_json())
        )
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE[brand_id] = profile
    return {"id": brand_id, "brand_name": profile.brand_name,
            "company_name": profile.company_name, "website": profile.website,
            "industry": profile.industry}


async def update_brand(brand_id: str, profile: BrandProfile):
    """更新品牌档案（重新 derive 后调用）。"""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE brands SET brand_name=?, company_name=?, website=?, industry=?, brand_profile_json=? "
            "WHERE id=?",
            (profile.brand_name, profile.company_name, profile.website,
             profile.industry, profile.to_json(), brand_id)
        )
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE[brand_id] = profile


async def delete_brand(brand_id: str):
    """软删品牌（is_active=0）。若有活跃题集/任务，抛 ValueError 提示先清空。
    ucloud 不可删。"""
    if brand_id == "ucloud":
        raise ValueError("ucloud 为预置默认品牌，不可删除")
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM questions WHERE brand_id=? AND is_active=1 LIMIT 1", (brand_id,))
        if await cur.fetchone():
            raise ValueError(f"品牌 '{brand_id}' 仍有活跃题集，请先清空题集再删")
        cur = await db.execute("SELECT 1 FROM tasks WHERE brand_id=? AND status='active' LIMIT 1", (brand_id,))
        if await cur.fetchone():
            raise ValueError(f"品牌 '{brand_id}' 仍有活跃任务，请先删除任务再删")
        await db.execute("UPDATE brands SET is_active=0 WHERE id=?", (brand_id,))
        await db.commit()
    finally:
        await db.close()
    _BRAND_PROFILE_CACHE.pop(brand_id, None)


# ============ 设置 ============

async def get_setting(key: str, default: str = None) -> Optional[str]:
    """获取设置"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM app_settings WHERE key=?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default
    finally:
        await db.close()


async def set_setting(key: str, value: str):
    """设置"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_settings() -> Dict[str, str]:
    """获取所有设置"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM app_settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        await db.close()


# ============ 认证 ============

async def create_session(token: str, username: str = "admin", role: str = "admin", hours: int = 24):
    """创建登录会话"""
    from datetime import timedelta
    db = await get_db()
    try:
        expires = (datetime.now() + timedelta(hours=hours)).isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO admin_sessions (token, created_at, expires_at, username, role) VALUES (?, datetime('now'), ?, ?, ?)",
            (token, expires, username, role)
        )
        await db.commit()
    finally:
        await db.close()


async def verify_session(token: str) -> Optional[Dict]:
    """验证会话token，返回用户信息或None"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT expires_at, username, role FROM admin_sessions WHERE token=?",
            (token,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        from datetime import datetime
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > expires:
            await db.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
            await db.commit()
            return None
        user_info = {
            "username": row["username"] or "admin",
            "role": row["role"] or "admin",
        }
        return user_info
    except Exception:
        return None
    finally:
        await db.close()


async def delete_session(token: str):
    """删除会话"""
    db = await get_db()
    try:
        await db.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
        await db.commit()
    finally:
        await db.close()


async def get_admin_password_hash() -> str:
    """获取管理员密码hash"""
    return await get_setting("admin_password_hash", "")


async def set_admin_password_hash(hashed: str):
    """设置管理员密码hash"""
    await set_setting("admin_password_hash", hashed)


# ============ 用户管理 ============

async def create_user(username: str, password_hash: str, role: str = "viewer") -> int:
    """创建用户"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role)
        )
        await db.commit()
        return cursor.lastrowid
    except aiosqlite.IntegrityError:
        raise ValueError(f"用户名 '{username}' 已存在")
    finally:
        await db.close()


async def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名获取用户"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE username=?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_users() -> List[Dict]:
    """列出所有用户"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def delete_user(user_id: int):
    """删除用户"""
    db = await get_db()
    try:
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()
    finally:
        await db.close()


async def update_user_password(username: str, password_hash: str):
    """更新用户密码"""
    db = await get_db()
    try:
        await db.execute("UPDATE users SET password_hash=? WHERE username=?", (password_hash, username))
        await db.commit()
    finally:
        await db.close()


async def backfill_citations(run_id: str) -> int:
    """从 raw_content 重新提取引用详情并回填 citations/all_cited_urls 列

    返回回填的记录数
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    from analyzer import ResponseAnalyzer, AnalysisResult

    db = await get_db()
    analyzer = ResponseAnalyzer(brand_profile=_active_brand_profile())
    count = 0
    try:
        cursor = await db.execute(
            "SELECT id, raw_content FROM analysis_results WHERE run_id=? AND raw_content != ''",
            (run_id,)
        )
        rows = await cursor.fetchall()

        for row in rows:
            content = row["raw_content"]
            if not content:
                continue

            # 重新运行引用检测（_detect_citations 内部已用 GEO 口径写 has_citation）
            result = AnalysisResult(question_id="", model_key="", model_name="")
            result.raw_content = content
            analyzer._detect_citations(content, result)

            citations_json = json.dumps(
                [{"citation_type": c.citation_type, "content": c.content,
                  "position": c.position, "source_channel": c.source_channel,
                  "is_ucloud": c.is_ucloud}
                 for c in result.citations],
                ensure_ascii=False
            )
            all_urls_json = json.dumps(
                [{"citation_type": c.citation_type, "content": c.content,
                  "position": c.position, "source_channel": c.source_channel,
                  "is_ucloud": c.is_ucloud}
                 for c in result.all_cited_urls],
                ensure_ascii=False
            )

            # 同步回填 has_citation / citation_count（GEO 口径），避免与重算不一致
            await db.execute(
                "UPDATE analysis_results SET citations=?, all_cited_urls=?, "
                "has_citation=?, citation_count=? WHERE id=?",
                (citations_json, all_urls_json,
                 int(result.has_citation), result.citation_count, row["id"])
            )
            count += 1

        await db.commit()
    finally:
        await db.close()

    return count


# ============ 三级任务单元（task_units）============

# 单元状态机与 schema 见 SCHEMA_SQL 末尾；落库主路径由 core/task_units.SqliteUnitStore
# （同步 sqlite3）完成，这里提供 server 端异步查询的只读/统计接口。

async def get_task_unit(run_id: str, model_key: str, question_id: str) -> Optional[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM task_units WHERE run_id=? AND model_key=? AND question_id=?",
            (run_id, model_key, question_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_task_units(run_id: str, status: Optional[str] = None) -> List[Dict]:
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                "SELECT * FROM task_units WHERE run_id=? AND status=? ORDER BY question_id, model_key",
                (run_id, status),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM task_units WHERE run_id=? ORDER BY question_id, model_key",
                (run_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def count_task_units(run_id: str) -> Dict[str, int]:
    """按 status 统计单元数。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT status, COUNT(*) AS c FROM task_units WHERE run_id=? GROUP BY status",
            (run_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    out = {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0}
    for r in rows:
        out[r["status"]] = r["c"]
    return out


# ============================================================
# Task 顶层（三级任务架构：任务 → 模型 → 问题）
# ============================================================

async def create_task(task_id: str, name: str, question_ids: List[str],
                      categories: Optional[List[str]] = None, brand_id: str = None) -> Dict:
    """创建任务（固定总题集，创建时拍板）。brand_id 默认 current。"""
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tasks (id, name, question_ids, categories, status, brand_id) "
            "VALUES (?, ?, ?, ?, 'active', ?)",
            (task_id, name, json.dumps(question_ids),
             json.dumps(categories or []), brand_id)
        )
        await db.commit()
        return await get_task(task_id)
    finally:
        await db.close()


async def get_task(task_id: str) -> Optional[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        t = dict(row)
        t["question_ids"] = json.loads(t["question_ids"]) if isinstance(t["question_ids"], str) else t["question_ids"]
        t["categories"] = json.loads(t["categories"]) if isinstance(t.get("categories"), str) else (t.get("categories") or [])
        return t
    finally:
        await db.close()


async def list_tasks(limit: int = 100, offset: int = 0, brand_id: str = None) -> List[Dict]:
    if brand_id is None:
        brand_id = await get_current_brand_id()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE brand_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (brand_id, limit, offset)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for t in rows:
            t["question_ids"] = json.loads(t["question_ids"]) if isinstance(t["question_ids"], str) else t["question_ids"]
            t["categories"] = json.loads(t["categories"]) if isinstance(t.get("categories"), str) else (t.get("categories") or [])
        return rows
    finally:
        await db.close()


async def delete_task(task_id: str):
    """级联删除 task + 其下批次 runs + results + scores。"""
    db = await get_db()
    try:
        # 先删该 task 下的 analysis_results / geo_scores
        await db.execute("DELETE FROM analysis_results WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM geo_scores WHERE task_id=?", (task_id,))
        # 删该 task 下的批次 run（先收 run_id 再删 results）
        cur = await db.execute("SELECT id FROM evaluation_runs WHERE task_id=?", (task_id,))
        run_ids = [r["id"] for r in await cur.fetchall()]
        for rid in run_ids:
            await db.execute("DELETE FROM analysis_results WHERE run_id=?", (rid,))
            await db.execute("DELETE FROM geo_scores WHERE run_id=?", (rid,))
        await db.execute("DELETE FROM evaluation_runs WHERE task_id=?", (task_id,))
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.commit()
    finally:
        await db.close()


async def add_task_batch(run_id: str, task_id: str, batch_id: str, name: str,
                         model_keys: List[str], question_ids: List[str],
                         per_model: Dict[str, List[str]], config: Optional[Dict] = None) -> Dict:
    """在 task 下建一个下载批次。brand_id 取 task.brand_id。"""
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO evaluation_runs
               (id, name, status, model_keys, question_ids, total_questions, config, mode, task_id, batch_id, brand_id)
               VALUES (?, ?, 'config_downloaded', ?, ?, ?, ?, 'webchat', ?, ?, ?)""",
            (run_id, name, json.dumps(model_keys), json.dumps(question_ids),
             sum(len(v) for v in per_model.values()), json.dumps(config or {}), task_id, batch_id, brand_id)
        )
        await db.commit()
        return await get_run(run_id)
    finally:
        await db.close()


async def list_task_batches(task_id: str) -> List[Dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluation_runs WHERE task_id=? ORDER BY started_at DESC, id DESC",
            (task_id,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["model_keys"] = json.loads(r["model_keys"]) if isinstance(r["model_keys"], str) else r["model_keys"]
            r["question_ids"] = json.loads(r["question_ids"]) if isinstance(r["question_ids"], str) else r["question_ids"]
            r["config"] = json.loads(r["config"]) if isinstance(r.get("config"), str) else (r.get("config") or {})
        return rows
    finally:
        await db.close()


async def set_batch_status(run_id: str, status: str, completed: Optional[int] = None):
    await update_run_status(run_id, status, completed)


async def get_run_by_batch_id(batch_id: str) -> Optional[Dict]:
    """按 batch_id 反查 evaluation_runs（Win 守护进程回报状态用）。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM evaluation_runs WHERE batch_id=?", (batch_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# 批次状态机中「未完成」的状态：守护进程启动时拉这些批次补跑/续跑。
PENDING_BATCH_STATUSES = ("config_downloaded", "pushed", "awaiting_human")


async def list_pending_batches() -> List[Dict]:
    """列出所有未完成批次（供守护进程 GET /api/batches/pending）。"""
    db = await get_db()
    try:
        placeholders = ",".join("?" * len(PENDING_BATCH_STATUSES))
        cursor = await db.execute(
            f"SELECT id, task_id, batch_id, status, name, mode "
            f"FROM evaluation_runs WHERE status IN ({placeholders}) "
            f"ORDER BY COALESCE(started_at, id) ASC",
            PENDING_BATCH_STATUSES,
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def save_task_analysis_result(task_id: str, batch_id: str, run_id: str, result: Dict):
    """按 (task_id, model_key, question_id) 去重覆盖插入。"""
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM analysis_results WHERE task_id=? AND model_key=? AND question_id=?",
            (task_id, result["model_key"], result["question_id"])
        )
        await db.execute(
            """INSERT INTO analysis_results
               (run_id, task_id, batch_id, question_id, model_key, model_name,
                ucloud_mentioned, ucloud_mention_count, ucloud_rank,
                has_citation, citation_count, ucloud_recommended, recommendation_strength,
                sentiment_score, sentiment_label, position_weight, response_length,
                raw_content, competitor_mentions, error_message, citations, all_cited_urls, brand_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, task_id, batch_id, result["question_id"], result["model_key"], result["model_name"],
             int(result["ucloud_mentioned"]), result["ucloud_mention_count"], result.get("ucloud_rank"),
             int(result["has_citation"]), result["citation_count"],
             int(result["ucloud_recommended"]), result["recommendation_strength"],
             result["sentiment_score"], result["sentiment_label"], result["position_weight"],
             result["response_length"], result.get("raw_content", ""),
             json.dumps(result.get("competitor_mentions", {}), ensure_ascii=False),
             result.get("error_message"),
             json.dumps(result.get("citations", []), ensure_ascii=False),
             json.dumps(result.get("all_cited_urls", []), ensure_ascii=False), brand_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_task_results(task_id: str, model_key: Optional[str] = None) -> List[Dict]:
    db = await get_db()
    try:
        query = "SELECT * FROM analysis_results WHERE task_id=?"
        params = [task_id]
        if model_key:
            query += " AND model_key=?"
            params.append(model_key)
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def count_task_results_by_batch(task_id: str) -> Dict[str, int]:
    """返回 {batch_id: 结果条数}，仅统计有 batch_id 的行。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT batch_id, COUNT(*) AS cnt FROM analysis_results "
            "WHERE task_id=? AND batch_id IS NOT NULL GROUP BY batch_id",
            (task_id,)
        )
        rows = await cursor.fetchall()
        return {r["batch_id"]: r["cnt"] for r in rows}
    finally:
        await db.close()


async def get_batch_results(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的全部分析结果（LEFT JOIN questions 带题目原文），按 model_key、question_id 排序。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT a.*, q.question AS question_text, q.category AS question_category "
            "FROM analysis_results a "
            "LEFT JOIN questions q ON a.question_id = q.id "
            "WHERE a.task_id=? AND a.batch_id=? "
            "ORDER BY a.model_key, a.question_id",
            (task_id, batch_id)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def add_batch_import_log(task_id: str, batch_id: str, run_id: Optional[str],
                               results_inserted: int, file_name: Optional[str] = None,
                               file_size: Optional[int] = None) -> int:
    """记一条批次导入审计日志，返回新行 id。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO batch_import_logs "
            "(task_id, batch_id, run_id, results_inserted, file_name, file_size) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, batch_id, run_id, results_inserted, file_name, file_size)
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_batch_import_logs(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的全部导入日志，按时间倒序。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM batch_import_logs "
            "WHERE task_id=? AND batch_id=? ORDER BY imported_at DESC, id DESC",
            (task_id, batch_id)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_last_import_times(task_id: str) -> Dict[str, str]:
    """返回 {batch_id: 最后导入时间}，用于批次行展示。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT batch_id, MAX(imported_at) AS last_at "
            "FROM batch_import_logs WHERE task_id=? GROUP BY batch_id",
            (task_id,)
        )
        rows = await cursor.fetchall()
        return {r["batch_id"]: r["last_at"] for r in rows if r["batch_id"]}
    finally:
        await db.close()


async def get_task_scores(task_id: str, category: Optional[str] = None) -> List[Dict]:
    db = await get_db()
    try:
        query = "SELECT * FROM geo_scores WHERE task_id=?"
        params = [task_id]
        if category:
            query += " AND category=?"
            params.append(category)
        else:
            query += " AND category IS NULL"
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def delete_task_geo_scores(task_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM geo_scores WHERE task_id=?", (task_id,))
        await db.commit()
    finally:
        await db.close()


async def save_task_geo_scores(task_id: str, model_key: str, model_name: str,
                               category: Optional[str], scores: Dict):
    task = await get_task(task_id)
    brand_id = (task or {}).get("brand_id") or "ucloud"
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO geo_scores
               (task_id, run_id, model_key, model_name, category,
                geo_score, coverage_rate, mention_rate, citation_rate,
                recommendation_rate, sentiment_score, avg_rank,
                total_questions, valid_responses, brand_id)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, model_key, model_name, category,
             scores["geo_score"], scores["coverage_rate"], scores["mention_rate"],
             scores["citation_rate"], scores["recommendation_rate"],
             scores["sentiment_score"], scores["avg_rank"],
             scores["total_questions"], scores["valid_responses"], brand_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_task_coverage(task_id: str) -> Dict:
    """返回 {model_key: {question_id: 'done'|'failed'|'missing'}}。
    done=有非空内容行；failed=有 error_message 行；missing=固定题集里没有的。"""
    task = await get_task(task_id)
    if not task:
        return {}
    all_qids = task["question_ids"]
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT model_key, question_id, raw_content, error_message FROM analysis_results WHERE task_id=?",
            (task_id,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    models = sorted({r["model_key"] for r in rows} | set())
    coverage: Dict[str, Dict[str, str]] = {mk: {} for mk in models}
    for r in rows:
        mk, qid = r["model_key"], r["question_id"]
        if r.get("error_message"):
            coverage.setdefault(mk, {})[qid] = "failed"
        elif r.get("raw_content"):
            coverage.setdefault(mk, {})[qid] = "done"
        else:
            coverage.setdefault(mk, {})[qid] = "failed"
    # 标 missing
    for mk in list(coverage.keys()):
        for qid in all_qids:
            coverage[mk].setdefault(qid, "missing")
    return coverage

