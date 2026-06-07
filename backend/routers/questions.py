"""问题管理路由"""
from fastapi import APIRouter, HTTPException
import json
import database as db
import models

QUESTION_TYPES = ["品牌词", "品类词", "对比词", "场景词"]

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("")
async def list_questions(category: str = None, question_type: str = None,
                         active_only: bool = True):
    """列出问题"""
    questions = await db.get_questions(category, question_type, active_only)
    for q in questions:
        try:
            q["tags"] = json.loads(q["tags"]) if isinstance(q["tags"], str) else q["tags"]
        except Exception:
            q["tags"] = []
    return {"success": True, "data": questions}


@router.get("/categories")
async def list_categories():
    """列出所有品类"""
    questions = await db.get_questions(active_only=True)
    cats = list(dict.fromkeys(q["category"] for q in questions))
    counts = {c: sum(1 for q in questions if q["category"] == c) for c in cats}
    return {"success": True, "data": [{"name": c, "count": counts[c]} for c in cats]}


@router.get("/types")
async def list_types():
    """列出所有问题类型"""
    return {"success": True, "data": QUESTION_TYPES}


@router.post("")
async def create_question(q: models.QuestionCreate):
    """新增问题"""
    await db.upsert_question(q.dict())
    return {"success": True}


@router.put("/{question_id}")
async def update_question(question_id: str, q: models.QuestionUpdate):
    """更新问题"""
    existing = await db.get_questions()
    found = [x for x in existing if x["id"] == question_id]
    if not found:
        raise HTTPException(404, "问题不存在")
    update_data = q.dict(exclude_none=True)
    current = found[0]
    try:
        current["tags"] = json.loads(current["tags"]) if isinstance(current["tags"], str) else current["tags"]
    except Exception:
        current["tags"] = []
    merged = {**current, **update_data}
    await db.upsert_question(merged)
    return {"success": True}


@router.delete("/{question_id}")
async def delete_question(question_id: str):
    """删除问题"""
    await db.delete_question(question_id)
    return {"success": True}


@router.post("/import")
async def import_questions(req: models.QuestionImport):
    """批量导入"""
    for q in req.questions:
        await db.upsert_question(q.dict())
    return {"success": True, "data": {"imported": len(req.questions)}}
