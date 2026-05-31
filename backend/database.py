"""
UCloud GEO Web - 数据库层
SQLite 异步数据库，管理评测、结果、问题、设置
"""
import os
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "geo.db")

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

        # 检查是否已有问题数据
        cursor = await db.execute("SELECT COUNT(*) FROM questions")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await _import_default_questions(db)
    finally:
        await db.close()


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
                response_length, raw_content, competitor_mentions, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, result["question_id"], result["model_key"], result["model_name"],
             int(result["ucloud_mentioned"]), result["ucloud_mention_count"], result.get("ucloud_rank"),
             int(result["has_citation"]), result["citation_count"],
             int(result["ucloud_recommended"]), result["recommendation_strength"],
             result["sentiment_score"], result["sentiment_label"], result["position_weight"],
             result["response_length"], result.get("raw_content", ""),
             json.dumps(result.get("competitor_mentions", {}), ensure_ascii=False),
             result.get("error_message"))
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
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
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
