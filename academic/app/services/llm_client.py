from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger


class DoubaoClient:
    """豆包 ChatCompletions API 的轻量异步封装。"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model: str,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        # 基础配置参数
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """统一处理请求构造、重试机制以及 JSON 解析。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            "thinking": {
                "type": "disabled"
            }
        }
        if response_format:
            payload["response_format"] = response_format

        attempt = 0
        last_exception: Exception | None = None
        while attempt < self.max_retries:
            try:
                response = await self._client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = self._safe_parse_json(raw_text)
                logger.debug("LLM response received", parsed=parsed)
                return raw_text, parsed
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM 调用失败", attempt=attempt + 1, error=str(exc))
                last_exception = exc
                await asyncio.sleep(0.5 * (attempt + 1))
                attempt += 1

        if last_exception:
            raise last_exception
        raise RuntimeError("LLM 调用失败且无异常信息")

    def _safe_parse_json(self, text: str) -> dict[str, Any]:
        """将模型返回的字符串解析为 JSON，不合法时记录日志并返回空字典。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("模型返回非 JSON 文本", text=text)
            return {}

    async def aclose(self) -> None:
        """关闭底层 httpx 客户端，释放连接池。"""
        await self._client.aclose()
