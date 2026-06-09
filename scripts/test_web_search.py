"""Test all models with and without web search via ModelVerse proxy"""
import sys
import asyncio
import os
from openai import OpenAI

TEST_QUESTION_NO_SEARCH = "请用一句话介绍UCloud优刻得"
TEST_QUESTION_SEARCH = "UCloud 2026年最新动态"

API_KEY = "6TDiy0eXKczEAlcDA100C6A2-9298-4670-aB17-7248231d"
BASE_URL = "https://api.modelverse.cn/v1"

MODELS = [
    {"key": "qwen",    "model": "Qwen/Qwen-Plus",              "name": "通义千问"},
    {"key": "kimi",    "model": "moonshotai/Kimi-K2-Instruct", "name": "Kimi"},
    {"key": "doubao",  "model": "ByteDance/doubao-1-5-pro-32k-250115", "name": "豆包"},
    {"key": "deepseek","model": "deepseek-ai/DeepSeek-V3.1",   "name": "DeepSeek"},
    {"key": "ernie",   "model": "baidu/ernie-4.5-turbo-128k",  "name": "文心一言"},
]


def chat(client, model_name, prompt, enable_search=False):
    """Send chat with optional search, model-specific search params"""
    kwargs = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.7,
        "timeout": 120,
    }

    if enable_search:
        if client.model_key == "qwen":
            kwargs["extra_body"] = {
                "enable_search": True,
                "search_options": {"forced_search": True},
            }
        elif client.model_key == "kimi":
            kwargs["tools"] = [{
                "type": "builtin_function",
                "function": {"name": "$web_search"},
            }]
        elif client.model_key == "doubao":
            kwargs["extra_body"] = {"enable_search": True}
        elif client.model_key == "deepseek":
            pass  # no built-in search
        elif client.model_key == "ernie":
            pass  # needs separate Qianfan API

    return client.client.chat.completions.create(**kwargs)


class TestClient:
    def __init__(self, key, model_name):
        self.model_key = key
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        self.model_name = model_name

    def chat(self, prompt, enable_search=False):
        return chat(self, self.model_name, prompt, enable_search)


def main():
    SEP = "=" * 60

    for m in MODELS:
        print("")
        print(SEP)
        print(" Testing: " + m["name"] + " (" + m["key"] + ")")
        print(SEP)
        print(f"  model: {m['model']}")

        client = TestClient(m["key"], m["model"])

        # Test without search
        try:
            resp = client.chat(TEST_QUESTION_NO_SEARCH)
            content = resp.choices[0].message.content
            print(f"  No search: OK ({len(content)} chars)")
            preview = content[:150] + ("..." if len(content) > 150 else "")
            print(f"    {preview}")
        except Exception as e:
            print(f"  No search: ERROR - {e}")

        # Test with search
        if m["key"] in ("qwen", "kimi", "doubao"):
            try:
                resp = client.chat(TEST_QUESTION_SEARCH, enable_search=True)
                content = resp.choices[0].message.content
                print(f"  Search:   OK ({len(content)} chars)")
                preview = content[:150] + ("..." if len(content) > 150 else "")
                print(f"    {preview}")
            except Exception as e:
                err_msg = str(e)
                if len(err_msg) > 200:
                    err_msg = err_msg[:200] + "..."
                print(f"  Search:   ERROR - {err_msg}")
        else:
            print("  Search:   N/A (no built-in search for this model via ModelVerse)")

    print("")
    print(SEP)
    print("Done.")


main()
