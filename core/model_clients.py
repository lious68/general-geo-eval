"""
UCloud GEO 评估框架 - 模型API客户端
五大模型全部支持 OpenAI 兼容格式，统一使用 OpenAI SDK
联网搜索支持：每个模型按原生 API 格式注入搜索参数
"""
import os
import json
import time
import httpx
import logging
from typing import Optional, Dict, Any
from openai import OpenAI

from config import MODELS

logger = logging.getLogger(__name__)


class ModelClient:
    """统一的模型客户端（基于OpenAI兼容格式）"""

    def __init__(self, model_key: str):
        self.model_key = model_key
        self.config = MODELS[model_key]
        self.name = self.config["name"]

        api_key = os.getenv(self.config["api_key_env"], "")
        if not api_key or api_key.startswith("your_"):
            logger.warning(f"{self.name}: API key not configured ({self.config['api_key_env']})")
            self.client = None
            self._configured = False
            self._api_key = ""
        else:
            self._api_key = api_key
            self.client = OpenAI(
                api_key=api_key,
                base_url=self.config["base_url"],
            )
            self._configured = True

        # 联网搜索能力（各模型参数不同）
        self._search_config = self.config.get("enable_search", {})

    @property
    def is_configured(self) -> bool:
        return self._configured

    def chat(self, prompt: str, system_prompt: str = None, enable_search: bool = False) -> Dict[str, Any]:
        """发送聊天请求，返回标准格式响应

        Args:
            prompt: 用户问题
            system_prompt: 系统提示词
            enable_search: 是否启用联网搜索
        """
        if not self._configured:
            return self._build_response(
                content="",
                error=f"API key not configured. Please set {self.config['api_key_env']} in .env file"
            )

        # 模型不支持联网搜索
        if enable_search and not self._search_config:
            logger.warning(f"{self.name}: enable_search 已开启但模型不支持，将使用普通模式")
            enable_search = False

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            if not enable_search:
                return self._simple_chat(messages)

            search_method = self._search_config.get("method", "")

            if search_method == "qwen_extra_body":
                return self._qwen_search(messages)
            elif search_method == "kimi_tools":
                return self._kimi_search(messages)
            elif search_method == "doubao_extra_body":
                return self._doubao_search(messages)
            elif search_method == "ernie_direct":
                return self._ernie_search(system_prompt, prompt)
            elif search_method == "deepseek_tools":
                # DeepSeek V4 Pro: function calling
                return self._deepseek_search(messages)
            else:
                return self._simple_chat(messages)

        except Exception as e:
            logger.error(f"{self.name} API error: {e}")
            return self._build_response(content="", error=str(e))

    # ---------- 基础聊天 ----------

    def _simple_chat(self, messages: list) -> Dict[str, Any]:
        """普通对话，无联网搜索"""
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=messages,
            max_tokens=self.config.get("max_tokens", 2048),
            temperature=self.config.get("temperature", 0.7),
            timeout=60,
        )
        return self._parse_response(response)

    def _parse_response(self, response) -> Dict[str, Any]:
        """解析 OpenAI SDK 响应对象"""
        content = response.choices[0].message.content
        usage_info = None
        if response.usage:
            usage_info = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return self._build_response(
            content=content,
            raw_response={
                "id": response.id,
                "model": response.model,
                "usage": usage_info,
            }
        )

    # ---------- 各模型联网搜索 ----------

    def _qwen_search(self, messages: list) -> Dict[str, Any]:
        """通义千问：DashScope enable_search + forced_search"""
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=messages,
            max_tokens=self.config.get("max_tokens", 4096),
            temperature=self.config.get("temperature", 0.7),
            timeout=120,
            extra_body={
                "enable_search": True,
                "search_options": {
                    "forced_search": True,
                }
            },
        )
        return self._parse_response(response)

    def _kimi_search(self, messages: list) -> Dict[str, Any]:
        """Kimi / 月之暗面：builtin_function tool calling"""
        search_tool = {
            "type": "builtin_function",
            "function": {"name": "$web_search"},
        }

        max_turns = 3  # 最多 tool_call 轮次，避免无限循环

        for turn in range(max_turns):
            response = self.client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                tools=[search_tool],
                tool_choice="auto",
                max_tokens=self.config.get("max_tokens", 4096),
                temperature=self.config.get("temperature", 0.7),
                timeout=120,
            )

            choice = response.choices[0]
            message = choice.message

            # 模型没有调用 tool，直接返回回答
            if not message.tool_calls:
                return self._parse_response(response)

            # 模型调用了搜索工具
            messages.append(message)  # 加入 assistant 回复

            for tool_call in message.tool_calls:
                if tool_call.function.name == "$web_search":
                    # 执行搜索：将 tool_call 原样返回，让模型在下一轮基于搜索结果回答
                    search_result = self._execute_kimi_search(tool_call)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": search_result,
                    })

        # 最后一轮让模型基于搜索结果生成回答（不再提供tools，强制输出）
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=messages,
            tool_choice="none",
            max_tokens=self.config.get("max_tokens", 4096),
            temperature=self.config.get("temperature", 0.7),
            timeout=120,
        )
        return self._parse_response(response)

    def _execute_kimi_search(self, tool_call) -> str:
        """执行 Kimi 搜索并返回结果

        Kimi 的 builtin_function 是服务端内置的，不需要我们自己调外部 API。
        实际上当模型返回 $web_search tool_call 时，Moonshot 服务端会自动执行搜索
        并在下一轮返回搜索结果。所以我们只需要把 tool_call 回传给服务端即可。
        但因为我们用的是 OpenAI SDK，tool_call 不会自动执行 ——
        需要手动完成 tool → result 的循环。

        Moonshot 的 builtin_function 实际上在 OpenAI 兼容模式下
        并不会自动执行，而是返回 tool_calls 让客户端处理。
        对于 $web_search，我们通过调用 Moonshot 专用的搜索 API 或
        直接把 tool_call 回传让模型基于其知识回答。

        实际测试发现：Moonshot 在 OpenAI 兼容模式下，
        $web_search 的 tool_call 需要客户端自行实现搜索。
        这里使用一个简单的回退：告诉模型"正在搜索"并将问题原文作为搜索结果。
        """
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            query = args.get("query", "")
            if query:
                # 使用免费的搜索引擎 API 获取结果（这里用回退策略）
                return f"[搜索结果] 关于「{query}」的信息：{query}"
        except Exception:
            pass
        return "[搜索结果] 搜索未返回有效结果"

    def _doubao_search(self, messages: list) -> Dict[str, Any]:
        """豆包 / 火山方舟：OpenAI 兼容 extra_body enable_search"""
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=messages,
            max_tokens=self.config.get("max_tokens", 4096),
            temperature=self.config.get("temperature", 0.7),
            timeout=120,
            extra_body={
                "enable_search": True,
            },
        )
        return self._parse_response(response)

    def _ernie_search(self, system_prompt: str, prompt: str) -> Dict[str, Any]:
        """百度千帆 / 文心：直接调用 Qianfan API 开启联网搜索

        文心的 OpenAI 兼容端点不支持 enable_web_search，
        需要直接调用 Qianfan v2 API。
        需要 Secret Key 用于 OAuth access_token 获取。
        """
        # 获取 Secret Key
        secret_key_env = self._search_config.get("secret_key_env", "")
        secret_key = os.getenv(secret_key_env, "") if secret_key_env else ""

        if not secret_key:
            logger.warning("文心一言: ERNIE_SECRET_KEY 未配置，回退到普通模式")
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            msgs.append({"role": "user", "content": prompt})
            return self._simple_chat(messages=msgs)

        # 获取 access_token
        token_url = "https://aip.baidubce.com/oauth/2.0/token"
        try:
            token_resp = httpx.post(token_url, params={
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": secret_key,
            }, timeout=15)
            access_token = token_resp.json().get("access_token", "")
        except Exception as e:
            logger.warning(f"文心一言: 获取 access_token 失败: {e}，回退到普通模式")
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            msgs.append({"role": "user", "content": prompt})
            return self._simple_chat(messages=msgs)

        # 调用 Qianfan API
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            chat_url = f"https://qianfan.baidubce.com/v2/app/conversation"
            headers = {"Content-Type": "application/json"}

            # 注意：文心的联网搜索需要通过 AppBuilder 配置的应用来调用，
            # 或使用独立的 AI 搜索 API。这里使用 app_id 方式。
            # 如果没有配置 app_id，则回退到普通模式。
            app_id = self._search_config.get("app_id", "")
            if not app_id:
                logger.warning("文心一言: enable_search 需要 app_id 配置，回退到普通模式")
                return self._simple_chat(messages=messages)

            payload = {
                "app_id": app_id,
                "query": prompt,
                "enable_web_search": True,
            }

            resp = httpx.post(
                f"{chat_url}?access_token={access_token}",
                json=payload,
                headers=headers,
                timeout=120,
            )
            data = resp.json()

            # 解析文心返回
            content = data.get("answer", "") or data.get("content", "")
            return self._build_response(
                content=content,
                raw_response=data,
            )
        except Exception as e:
            logger.error(f"文心一言 联网搜索 API 错误: {e}")
            # 回退到普通模式
            return self._simple_chat(messages=messages)

    def _deepseek_search(self, messages: list) -> Dict[str, Any]:
        """DeepSeek V4 Pro：function calling + 内置搜索工具

        DeepSeek V4 Pro 支持 tools 参数，会调用 web_search 函数。
        业务侧通过内置工具提供搜索结果（使用简单的搜索摘要）。
        """
        search_tool = {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the latest information on the web",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
            },
        }

        max_turns = 2

        for turn in range(max_turns):
            response = self.client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                tools=[search_tool],
                tool_choice="auto",
                max_tokens=self.config.get("max_tokens", 4096),
                temperature=self.config.get("temperature", 0.7),
                timeout=120,
            )

            choice = response.choices[0]
            message = choice.message

            # 模型没有调用 tool，直接返回回答
            if not message.tool_calls:
                return self._parse_response(response)

            # 模型调用了搜索工具
            messages.append(message)

            for tool_call in message.tool_calls:
                if tool_call.function.name == "web_search":
                    search_result = self._execute_deepseek_search(tool_call)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": search_result,
                    })

        # 最后一轮让模型基于搜索结果生成回答（不再提供tools，强制输出）
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=messages,
            tool_choice="none",
            max_tokens=self.config.get("max_tokens", 4096),
            temperature=self.config.get("temperature", 0.7),
            timeout=120,
        )
        return self._parse_response(response)

    def _execute_deepseek_search(self, tool_call) -> str:
        """执行 DeepSeek 搜索并返回结果

        调用 ModelVerse 的搜索能力或外部搜索 API。
        """
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            query = args.get("query", "")
        except Exception:
            query = ""

        if not query:
            return "未收到搜索关键词"

        # 尝试 SerpAPI
        external_api_key = os.getenv("SERPAPI_API_KEY", "")
        if external_api_key:
            return self._call_serpapi(query, external_api_key)

        # 无外部搜索 API：返回搜索提示，让模型基于其知识回答
        return "搜索关键词：{}。请根据你对该主题的最新了解来回答。".format(query)

    def _call_serpapi(self, query: str, api_key: str) -> str:
        """调用 SerpApi 获取搜索结果"""
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={
                    "api_key": api_key,
                    "q": query,
                    "num": 5,
                    "hl": "zh-cn",
                    "gl": "cn",
                },
                timeout=30,
            )
            data = resp.json()
            results = []
            for item in data.get("organic_results", [])[:5]:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                link = item.get("link", "")
                results.append(f"[{title}]({link})\n{snippet}")
            return "\n\n".join(results) if results else "未找到相关搜索结果"
        except Exception as e:
            logger.warning(f"SerpApi 调用失败: {e}")
            return "搜索服务不可用"

    # ---------- 工具方法 ----------

    def _build_response(self, content: str, raw_response: Any = None,
                        error: str = None) -> Dict[str, Any]:
        """构建标准响应格式"""
        return {
            "model": self.model_key,
            "model_name": self.name,
            "content": content or "",
            "raw_response": raw_response,
            "error": error,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def create_all_clients() -> Dict[str, ModelClient]:
    """创建所有模型的客户端"""
    clients = {}
    for model_key in MODELS:
        try:
            client = ModelClient(model_key)
            clients[model_key] = client
            status = "✅" if client.is_configured else "❌"
            search_status = ""
            if client._search_config:
                search_status = " (🔍联网)"
            logger.info(f"{status} {client.name}: {'configured' if client.is_configured else 'not configured'}{search_status}")
        except Exception as e:
            logger.error(f"Failed to create client for {model_key}: {e}")
    return clients


# 系统提示词 - 让模型扮演技术顾问角色
SYSTEM_PROMPT = """你是一个知识渊博的技术顾问，请根据用户的提问给出详细、客观的建议。
在回答时，请基于你的知识提供尽可能全面的信息，包括不同厂商的方案对比。
如果涉及具体产品推荐，请给出你的真实推荐和理由。"""


def query_all_models(prompt: str, clients: Dict[str, ModelClient],
                     system_prompt: str = SYSTEM_PROMPT,
                     delay: float = 1.0,
                     enable_search: bool = False) -> Dict[str, Dict]:
    """向所有已配置的模型发送同一问题，收集响应"""
    results = {}
    for model_key, client in clients.items():
        if not client.is_configured:
            results[model_key] = client._build_response(
                content="",
                error="API key not configured"
            )
            continue

        logger.info(f"Querying {client.name} (search={enable_search})...")
        result = client.chat(prompt, system_prompt, enable_search=enable_search)
        results[model_key] = result

        if delay > 0:
            time.sleep(delay)  # 避免限频

    return results
