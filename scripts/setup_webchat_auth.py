"""
WebChat 登录认证设置脚本
在本机 Windows 上运行，打开可见浏览器窗口让用户手动登录各 AI 模型官网，
登录完成后保存认证状态（Playwright storageState JSON 文件）

使用方式:
    python scripts/setup_webchat_auth.py kimi     # 只设置 Kimi
    python scripts/setup_webchat_auth.py all       # 设置所有支持的模型
"""
import asyncio
import sys
import os
import json

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_auth import WEBCHAT_SITES, save_auth_state, ensure_auth_dir, AUTH_DIR, load_auth_state

SUPPORTED_MODELS = ["kimi", "deepseek", "ernie", "doubao", "qwen"]


async def setup_auth(model_key: str):
    """打开浏览器让用户手动登录，然后保存认证状态"""
    from playwright.async_api import async_playwright

    site = WEBCHAT_SITES.get(model_key)
    if not site:
        print(f"❌ 未知模型: {model_key}")
        return False

    # 检查是否已有认证状态（用于增量更新）
    existing_state = load_auth_state(model_key)

    print(f"\n{'='*50}")
    print(f"  设置 {site['name']} ({site['url']}) 的登录认证")
    if existing_state:
        cookie_count = len(existing_state.get("cookies", []))
        print(f"  ℹ️ 已有 {cookie_count} 个 cookie，将在此基础上更新")
    print(f"{'='*50}")
    print(f"  即将打开浏览器窗口，请手动登录 {site['name']}")
    print(f"  登录完成后，回到此终端按 Enter 键保存登录状态")
    print(f"{'='*50}\n")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)  # 可见模式

    # 如果已有认证状态，加载它以便在登录状态下打开页面
    if existing_state:
        context = await browser.new_context(
            storage_state=existing_state,
            viewport={"width": 1280, "height": 800},
        )
        print(f"  ✅ 已加载现有认证状态，浏览器将以已登录状态打开")
    else:
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        print(f"  ⚠️ 无现有认证状态，请先手动登录")

    page = await context.new_page()

    # 导航到网站
    await page.goto(site["url"], wait_until="domcontentloaded")
    print(f"  ✅ 浏览器已打开 {site['url']}")
    print(f"  请确认登录状态是否有效（如已登录可直接按 Enter；如未登录请先登录）")

    # 等待用户输入
    input("\n  确认登录有效后，请按 Enter 键保存状态...")

    # 保存认证状态
    ensure_auth_dir()
    state = await context.storage_state()
    path = save_auth_state(model_key, state)

    cookie_count = len(state.get("cookies", []))
    origin_count = len(state.get("origins", []))
    print(f"\n  ✅ 认证状态已保存!")
    print(f"  文件: {path}")
    print(f"  Cookie 数: {cookie_count}")
    print(f"  LocalStorage 项: {origin_count}")
    print(f"\n  下一步: 将此文件上传到服务器的「系统设置 → WebChat 登录状态」页面")
    print(f"  文件路径: {path}")

    await browser.close()
    await pw.stop()
    return True


async def setup_all():
    """设置所有支持的模型"""
    print("\n🌐 WebChat 登录认证批量设置")
    print(f"  当前支持的模型: {', '.join(SUPPORTED_MODELS)}")

    for model_key in SUPPORTED_MODELS:
        success = await setup_auth(model_key)
        if not success:
            continue

    print("\n✅ 全部设置完成!")
    print(f"  认证文件保存在: {AUTH_DIR}")
    print(f"  请将这些文件上传到服务器")


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/setup_webchat_auth.py <model_key>")
        print(f"  可选模型: {', '.join(SUPPORTED_MODELS)}, all")
        print("\n示例:")
        print("  python scripts/setup_webchat_auth.py kimi    # 设置 Kimi")
        print("  python scripts/setup_webchat_auth.py all      # 设置所有支持的模型")
        sys.exit(1)

    model_key = sys.argv[1].lower()

    if model_key == "all":
        asyncio.run(setup_all())
    else:
        asyncio.run(setup_auth(model_key))


if __name__ == "__main__":
    main()