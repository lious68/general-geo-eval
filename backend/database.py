"""
UCloud GEO Web - 数据库层
SQLite 异步数据库，管理评测、结果、问题、设置
"""
import os
import json
import re
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "geo.db")

UCLOUD_QUESTION_PATTERN = re.compile(r"u\s*cloud|优\s*刻\s*得|优刻得", re.IGNORECASE)
THIRD_PARTY_CITATION_DOMAINS = [
    "zhihu.com", "csdn.net", "juejin.cn", "github.com", "bilibili.com",
    "segmentfault.com", "oschina.net", "cnblogs.com", "infoq.cn", "51cto.com",
    "mp.weixin.qq.com",
]


def get_effective_citations(row: Dict[str, Any]) -> List[Dict[str, Any]]:
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

    effective = list(citations or [])
    if row.get("ucloud_mentioned"):
        seen = {
            (c.get("citation_type"), c.get("content"), c.get("position"))
            for c in effective if isinstance(c, dict)
        }
        for item in urls or []:
            if not isinstance(item, dict) or item.get("citation_type") != "url":
                continue
            url = (item.get("content") or "").lower()
            if not any(domain in url for domain in THIRD_PARTY_CITATION_DOMAINS):
                continue
            key = ("url", item.get("content"), item.get("position"))
            if key in seen:
                continue
            effective.append({**item, "is_ucloud": bool(item.get("is_ucloud", False))})
            seen.add(key)
    return effective


def has_effective_citation(row: Dict[str, Any]) -> bool:
    """按新口径判断是否有有效引用：官方引用，或提及UCloud时的第三方来源引用。"""
    return len(get_effective_citations(row)) > 0


def _natural_question_filter_sql(alias: str = "q") -> str:
    """排除题干自带 UCloud/优刻得 字眼的问题，仅统计自然问题。"""
    q = f"{alias}.question"
    return (
        f"(({q} IS NULL) OR ("
        f"LOWER(REPLACE({q}, ' ', '')) NOT LIKE '%ucloud%' "
        f"AND REPLACE({q}, ' ', '') NOT LIKE '%优刻得%'))"
    )


def is_natural_question_text(question: str) -> bool:
    """题干不自带 UCloud/优刻得 字眼时，视为自然问题。"""
    return not UCLOUD_QUESTION_PATTERN.search(question or "")

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
    config TEXT
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

CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
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


