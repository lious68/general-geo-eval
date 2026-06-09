"""本地 Agent WebSocket 路由

本地 Agent 通过 WebSocket 长连接到服务器，等待 WebChat 评测任务派发。
"""
import json
import logging
import os
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from database import verify_session, save_analysis_result, update_run_status, save_geo_scores, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# 引用 evaluations 的 ws_manager 用于广播进度给前端
_ws_manager = None


def set_ws_manager(manager):
    """由 app.py 调用，注入 evaluations 的 ws_manager"""
    global _ws_manager
    _ws_manager = manager


class AgentConnection:
    """已连接的本地 Agent"""
    def __init__(self, agent_id: str, ws: WebSocket):
        self.agent_id = agent_id
        self.ws = ws
        self.busy: bool = False
        self.current_run_id: Optional[str] = None


# 全局 Agent 注册表
_connected_agents: Dict[str, AgentConnection] = {}


def get_connected_agent() -> Optional[AgentConnection]:
    """获取一个空闲的已连接 Agent"""
    for agent in _connected_agents.values():
        if not agent.busy:
            return agent
    return None


async def send_task_to_agent(agent: AgentConnection, task_data: dict):
    """向 Agent 发送任务"""
    await agent.ws.send_json(task_data)
    agent.busy = True
    agent.current_run_id = task_data.get("run_id")


@router.get("/status")
async def agent_status():
    """前端查询 Agent 连接状态"""
    agents = []
    for aid, conn in _connected_agents.items():
        agents.append({
            "agent_id": aid,
            "busy": conn.busy,
            "current_run_id": conn.current_run_id,
        })
    return {"success": True, "data": {"connected": len(agents) > 0, "agents": agents}}


@router.websocket("/ws")
async def agent_ws(ws: WebSocket, token: str = None):
    """Agent WebSocket 连接

    鉴权方式同 evaluations/ws：token 通过 query param 传递。
    """
    # 验证 token
    if not token or not await verify_session(token):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    agent_id = None
    logger.info("Agent WebSocket connected")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "register":
                agent_id = msg.get("agent_id", "unknown")
                conn = AgentConnection(agent_id, ws)
                _connected_agents[agent_id] = conn
                logger.info(f"Agent registered: {agent_id}")

            elif msg_type == "task.progress":
                run_id = msg.get("run_id")
                completed = msg.get("completed", 0)
                total = msg.get("total", 0)
                current_model = msg.get("current_model", "")
                current_question = msg.get("current_question", "")

                await update_run_status(run_id, "running", completed)
                if _ws_manager:
                    await _ws_manager.broadcast(run_id, {
                        "type": "progress",
                        "run_id": run_id,
                        "completed": completed,
                        "total": total,
                        "current_model": current_model,
                        "current_question": current_question,
                    })

            elif msg_type == "task.result":
                run_id = msg.get("run_id")
                result = msg.get("result", {})
                await save_analysis_result(run_id, result)

            elif msg_type == "task.completed":
                run_id = msg.get("run_id")
                model_key = msg.get("model_key", "")
                model_name = msg.get("model_name", model_key)
                completed = msg.get("completed", 0)

                # 计算并保存 GEO 评分
                await _calculate_scores_for_run(run_id, model_key, model_name)

                await update_run_status(run_id, "completed", completed)
                if _ws_manager:
                    await _ws_manager.broadcast(run_id, {
                        "type": "completed",
                        "run_id": run_id,
                    })

                # 释放 Agent
                for aid, conn in _connected_agents.items():
                    if conn.current_run_id == run_id:
                        conn.busy = False
                        conn.current_run_id = None
                        break

                logger.info(f"Agent task completed: run_id={run_id}")

            elif msg_type == "task.failed":
                run_id = msg.get("run_id")
                error = msg.get("error", "Unknown error")

                await update_run_status(run_id, "failed")
                if _ws_manager:
                    await _ws_manager.broadcast(run_id, {
                        "type": "failed",
                        "run_id": run_id,
                        "error": error,
                    })

                # 释放 Agent
                for aid, conn in _connected_agents.items():
                    if conn.current_run_id == run_id:
                        conn.busy = False
                        conn.current_run_id = None
                        break

                logger.warning(f"Agent task failed: run_id={run_id}, error={error}")

            elif msg_type == "pong":
                pass  # keepalive response

    except WebSocketDisconnect:
        logger.info(f"Agent WebSocket disconnected: {agent_id}")
    except Exception as e:
        logger.error(f"Agent WebSocket error: {e}")
    finally:
        # 清理注册
        if agent_id and agent_id in _connected_agents:
            conn = _connected_agents.pop(agent_id)
            # 如果 Agent 正在执行任务，标记为失败
            if conn.busy and conn.current_run_id:
                run_id = conn.current_run_id
                logger.warning(f"Agent disconnected during task: run_id={run_id}")
                await update_run_status(run_id, "failed")
                if _ws_manager:
                    await _ws_manager.broadcast(run_id, {
                        "type": "failed",
                        "run_id": run_id,
                        "error": "Local Agent 断开连接",
                    })


async def _calculate_scores_for_run(run_id: str, model_key: str, model_name: str):
    """从数据库读取已完成的结果，计算并保存 GEO 评分"""
    from services.eval_runner import calculate_and_save_geo_scores

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM analysis_results WHERE run_id=? AND model_key=?",
            (run_id, model_key)
        )
        rows = await cursor.fetchall()
        all_results = [dict(r) for r in rows]

        # 获取问题列表以做品类评分
        cursor2 = await db.execute("SELECT * FROM questions WHERE is_active=1")
        q_rows = await cursor2.fetchall()
        questions = [dict(r) for r in q_rows]
    finally:
        await db.close()

    if all_results:
        # 转换格式：DB 中的字段和 _analysis_to_dict 格式有差异，需要映射
        formatted = []
        for r in all_results:
            formatted.append({
                "question_id": r["question_id"],
                "model_key": r["model_key"],
                "model_name": r["model_name"],
                "ucloud_mentioned": bool(r.get("ucloud_mentioned", 0)),
                "ucloud_mention_count": r.get("ucloud_mention_count", 0),
                "ucloud_rank": r.get("ucloud_rank"),
                "has_citation": bool(r.get("has_citation", 0)),
                "citation_count": r.get("citation_count", 0),
                "ucloud_recommended": bool(r.get("ucloud_recommended", 0)),
                "recommendation_strength": r.get("recommendation_strength", "none"),
                "sentiment_score": r.get("sentiment_score", 0.5),
                "sentiment_label": r.get("sentiment_label", "neutral"),
                "position_weight": r.get("position_weight", 0.0),
                "response_length": r.get("response_length", 0),
                "raw_content": r.get("raw_content", ""),
            })
        await calculate_and_save_geo_scores(run_id, model_key, model_name, formatted, questions)
