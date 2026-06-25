"""Inspect web chat DOM structures for selector discovery"""
import asyncio
import json
from playwright.async_api import async_playwright


async def inspect_site(url, name):
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = await b.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        print(f"\n=== {name} ({url}) ===")
        print(f"Title: {await page.title()}")

        # Use page.locator + evaluate approach
        # Inputs
        input_count = await page.locator("textarea").count()
        ce_count = await page.locator("[contenteditable='true']").count()
        print(f"textarea count: {input_count}, contenteditable count: {ce_count}")

        # Check textarea attributes
        for i in range(min(input_count, 3)):
            ta = page.locator("textarea").nth(i)
            cls = await ta.get_attribute("class") or ""
            ph = await ta.get_attribute("placeholder") or ""
            dt = await ta.get_attribute("data-testid") or ""
            print(f"  textarea[{i}]: class={cls[:80]}, placeholder={ph[:40]}, data-testid={dt}")

        # Check contenteditable attributes
        for i in range(min(ce_count, 3)):
            ce = page.locator("[contenteditable='true']").nth(i)
            cls = await ce.get_attribute("class") or ""
            tag = await ce.evaluate("el => el.tagName")
            print(f"  contenteditable[{i}]: tag={tag}, class={cls[:80]}")

        # Buttons with text or aria-label
        btn_count = await page.locator("button").count()
        print(f"button count: {btn_count}")
        for i in range(min(btn_count, 15)):
            btn = page.locator("button").nth(i)
            txt = await btn.inner_text() if await btn.is_visible() else "(hidden)"
            cls = await btn.get_attribute("class") or ""
            dt = await btn.get_attribute("data-testid") or ""
            al = await btn.get_attribute("aria-label") or ""
            print(f"  btn[{i}]: class={cls[:60]}, text={txt[:30]}, data-testid={dt}, aria-label={al[:40]}")

        # Links
        link_count = await page.locator("a[href]").count()
        print(f"link count: {link_count}")
        for i in range(min(link_count, 10)):
            lnk = page.locator("a[href]").nth(i)
            href = await lnk.get_attribute("href") or ""
            txt = await lnk.inner_text() if await lnk.is_visible() else ""
            cls = await lnk.get_attribute("class") or ""
            print(f"  link[{i}]: class={cls[:60]}, href={href[:50]}, text={txt[:30]}")

        # data-testid elements
        dt_count = await page.locator("[data-testid]").count()
        print(f"data-testid count: {dt_count}")
        for i in range(min(dt_count, 15)):
            dt_el = page.locator("[data-testid]").nth(i)
            dt_val = await dt_el.get_attribute("data-testid") or ""
            cls = await dt_el.get_attribute("class") or ""
            tag = await dt_el.evaluate("el => el.tagName")
            print(f"  dt[{i}]: tag={tag}, data-testid={dt_val}, class={cls[:60]}")

        # Search-related elements
        search_count = await page.locator("[class*='search'], [class*='Search']").count()
        print(f"search class count: {search_count}")
        for i in range(min(search_count, 8)):
            se = page.locator("[class*='search'], [class*='Search']").nth(i)
            cls = await se.get_attribute("class") or ""
            tag = await se.evaluate("el => el.tagName")
            txt = await se.inner_text() if await se.is_visible() else ""
            print(f"  search[{i}]: tag={tag}, class={cls[:60]}, text={txt[:30]}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await b.close()
        await pw.stop()


async def main():
    sites = [
        ("https://chat.deepseek.com", "DeepSeek"),
        ("https://chat.baidu.com", "Ernie"),
        ("https://www.doubao.com/chat", "Doubao"),
        ("https://tongyi.aliyun.com/qwen", "Qwen"),
    ]
    for url, name in sites:
        try:
            await inspect_site(url, name)
        except Exception as e:
            print(f"Failed {name}: {e}")


asyncio.run(main())