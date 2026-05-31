"""
UCloud GEO 评估 - API 连接测试工具
逐个测试各模型API是否可用，无需运行完整评估
用法: python test_api.py
"""
import os
import sys

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from config import MODELS


def test_model(model_key: str) -> bool:
    """测试单个模型API连接"""
    config = MODELS[model_key]
    name = config["name"]
    api_key = os.getenv(config["api_key_env"], "")

    print(f"\n{'='*50}")
    print(f"测试模型: {name} ({model_key})")
    print(f"{'='*50}")

    if not api_key or api_key.startswith("your_"):
        print(f"  ❌ API Key 未配置 ({config['api_key_env']})")
        return False

    print(f"  Base URL: {config['base_url']}")
    print(f"  Model: {config['model']}")
    print(f"  API Key: {api_key[:8]}...{api_key[-4:]}")

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url=config["base_url"],
        )

        print(f"  ⏳ 发送测试请求...")
        response = client.chat.completions.create(
            model=config["model"],
            messages=[{"role": "user", "content": "请用一句话介绍UCloud优刻得"}],
            max_tokens=200,
            temperature=0.7,
        )

        content = response.choices[0].message.content
        usage = response.usage

        print(f"  ✅ 连接成功！")
        print(f"  响应: {content[:100]}...")
        if usage:
            print(f"  Token使用: 输入{usage.prompt_tokens} + 输出{usage.completion_tokens} = {usage.total_tokens}")

        # 检测是否提及UCloud
        ucloud_keywords = ["UCloud", "ucloud", "优刻得"]
        mentioned = any(kw in content for kw in ucloud_keywords)
        print(f"  UCloud提及: {'是 ✅' if mentioned else '否 ❌'}")

        return True

    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        return False


def main():
    print("🔍 UCloud GEO 评估 - API 连接测试")
    print("=" * 50)

    results = {}
    for model_key in MODELS:
        success = test_model(model_key)
        results[model_key] = success

    print(f"\n{'='*50}")
    print("📊 测试结果汇总")
    print(f"{'='*50}")

    available = 0
    for model_key, success in results.items():
        name = MODELS[model_key]["name"]
        status = "✅ 可用" if success else "❌ 不可用"
        print(f"  {name}: {status}")
        if success:
            available += 1

    print(f"\n  可用模型: {available}/{len(MODELS)}")

    if available == 0:
        print("\n  ⚠️ 没有可用的模型！请检查 .env 文件中的 API Key 配置")
        print("  运行 `cp .env.example .env` 并填入你的 API keys")
    elif available < len(MODELS):
        print(f"\n  💡 部分模型可用，可以运行: python main.py --models {' '.join(k for k,v in results.items() if v)}")
    else:
        print("\n  ✅ 所有模型可用！可以运行: python main.py")


if __name__ == "__main__":
    main()
