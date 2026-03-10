import httpx
import pytest

from app.services.llm_client import DoubaoClient


class FakeResponse:
    def __init__(self, status_code: int, *, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._text = text
        self.request = httpx.Request("POST", "https://example.com/v1/chat/completions")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,
            )

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return self._text


class FakeAsyncClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url: str, *, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_chat_does_not_send_thinking_by_default():
    client = FakeAsyncClient(
        [
            FakeResponse(
                200,
                payload={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )
        ]
    )
    llm = DoubaoClient(
        api_key="test-key",
        api_url="https://example.com/v1/chat/completions",
        model="doubao-seed-2-0-mini",
        max_retries=1,
        client=client,
    )

    raw, parsed = await llm.chat(
        system_prompt="system",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )

    assert raw == '{"ok": true}'
    assert parsed == {"ok": True}
    assert "thinking" not in client.calls[0]["json"]
    assert client.calls[0]["json"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_retries_without_response_format_after_400():
    client = FakeAsyncClient(
        [
            FakeResponse(400, text='{"error":"response_format not supported"}'),
            FakeResponse(
                200,
                payload={"choices": [{"message": {"content": '{"answer": "ok"}'}}]},
            ),
        ]
    )
    llm = DoubaoClient(
        api_key="test-key",
        api_url="https://example.com/v1/chat/completions",
        model="doubao-seed-2-0-mini",
        max_retries=1,
        client=client,
    )

    raw, parsed = await llm.chat(
        system_prompt="system",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )

    assert raw == '{"answer": "ok"}'
    assert parsed == {"answer": "ok"}
    assert len(client.calls) == 2
    assert "response_format" in client.calls[0]["json"]
    assert "response_format" not in client.calls[1]["json"]


@pytest.mark.asyncio
async def test_chat_allows_thinking_type_override():
    client = FakeAsyncClient(
        [
            FakeResponse(
                200,
                payload={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )
        ]
    )
    llm = DoubaoClient(
        api_key="test-key",
        api_url="https://example.com/v1/chat/completions",
        model="doubao-seed-2-0-mini",
        max_retries=1,
        client=client,
    )

    await llm.chat(
        system_prompt="system",
        messages=[{"role": "user", "content": "hi"}],
        overrides={"thinking_type": "disabled"},
    )

    assert client.calls[0]["json"]["thinking_type"] == "disabled"


@pytest.mark.asyncio
async def test_chat_supports_per_call_timeout_and_retry_override():
    client = FakeAsyncClient([httpx.ReadTimeout("boom")])
    llm = DoubaoClient(
        api_key="test-key",
        api_url="https://example.com/v1/chat/completions",
        model="doubao-seed-2-0-mini",
        max_retries=3,
        client=client,
    )

    raw, parsed = await llm.chat(
        system_prompt="system",
        messages=[{"role": "user", "content": "hi"}],
        timeout=15.0,
        max_retries=1,
    )

    assert raw == ""
    assert parsed == {}
    assert len(client.calls) == 1
    assert client.calls[0]["timeout"] == 15.0
