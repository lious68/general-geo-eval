"""
WebChat 本地评测一键启动器

用法（任选其一）:

  # 方式1：从服务器下载任务配置后运行
  python scripts/webchat_run.py --server https://your-server.com --token xxx

  # 方式2：直接运行（使用本地已有配置或手动指定）
  python scripts/webchat_run.py --config task_config.json
  python scripts/webchat_run.py --models kimi ernie --headed

  # 方式3：交互式（引导式选择）
  python scripts/webchat_run.py

说明:
  - 默认以 headed 模式运行，弹出浏览器窗口
  - 人可手动处理验证码、登录等交互
  - 评测完成后自动保存结果文件
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 添加路径
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

# 导入 local_webchat_runner 的核心逻辑
from local_webchat_runner import run_local_eval, _setup_headed_mode, SEP


def download_config(server_url: str, token: str, output_file: str = "task_config.json"):
    """从服务器下载 WebChat 任务配置"""
    import urllib.request

    url = server_url.rstrip("/") + "/api/evaluations/export-webchat-config"

    # 这里需要构造一个 EvaluationCreate 风格的请求体
    # 简单起见，我们提供一个默认配置
    print("  ⚠️  服务器下载模式需要先在服务器上创建 WebChat 评测任务")
    print("     请到前端 '执行评测' 页面，选择 WebChat 模式后点击「下载任务配置」")
    print()
    print("  临时方案：手动创建 task_config.json，格式如下：")
    print(json.dumps({
        "version": 1,
        "task": {
            "name": "GEO评估",
            "model_keys": ["kimi"],
            "delay": 8,
        },
        "question_ids": None,
        "categories": [],
    }, indent=2, ensure_ascii=False))
    sys.exit(1)


def interactive_setup():
    """交互式配置引导"""
    print()
    print("  🌐 WebChat 本地评测 — 交互式配置")
    print(SEP)
    print()

    # 选择模型
    print("  选择要评测的模型（输入编号，多个用逗号分隔）:")
    print("    1. kimi     (Kimi)")
    print("    2. deepseek (DeepSeek)")
    print("    3. ernie    (文心一言)")
    print("    4. doubao   (豆包)")
    print("    5. qwen     (千问)")
    print()

    model_map = {
        "1": "kimi", "2": "deepseek", "3": "ernie",
        "4": "doubao", "5": "qwen",
    }

    choice = input("  选择 [默认 1]: ").strip() or "1"
    model_keys = []
    for c in choice.split(","):
        c = c.strip()
        if c in model_map:
            model_keys.append(model_map[c])
    if not model_keys:
        model_keys = ["kimi"]

    print(f"  已选: {', '.join(model_keys)}")
    print()

    # 品类
    categories_input = input("  品类筛选（逗号分隔，直接回车=全部）: ").strip()
    categories = [c.strip() for c in categories_input.split(",") if c.strip()] if categories_input else None

    # 延迟
    delay_input = input("  每题延迟秒数 [默认 8]: ").strip()
    delay = float(delay_input) if delay_input else 8.0

    # 输出文件
    output = input("  输出文件路径 [默认 output/webchat_评测_YYYYMMDD_HHMMSS.json]: ").strip()
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"output/webchat_评测_{timestamp}.json"

    # 浏览器模式
    headed_input = input("  显示浏览器窗口？(y/n) [默认 y，方便处理验证码]: ").strip().lower()
    headed = headed_input != "n"

    print()
    print(f"  配置确认:")
    print(f"    模型: {', '.join(model_keys)}")
    print(f"    品类: {categories or '全部'}")
    print(f"    延迟: {delay}s")
    print(f"    输出: {output}")
    print(f"    浏览器: {'显示窗口' if headed else '后台运行'}")
    confirm = input("  确认执行？(y/n) [默认 y]: ").strip().lower()

    if confirm == "n":
        print("  已取消。")
        sys.exit(0)

    return {
        "model_keys": model_keys,
        "question_ids": None,
        "categories": categories,
        "delay": delay,
        "output": output,
        "headed": headed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="WebChat 本地评测一键启动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互式引导（推荐新手）
  python scripts/webchat_run.py

  # 从服务器任务配置运行
  python scripts/webchat_run.py --config task_config.json

  # 手动指定模型
  python scripts/webchat_run.py --models kimi ernie --headed

  # 指定品类和输出文件
  python scripts/webchat_run.py --models kimi --categories 云数据库 --delay 10
        """,
    )
    parser.add_argument("--config", help="任务配置文件路径")
    parser.add_argument("--models", nargs="+", help="模型列表")
    parser.add_argument("--categories", help="品类筛选（逗号分隔）")
    parser.add_argument("--delay", type=float, help="每题延迟秒数")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--headed", action="store_true", default=True,
                        help="显示浏览器窗口（默认开启，方便处理验证码）")
    parser.add_argument("--headless", action="store_true",
                        help="后台运行（不显示浏览器）")
    parser.add_argument("--server", help="服务器地址（用于下载任务配置）")
    parser.add_argument("--token", help="服务器认证 Token")
    parser.add_argument("--interactive", action="store_true",
                        help="交互式配置引导")

    args = parser.parse_args()

    # 如果没有任何参数，进入交互模式
    is_interactive = (
        args.interactive
        or (not args.config and not args.models and not args.server)
    )

    if is_interactive:
        config = interactive_setup()
    elif args.server:
        # 服务器下载模式
        config_file = args.config or "task_config.json"
        download_config(args.server, args.token or "", config_file)
        # download_config 会 exit，不会到这里
        return
    elif args.config:
        # 从配置文件加载
        print(f"  📥 从配置文件加载: {args.config}")
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        config = {
            "model_keys": cfg["task"]["model_keys"],
            "question_ids": cfg.get("question_ids"),
            "categories": cfg.get("categories"),
            "delay": cfg["task"].get("delay", 8.0),
            "output": args.output,
            "headed": args.headed,
        }
        if args.headless:
            config["headed"] = False
        if args.delay is not None:
            config["delay"] = args.delay
    else:
        # 手动参数模式
        categories = None
        if args.categories:
            categories = [c.strip() for c in args.categories.split(",")]
        config = {
            "model_keys": args.models or ["kimi"],
            "question_ids": None,
            "categories": categories,
            "delay": args.delay if args.delay is not None else 8.0,
            "output": args.output,
            "headed": args.headed and not args.headless,
        }

    # 设置浏览器模式
    _setup_headed_mode(config["headed"])

    # 默认输出文件名
    if not config["output"]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config["output"] = f"output/webchat_评测_{timestamp}.json"

    # 运行评测
    asyncio.run(run_local_eval(
        model_keys=config["model_keys"],
        question_ids=config["question_ids"],
        categories=config["categories"],
        delay=config["delay"],
        output_path=config["output"],
    ))


if __name__ == "__main__":
    main()
