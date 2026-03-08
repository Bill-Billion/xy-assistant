from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from time import perf_counter
from typing import Any, AsyncIterator, Dict, List, Optional

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
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stop_words: Optional[List[str]] = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # 基础配置参数
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.stop_words = stop_words or None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
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
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.stop_words:
            payload["stop"] = self.stop_words
        if response_format:
            payload["response_format"] = response_format
        if overrides:
            payload.update(overrides)

        last_exception: Exception | None = None
        payload_variants = self._build_payload_variants(payload)

        for variant_index, (variant_name, variant_payload) in enumerate(payload_variants):
            attempt = 0
            while attempt < self.max_retries:
                try:
                    call_start = perf_counter()
                    response = await self._client.post(self.api_url, headers=headers, json=variant_payload)
                    response.raise_for_status()
                    data = response.json()
                    raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    parsed = self._safe_parse_json(raw_text)
                    duration = round(perf_counter() - call_start, 3)
                    logger.debug(
                        "LLM response received",
                        parsed=parsed,
                        duration=duration,
                        variant=variant_name,
                        max_tokens=variant_payload.get("max_tokens"),
                        temperature=variant_payload.get("temperature"),
                        top_p=variant_payload.get("top_p"),
                    )
                    return raw_text, parsed
                except httpx.HTTPStatusError as exc:
                    last_exception = exc
                    response_text = self._clip_response_text(exc.response.text)
                    status_code = exc.response.status_code
                    logger.warning(
                        "LLM 请求被上游拒绝",
                        attempt=attempt + 1,
                        variant=variant_name,
                        status_code=status_code,
                        response_text=response_text,
                        has_response_format="response_format" in variant_payload,
                        has_thinking="thinking" in variant_payload,
                    )
                    if status_code == 400 and variant_index + 1 < len(payload_variants):
                        next_variant = payload_variants[variant_index + 1][0]
                        logger.warning(
                            "LLM 400 触发降级重试",
                            current_variant=variant_name,
                            next_variant=next_variant,
                        )
                        break
                    await asyncio.sleep(0.5 * (attempt + 1))
                    attempt += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("LLM 调用失败", attempt=attempt + 1, variant=variant_name, error=str(exc))
                    last_exception = exc
                    await asyncio.sleep(0.5 * (attempt + 1))
                    attempt += 1
            else:
                continue

            if isinstance(last_exception, httpx.HTTPStatusError) and last_exception.response.status_code == 400:
                continue
            break

        if last_exception:
            logger.warning("LLM 多次调用失败，返回空结果", error=str(last_exception))
        else:
            logger.warning("LLM 调用失败且无异常信息，返回空结果")
        return "", {}

    def _build_payload_variants(self, payload: Dict[str, Any]) -> list[tuple[str, Dict[str, Any]]]:
        variants: list[tuple[str, Dict[str, Any]]] = [("default", deepcopy(payload))]
        if "response_format" in payload:
            variant = deepcopy(payload)
            variant.pop("response_format", None)
            variants.append(("no_response_format", variant))
        if "thinking" in payload:
            variant = deepcopy(payload)
            variant.pop("thinking", None)
            variants.append(("no_thinking", variant))
        if "response_format" in payload and "thinking" in payload:
            variant = deepcopy(payload)
            variant.pop("response_format", None)
            variant.pop("thinking", None)
            variants.append(("no_response_format_no_thinking", variant))

        deduped: list[tuple[str, Dict[str, Any]]] = []
        seen_payloads: set[str] = set()
        for name, item in variants:
            serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if serialized in seen_payloads:
                continue
            seen_payloads.add(serialized)
            deduped.append((name, item))
        return deduped

    def _clip_response_text(self, text: str, *, limit: int = 500) -> str:
        raw = (text or "").strip()
        if len(raw) <= limit:
            return raw
        return raw[:limit] + "...(truncated)"

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """剥离 ```json ... ``` 等 markdown 代码块包裹。"""
        stripped = text.strip()
        if stripped.startswith("```"):
            # 去掉首行（```json / ```）
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1:]
            # 去掉末尾 ```
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3].rstrip()
        return stripped

    def _safe_parse_json(self, text: str) -> dict[str, Any]:
        """将模型返回的字符串解析为 JSON，不合法时记录日志并返回空字典。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试剥离 markdown 代码块后重新解析
        cleaned = self._strip_markdown_fences(text)
        if cleaned != text.strip():
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        logger.warning("模型返回非 JSON 文本", text=text)
        return {}

    async def chat_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        overrides: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """流式调用，逐 token yield 文本片段。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if overrides:
            payload.update(overrides)

        async with self._client.stream(
            "POST", self.api_url, headers=headers, json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    return
                try:
                    chunk = json.loads(data_str)
                    content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    async def aclose(self) -> None:
        """关闭底层 httpx 客户端，释放连接池。"""
        if hasattr(self._client, "aclose") and self._owns_client:
            await self._client.aclose()
