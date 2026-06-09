"""
本地 WebChat Agent — 连接服务器，接收任务，本地跑浏览器评测

用法:
    python scripts/local_agent.py --server 113.31.106.119 --password <你的密码>
    python scripts/local_agent.py --server 113.31.106.119 --token <你的token>

说明:
    - 保持运行，等待线上控制台派发 WebChat 评测任务
    - 收到任务后自动打开浏览器执行评测（有界面，可观察）
    - 逐题回传结果到服务器，线上控制台实时显示进度
    - 断线自动重连
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time
import tempfile
import platform
import uuid

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Agent 唯一标识
AGENT_ID = f"{platform.node()}-{uuid.uuid4().hex[:6]}"

# 当前任务取消标志
_cancel_flag = False


def get_token(server: str, password: str) -> str:
    """通过密码登录获取 token"""
    import urllib.request
    data = json.dumps({"password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{server}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    token = result.get("data", {}).get("token", "")
    if not token:
        raise ValueError(f"登录失败: {result}")
    return token


async def handle_task(ws, task_msg: dict):
    """处理服务器派发的评测任务"""
    global _cancel_flag
    _cancel_flag = False

    run_id = task_msg["run_id"]
    model_keys = task_msg["model_keys"]
    questions = task_msg["questions"]
    delay = task_msg.get("delay", 10)
    auth_states = task_msg.get("auth_states", {})

    logger.info(f"收到任务: run_id={run_id}, models={model_keys}, questions={len(questions)}")

    from analyzer import ResponseAnalyzer
    from web_chat_clients import create_web_chat_client
    from playwright.async_api import async_playwright
    from web_chat_auth import WEBCHAT_SITES

    analyzer = ResponseAnalyzer()
    total = len(questions) * len(model_keys)
    completed = 0

    for mk in model_keys:
        if _cancel_flag:
            break

        auth_state = auth_states.get(mk)
        if not auth_state:
            logger.warning(f"模型 {mk} 无认证状态，跳过")
            for q in questions:
                result = _empty_result(q["id"], mk, "WebChat 未配置登录状态")
                await ws.send_json({"type": "task.result", "run_id": run_id, "result": result})
                completed += 1
            continue

        # 启动浏览器（有界面）
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            storage_state=auth_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # 创建 WebChat 客户端并注入浏览器
        client = create_web_chat_client(mk)
        client._playwright = pw
        client._browser = browser
        client._context = ctx
        client._page = await ctx.new_page()
        client.is_configured = True

        logger.info(f"浏览器已启动: {mk}")

        for q in questions:
            if _cancel_flag:
                break

            q_preview = q["question"][:40] + ("..." if len(q["question"]) > 40 else "")
            logger.info(f"[{completed+1}/{total}] {mk} → {q_preview}")

            try:
                resp = await client.chat(q["question"])
                content = resp.get("content", "")
                error = resp.get("error")

                analysis = analyzer.analyze(
                    question_id=q["id"],
                    model_key=mk,
                    model_name=client.name,
                    content=content,
                    error=error,
                )

                result = {
                    "question_id": q["id"],
                    "model_key": mk,
                    "model_name": client.name,
                    "ucloud_mentioned": analysis.ucloud_mentioned,
                    "ucloud_mention_count": analysis.ucloud_mention_count,
                    "ucloud_rank": analysis.ucloud_rank,
                    "has_citation": analysis.has_citation,
                    "citation_count": analysis.citation_count,
                    "ucloud_recommended": analysis.ucloud_recommended,
                    "recommendation_strength": analysis.ucloud_recommendation_strength,
                    "sentiment_score": analysis.sentiment_score,
                    "sentiment_label": analysis.sentiment_label,
                    "position_weight": analysis.position_weight,
                    "response_length": analysis.response_length,
                    "raw_content": analysis.raw_content,
                    "competitor_mentions": json.dumps({
                        k: [{"keyword": m.keyword, "position": m.position} for m in v]
                        for k, v in analysis.competitor_mentions.items()
                    }),
                    "error_message": analysis.error_message,
                    "citations": json.dumps([{
                        "citation_type": c.citation_type, "content": c.content,
                        "position": c.position, "source_channel": c.source_channel,
                        "is_ucloud": c.is_ucloud
                    } for c in analysis.citations]),
                    "all_cited_urls": json.dumps([{
                        "citation_type": c.citation_type, "content": c.content,
                        "position": c.position, "source_channel": c.source_channel,
                        "is_ucloud": c.is_ucloud
                    } for c in analysis.all_cited_urls]),
                }

                # 发送结果
                await ws.send_json({"type": "task.result", "run_id": run_id, "result": result})

            except Exception as e:
                logger.error(f"评测出错 {mk} {q['id']}: {e}")
                result = _empty_result(q["id"], mk, str(e))
                await ws.send_json({"type": "task.result", "run_id": run_id, "result": result})

            completed += 1

            # 发送进度
            await ws.send_json({
                "type": "task.progress",
                "run_id": run_id,
                "completed": completed,
                "total": total,
                "current_model": mk,
                "current_question": q["id"],
            })

            mention = "✓提及" if analysis.ucloud_mentioned else "✗未提及"
            logger.info(f"  → {mention} 长度={analysis.response_length}")

            # 延迟
            if delay > 0:
                logger.info(f"  等待 {delay}s...")
                await asyncio.sleep(delay)

        # 关闭浏览器
        await client.close()
        logger.info(f"浏览器已关闭: {mk}")

    # 发送完成
    if _cancel_flag:
        await ws.send_json({"type": "task.failed", "run_id": run_id, "error": "任务已取消", "completed": completed})
    else:
        await ws.send_json({"type": "task.completed", "run_id": run_id, "model_key": model_keys[0] if model_keys else "", "model_name": client.name if model_keys else "", "completed": completed})

    logger.info(f"任务完成: run_id={run_id}, completed={completed}")


def _empty_result(question_id: str, model_key: str, error: str) -> dict:
    return {
        "question_id": question_id,
        "model_key": model_key,
        "model_name": model_key,
        "ucloud_mentioned": False,
        "ucloud_mention_count": 0,
        "ucloud_rank": None,
        "has_citation": False,
        "citation_count": 0,
        "ucloud_recommended": False,
        "recommendation_strength": "none",
        "sentiment_score": 0.5,
        "sentiment_label": "neutral",
        "position_weight": 0.0,
        "response_length": 0,
        "raw_content": "",
        "competitor_mentions": "{}",
        "error_message": error,
        "citations": "[]",
        "all_cited_urls": "[]",
    }


async def run_agent(server: str, token: str):
    """主循环：连接服务器，等待任务"""
    import websockets

    # 使用 ws:// 或 wss://
    protocol = "wss" if server.startswith("https") or ":443" in server else "ws"
    host = server.replace("https://", "").replace("http://", "")
    url = f"{protocol}://{host}/api/agent/ws?token={token}"

    while True:
        try:
            logger.info(f"连接服务器 {host}...")
            async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                # 注册
                await ws.send(json.dumps({
                    "type": "register",
                    "agent_id": AGENT_ID,
                    "hostname": platform.node(),
                    "capabilities": ["webchat"],
                }))
                logger.info(f"已连接! Agent ID: {AGENT_ID}")
                logger.info("等待线上控制台派发任务...")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "task.assign":
                        await handle_task(ws, msg)
                        logger.info("等待下一个任务...")

                    elif msg_type == "task.cancel":
                        global _cancel_flag
                        _cancel_flag = True
                        logger.info(f"收到取消指令: run_id={msg.get('run_id')}")

                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong", "agent_id": AGENT_ID}))

        except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
            logger.warning(f"连接断开: {e}, 5 秒后重连...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"异常: {e}, 5 秒后重连...")
            await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="本地 WebChat Agent")
    parser.add_argument("--server", default="113.31.106.119", help="服务器地址 (默认 113.31.106.119)")
    parser.add_argument("--password", help="登录密码（自动获取 token）")
    parser.add_argument("--token", help="直接指定 token（优先于密码）")
    args = parser.parse_args()

    # 获取 token
    if args.token:
        token = args.token
    elif args.password:
        logger.info("登录获取 token...")
        token = get_token(args.server, args.password)
        logger.info("登录成功")
    else:
        parser.error("请指定 --password 或 --token")

    # 安装检查
    try:
        import websockets
    except ImportError:
        logger.info("安装 websockets 库...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "--quiet"])
        logger.info("安装完成")

    asyncio.run(run_agent(args.server, token))


if __name__ == "__main__":
    main()
