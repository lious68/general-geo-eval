"""
WebChat 交互式反爬验证辅助脚本

当豆包等网站弹出反爬验证（滑块、点选等）时，服务器上的 Playwright 无法自动通过。
此脚本通过 SSH + VNC 隧道将服务器的虚拟浏览器画面转发到本地，让你手动操作验证。

使用方式:
    python scripts/webchat_interactive_helper.py doubao     # 启动 VNC 隧道，连接到豆包浏览器
    python scripts/webchat_interactive_helper.py all         # 所有模型

流程:
    1. 在服务器上用 xvfb 启动一个带登录态的 Playwright 浏览器
    2. 在服务器上用 x11vnc 把虚拟显示器转发到 VNC 端口
    3. 建立 SSH 隧道将 VNC 端口映射到本地 5900
    4. 你用 VNC 客户端连接 localhost:5900 看到浏览器画面
    5. 手动通过反爬验证
    6. 验证通过后脚本自动保存最新的认证状态并退出
"""
import asyncio
import sys
import os
import json
import subprocess
import time
import signal

# 项目路径
PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..")
CORE_DIR = os.path.join(PROJECT_DIR, "core")
sys.path.insert(0, CORE_DIR)

from web_chat_auth import WEBCHAT_SITES, save_auth_state, load_auth_state, ensure_auth_dir, AUTH_DIR

SUPPORTED_MODELS = ["kimi", "deepseek", "ernie", "doubao", "qwen"]

# 服务器配置
SERVER = "113.31.106.119"
SSH_KEY = os.path.expanduser("~/.ssh/id_rsa/las20260523.pem")
SSH_USER = "root"
VNC_PORT = 5900  # 本地 VNC 端口
REMOTE_VNC_PORT = 5900  # 服务器 VNC 端口


