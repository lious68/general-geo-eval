"""Test all 5 models with latest versions - basic + search"""
import sys
import asyncio
sys.path.insert(0, "/opt/ucloud-geo-eval/backend")
sys.path.insert(0, "/opt/ucloud-geo-eval/core")
import database as db
from services.eval_runner import _create_model_client

SEP = "=" * 72

async def test():
    models = ["qwen", "kimi", "doubao", "deepseek", "ernie"]

    print(SEP)
    print("  Testing latest models - basic + web search")
    print(SEP)

    for mk in models:
        client = await _create_model_client(mk)
        print("")
        print("-" * 72)
        print("  {:<12} base_url: {}".format(client.name, client.config["base_url"]))
        print("  {:<12} model:    {}".format("", client.config["model"]))
        print("-" * 72)

        if not client.is_configured:
            print("  >> NOT CONFIGURED")
            continue

        # --- Basic chat ---
        try:
            resp = client.chat("请用一句话介绍UCloud优刻得")
            if resp.get("error"):
                print("  [BASIC] ERROR: {}".format(resp["error"][:120]))
            else:
                content = resp.get("content", "")
                print("  [BASIC] OK ({} chars)".format(len(content)))
                if len(content) > 160:
                    print("    {}...".format(content[:160]))
                else:
                    print("    {}".format(content))
        except Exception as e:
            print("  [BASIC] EXCEPTION: {}".format(str(e)[:150]))

        # --- Search ---
        if client._search_config:
            method = client._search_config.get("method", "")
            print("  [SEARCH] method: {}".format(method))
            try:
                resp = client.chat("UCloud 2026年最新动态", enable_search=True)
                if resp.get("error"):
                    print("  [SEARCH] ERROR: {}".format(resp["error"][:120]))
                else:
                    content = resp.get("content", "")
                    print("  [SEARCH] OK ({} chars)".format(len(content)))
                    # Check if it actually has search-like content
                    has_search = False
                    if "http" in content.lower():
                        has_search = True
                    if "截至2024" in content or "截至2025" in content or "无法获取" in content:
                        has_search = False
                    if "最新动态" in content and "截至" not in content:
                        has_search = True

                    if has_search:
                        print("  [SEARCH] ==> SEARCH SUCCESSFUL")
                    else:
                        print("  [SEARCH] ==> NO REAL SEARCH (fallback)")
                    if len(content) > 200:
                        print("    {}...".format(content[:200]))
                    else:
                        print("    {}".format(content))
            except Exception as e:
                print("  [SEARCH] EXCEPTION: {}".format(str(e)[:150]))
        else:
            print("  [SEARCH] not supported")

    print("")
    print(SEP)
    print("Done.")

asyncio.run(test())
