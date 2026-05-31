"""
UCloud GEO 评估框架 - 模型API客户端
五大模型全部支持 OpenAI 兼容格式，统一使用 OpenAI SDK
"""
import os
import json
import time
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
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url=self.config["base_url"],
            )
            self._configured = True

    @property
    def is_configured(self) -> bool:
        return self._configured

    def chat(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        """发送聊天请求，返回标准格式响应"""
        if not self._configured:
            return self._build_response(
                content="",
                error=f"API key not configured. Please set {self.config['api_key_env']} in .env file"
            )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                max_tokens=self.config.get("max_tokens", 2048),
                temperature=self.config.get("temperature", 0.7),
            )
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
        except Exception as e:
            logger.error(f"{self.name} API error: {e}")
            return self._build_response(content="", error=str(e))

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
            logger.info(f"{status} {client.name}: {'configured' if client.is_configured else 'not configured'}")
        except Exception as e:
            logger.error(f"Failed to create client for {model_key}: {e}")
    return clients


# 系统提示词 - 让模型扮演技术顾问角色
SYSTEM_PROMPT = """你是一个知识渊博的技术顾问，请根据用户的提问给出详细、客观的建议。
在回答时，请基于你的知识提供尽可能全面的信息，包括不同厂商的方案对比。
如果涉及具体产品推荐，请给出你的真实推荐和理由。"""


def query_all_models(prompt: str, clients: Dict[str, ModelClient],
                     system_prompt: str = SYSTEM_PROMPT,
                     delay: float = 1.0) -> Dict[str, Dict]:
    """向所有已配置的模型发送同一问题，收集响应"""
    results = {}
    for model_key, client in clients.items():
        if not client.is_configured:
            results[model_key] = client._build_response(
                content="",
                error="API key not configured"
            )
            continue

        logger.info(f"Querying {client.name}...")
        result = client.chat(prompt, system_prompt)
        results[model_key] = result

        if delay > 0:
            time.sleep(delay)  # 避免限频

    return results