async def interactive_auth(model_key: str):
    """交互式处理反爬验证：通过 VNC 让用户手动操作服务器浏览器"""
    from playwright.async_api import async_playwright

    site = WEBCHAT_SITES.get(model_key)
    if not site:
        print(f"❌ 未知模型: {model_key}")
        return False

    existing_state = load_auth_state(model_key)
    cookie_count = len(existing_state.get("cookies", [])) if existing_state else 0

    print(f"\n{'='*60}")
    print(f"  🌐 交互式 WebChat 验证: {site['name']} ({site['url']})")
    print(f"{'='*60}")
    if existing_state:
        print(f"  已有 {cookie_count} 个 cookie，将在登录态基础上打开")
    print()

    # Step 1: 启动 SSH 隧道 + x11vnc
    print("  📡 Step 1: 建立 SSH + VNC 隧道...")
    print(f"  SSH: {SSH_USER}@{SERVER}")
    print(f"  VNC: localhost:{VNC_PORT} → server:{REMOTE_VNC_PORT}")

    # 先杀掉可能残留的 x11vnc
    subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         f"{SSH_USER}@{SERVER}",
         "pkill -9 x11vnc; true"],
        capture_output=True, timeout=10
    )

    # 获取 xvfb 的 DISPLAY 号（从 systemd 服务或 ps 获取）
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         f"{SSH_USER}@{SERVER}",
         "ps aux | grep Xvfb | grep -v grep | awk '{print $NF}' | head -1"],
        capture_output=True, text=True, timeout=10
    )
    display_num = result.stdout.strip().replace(":99", "99").replace(":", "")
    if not display_num:
        display_num = "99"
    display = f":{display_num}"
    print(f"  服务器虚拟显示器: {display}")

    # 在服务器上启动 x11vnc
    subprocess.Popen(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         f"{SSH_USER}@{SERVER}",
         f"x11vnc -display {display} -forever -shared -rfbport {REMOTE_VNC_PORT} "
         f"-nopw -nocursorshape -nocursorpos -nowf -noxdamage -threads"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    # 建立 SSH 隧道（本地 5900 → 远程 5900）
    ssh_tunnel = subprocess.Popen(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-N", "-L",
         f"{VNC_PORT}:localhost:{REMOTE_VNC_PORT}",
         f"{SSH_USER}@{SERVER}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    print(f"  ✅ SSH + VNC 隧道已建立")
    print()

    # Step 2: 用 Playwright 打开浏览器到目标网站
    print("  🖥️  Step 2: 打开浏览器...")
    pw = await async_playwright().start()

    # headed 模式（会渲染到 xvfb 的虚拟显示器上，VNC 可看到）
    browser = await pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    if existing_state:
        context = await browser.new_context(
            storage_state=existing_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
    else:
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

    # 注入反检测脚本
    stealth_js = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
    """
    await context.add_init_script(stealth_js)

    page = await context.new_page()
    await page.goto(site["url"], wait_until="domcontentloaded")

    print(f"  ✅ 浏览器已打开 {site['url']}")
    print()
    print(f"  {'='*60}")
    print(f"  ⚡ VNC 连接信息:")
    print(f"     地址: localhost:{VNC_PORT}")
    print(f"     密码: 无密码")
    print(f"")
    print(f"  📋 操作步骤:")
    print(f"     1. 用 VNC 客户端连接 localhost:{VNC_PORT}")
    print(f"        - Windows: 下载 VNC Viewer (https://www.realvnc.com/en/connect/download/viewer/)")
    print(f"        - 或用 TightVNC、TigerVNC 等任何 VNC 客户端")
    print(f"     2. 在 VNC 中看到浏览器画面")
    print(f"     3. 如有反爬验证（滑块、点选等），手动完成验证")
    print(f"     4. 确认可以正常输入问题并得到回复")
    print(f"     5. 回到此终端按 Enter 保存认证状态")
    print(f"  {'='*60}")

    input("\n  ✅ 验证/登录完成后，按 Enter 保存状态并退出...")

    # Step 3: 保存认证状态
    ensure_auth_dir()
    state = await context.storage_state()
    path = save_auth_state(model_key, state)

    new_cookie_count = len(state.get("cookies", []))
    print(f"\n  ✅ 认证状态已保存!")
    print(f"  文件: {path}")
    print(f"  Cookie 数: {cookie_count} → {new_cookie_count}")

    # Step 4: 上传认证文件到服务器
    print(f"\n  📤 上传认证文件到服务器...")
    upload_result = subprocess.run(
        ["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         path,
         f"{SSH_USER}@{SERVER}:/opt/ucloud-geo-eval/data/webchat_auth/"],
        capture_output=True, text=True, timeout=15
    )
    if upload_result.returncode == 0:
        print(f"  ✅ 认证文件已上传到服务器")
    else:
        print(f"  ❌ 上传失败: {upload_result.stderr}")
        print(f"  请手动上传: scp {path} {SSH_USER}@{SERVER}:/opt/ucloud-geo-eval/data/webchat_auth/")

    # 清理
    await browser.close()
    await pw.stop()

    # 关闭 SSH 隧道和 x11vnc
    ssh_tunnel.kill()
    subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         f"{SSH_USER}@{SERVER}",
         "pkill -9 x11vnc; true"],
        capture_output=True, timeout=10
    )

    print(f"\n  🎉 完成! {site['name']} 认证状态已更新并上传到服务器")
    print(f"  可以重新执行 WebChat 评测了")
    return True


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/webchat_interactive_helper.py <model_key>")
        print(f"  可选模型: {', '.join(SUPPORTED_MODELS)}")
        print()
        print("此脚本通过 SSH + VNC 将服务器的浏览器画面转发到本地，")
        print("让你手动处理反爬验证（滑块、点选等）。")
        print()
        print("前置条件:")
        print("  1. 本机需安装 VNC 客户端 (如 VNC Viewer)")
        print("  2. 本机需有 SSH key 访问服务器")
        sys.exit(1)

    model_key = sys.argv[1].lower()
    if model_key not in SUPPORTED_MODELS:
        print(f"❌ 不支持的模型: {model_key}")
        print(f"  支持: {', '.join(SUPPORTED_MODELS)}")
        sys.exit(1)

    try:
        asyncio.run(interactive_auth(model_key))
    except KeyboardInterrupt:
        print("\n\n  ⚠️ 被中断，清理中...")
        # 尝试清理 SSH 隧道
        subprocess.run(["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
                        f"{SSH_USER}@{SERVER}", "pkill -9 x11vnc; true"],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"\n  ❌ 错误: {e}")


if __name__ == "__main__":
    main()