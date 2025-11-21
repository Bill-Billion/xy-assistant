from __future__ import annotations

import asyncio
import os
from pathlib import Path
from statistics import mean
from time import perf_counter

from app.services.llm_client import DoubaoClient
from app.services.prompt_templates import build_system_prompt


async def measure_latency(
    client: DoubaoClient,
    label: str,
    system_prompt: str,
    response_format: dict | None,
    runs: int = 3,
) -> list[float]:
    durations: list[float] = []
    for _ in range(runs):
        start = perf_counter()
        await client.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": "请简要回答：今天天气怎么样？"}],
            response_format=response_format,
        )
        durations.append(perf_counter() - start)
    return durations


async def main() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    client = DoubaoClient(
        api_key=os.environ["DOUBAO_API_KEY"],
        api_url=os.environ.get("DOUBAO_API_URL", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
        model=os.environ["DOUBAO_MODEL"],
        timeout=float(os.environ.get("DOUBAO_TIMEOUT", 10.0)),
        max_retries=1,
        max_tokens=(lambda v: int(v) if v else None)(os.environ.get("DOUBAO_MAX_TOKENS")),
        temperature=(lambda v: float(v) if v else None)(os.environ.get("DOUBAO_TEMPERATURE")),
        top_p=(lambda v: float(v) if v else None)(os.environ.get("DOUBAO_TOP_P")),
        stop_words=(os.environ.get("DOUBAO_STOP_WORDS").split(",") if os.environ.get("DOUBAO_STOP_WORDS") else None),
    )

    prompts = [
        (
            "simple",
            "你是一个回答简洁问题的助手，只需回复一句话。",
            None,
        ),
        (
            "medium",
            "你是家庭生活助手，需用两句中文回答问题，并包含一个贴心提醒。",
            None,
        ),
        (
            "complex_json",
            build_system_prompt(),
            {"type": "json_object"},
        ),
    ]

    try:
        print("Doubao latency measurement (seconds):")
        for label, prompt, response_format in prompts:
            durations = await measure_latency(client, label, prompt, response_format)
            print(f"- {label}: runs={len(durations)}, values={[round(d, 3) for d in durations]}, avg={mean(durations):.3f}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