async def _migrate_add_columns(db: aiosqlite.Connection):
    """安全添加新列（兼容已有数据库）"""
    for col in ["citations", "all_cited_urls"]:
        try:
            await db.execute(f"ALTER TABLE analysis_results ADD COLUMN {col} TEXT DEFAULT '[]'")
            await db.commit()
        except aiosqlite.OperationalError:
            pass  # 列已存在


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
                     question_ids: List[str], config: Dict = None):
    """创建评测运行"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO evaluation_runs (id, name, status, model_keys, question_ids, total_questions, config)
               VALUES (?, ?, 'pending', ?, ?, ?, ?)""",
            (run_id, name, json.dumps(model_keys), json.dumps(question_ids),
             len(question_ids) * len(model_keys), json.dumps(config or {}))
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
            await db.execute(
                "UPDATE evaluation_runs SET status=?, completed_at=?, completed_questions=COALESCE(?,completed_questions) WHERE id=?",
                (status, datetime.now().isoformat(), completed, run_id)
            )
        elif status == "failed":
            await db.execute(
                "UPDATE evaluation_runs SET status=? WHERE id=?",
                (status, run_id)
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
            "SELECT * FROM evaluation_runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
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

        # recommendation_rate 当前用于仪表盘的“TOP3 推荐率”：
        # UCloud 进入品牌推荐列表 Top3 的有效回答数 / 有效回答总数。
        # 基于 analysis_results 动态回填，历史评测无需重跑也能按新口径展示。
        for row in rows:
            metrics_query = f"""
                SELECT
                    ar.*,
                    q.question
                FROM analysis_results ar
                JOIN questions q ON q.id = ar.question_id
                WHERE ar.run_id=?
                  AND ar.model_key=?
                  AND (ar.error_message IS NULL OR ar.error_message='')
                  AND {_natural_question_filter_sql('q')}
            """
            metrics_params = [run_id, row["model_key"]]
            if row.get("category"):
                metrics_query += " AND q.category=?"
                metrics_params.append(row["category"])

            metrics_cursor = await db.execute(metrics_query, metrics_params)
            metric_rows = [dict(r) for r in await metrics_cursor.fetchall()]
            valid_count = len(metric_rows)
            if valid_count:
                mentioned_count = sum(1 for r in metric_rows if r.get("ucloud_mentioned"))
                citation_count = sum(1 for r in metric_rows if has_effective_citation(r))
                top3_count = sum(1 for r in metric_rows if r.get("ucloud_rank") is not None and r.get("ucloud_rank") <= 3)
                sentiment_values = [r.get("sentiment_score") or 0 for r in metric_rows if r.get("ucloud_mentioned")]
                rank_values = [r.get("ucloud_rank") for r in metric_rows if r.get("ucloud_rank") is not None]
                row["valid_responses"] = valid_count
                row["coverage_rate"] = round(mentioned_count / valid_count, 4)
                row["citation_rate"] = round(citation_count / valid_count, 4)
                row["recommendation_rate"] = round(top3_count / valid_count, 4)
                row["sentiment_score"] = round(sum(sentiment_values) / len(sentiment_values), 4) if sentiment_values else 0
                row["avg_rank"] = round(sum(rank_values) / len(rank_values), 2) if rank_values else 0
            else:
                row["valid_responses"] = 0
                row["coverage_rate"] = 0
                row["citation_rate"] = 0
                row["recommendation_rate"] = 0
                row["sentiment_score"] = 0
                row["avg_rank"] = 0

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
                       active_only: bool = True) -> List[Dict]:
    """获取问题列表"""
    db = await get_db()
    try:
        query = "SELECT * FROM questions WHERE 1=1"
        params = []
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
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def upsert_question(q: Dict):
    """新增或更新问题"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO questions (id, category, question_type, question, tags, difficulty, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
               category=excluded.category, question_type=excluded.question_type,
               question=excluded.question, tags=excluded.tags, difficulty=excluded.difficulty""",
            (q["id"], q["category"], q["question_type"], q["question"],
             json.dumps(q.get("tags", []), ensure_ascii=False), q.get("difficulty", "medium"))
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

async def create_session(token: str, hours: int = 24):
    """创建登录会话"""
    from datetime import timedelta
    db = await get_db()
    try:
        expires = (datetime.now() + timedelta(hours=hours)).isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO admin_sessions (token, created_at, expires_at) VALUES (?, datetime('now'), ?)",
            (token, expires)
        )
        await db.commit()
    finally:
        await db.close()


async def verify_session(token: str) -> bool:
    """验证会话token"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT expires_at FROM admin_sessions WHERE token=?",
            (token,)
        )
        row = await cursor.fetchone()
        if not row:
            return False
        from datetime import datetime
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > expires:
            await db.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
            await db.commit()
            return False
        return True
    except Exception:
        return False
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


async def backfill_citations(run_id: str) -> int:
    """从 raw_content 重新提取引用详情并回填 citations/all_cited_urls 列

    返回回填的记录数
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    from analyzer import ResponseAnalyzer, AnalysisResult

    db = await get_db()
    analyzer = ResponseAnalyzer()
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

            # 重新运行引用检测
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

            await db.execute(
                "UPDATE analysis_results SET citations=?, all_cited_urls=? WHERE id=?",
                (citations_json, all_urls_json, row["id"])
            )
            count += 1

        await db.commit()
    finally:
        await db.close()

    return count
