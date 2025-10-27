from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Sequence, Tuple

from loguru import logger

from app.services.intent_definitions import IntentCode
from app.services.llm_client import DoubaoClient


CONTENT_INTENTS = {
    IntentCode.EDUCATION_GENERAL,
    IntentCode.ENTERTAINMENT_OPERA,
    IntentCode.ENTERTAINMENT_OPERA_SPECIFIC,
    IntentCode.ENTERTAINMENT_MUSIC,
    IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC,
}


@dataclass
class RefinementResult:
    target: Optional[str]
    source: str  # heuristic | llm | fallback | original


class TargetRefiner:
    """负责在意图已确定后，对 target 进行二次校准，兼顾 LLM 与本地兜底。"""

    def __init__(self, llm_client: DoubaoClient | None, llm_confidence_threshold: float = 0.6) -> None:
        self._llm_client = llm_client
        self._llm_confidence_threshold = llm_confidence_threshold

    def supports(self, intent_code: IntentCode) -> bool:
        return intent_code in CONTENT_INTENTS

    async def refine(
        self,
        intent_code: IntentCode,
        query: str,
        initial_target: str,
    ) -> RefinementResult:
        if not self.supports(intent_code):
            return RefinementResult(target=initial_target, source="original")

        candidates = self._generate_candidates(query, initial_target)
        if not candidates:
            return RefinementResult(target=initial_target, source="original")

        # 1. 先尝试启发式修正（例如去掉“习”前缀）
        heuristic = self._apply_heuristic(initial_target, query)
        if heuristic and heuristic != initial_target:
            return RefinementResult(target=heuristic, source="heuristic")

        # 2. 候选集大于 1 时尝试调用 LLM 做排序
        if self._llm_client and len(candidates) > 1:
            llm_target = await self._select_with_llm(query, candidates)
            if llm_target:
                return RefinementResult(target=llm_target, source="llm")

        # 3. 兜底：相似度匹配
        fallback = self._best_similarity_match(query, candidates)
        if fallback:
            return RefinementResult(target=fallback, source="fallback")

        return RefinementResult(target=initial_target, source="original")

    def _generate_candidates(self, query: str, initial_target: str) -> List[str]:
        raw_candidates: List[str] = []
        if initial_target:
            raw_candidates.append(initial_target)

        for pattern in [
            r"(学习|学|想学|练习|练|上课|上)([\u4e00-\u9fa5A-Za-z0-9]{2,})",
            r"(听|想听|听听|播放)([\u4e00-\u9fa5A-Za-z0-9]{2,})",
        ]:
            for match in self._findall(pattern, query):
                raw_candidates.append(match)

        return self._deduplicate(
            self._sanitize_candidate(candidate, query) for candidate in raw_candidates
        )

    @staticmethod
    def _findall(pattern: str, text: str) -> List[str]:
        import re

        results: List[str] = []
        for match in re.finditer(pattern, text):
            candidate = match.group(2)
            if candidate:
                results.append(candidate)
        return results

    @staticmethod
    def _sanitize_candidate(candidate: Optional[str], query: str) -> Optional[str]:
        if not candidate:
            return None
        cleaned = candidate.strip().strip("。！？?、，, ")
        if not cleaned:
            return None
        if cleaned.startswith("习") and "学习" in query:
            cleaned = cleaned[1:]
        if cleaned.startswith("学") and cleaned not in query and len(cleaned) > 1:
            cleaned = cleaned[1:]
        if cleaned.endswith(("教学", "课程")) and len(cleaned) > 2:
            cleaned = cleaned[:-2]
        return cleaned or None

    def _apply_heuristic(self, initial_target: str, query: str) -> Optional[str]:
        sanitized = self._sanitize_candidate(initial_target, query)
        return sanitized

    async def _select_with_llm(self, query: str, candidates: Sequence[str]) -> Optional[str]:
        if not self._llm_client:
            return None
        payload = {
            "query": query,
            "candidates": list(candidates),
            "instruction": "只从候选列表中选择最贴切的学习或娱乐对象。",
        }
        system_prompt = (
            "你是中文技能/曲目匹配助手。请阅读用户输入，从给定候选列表里选出最符合的选项。"
            "只允许返回 JSON，并包含 match 与 confidence 字段。"
        )
        messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        try:
            raw_text, parsed = await self._llm_client.chat(
                system_prompt=system_prompt,
                messages=messages,
                response_format={"type": "json_object"},
            )
            _ = raw_text  # 确保变量被引用
        except Exception as exc:  # noqa: BLE001
            logger.debug("target refine llm failed", error=str(exc))
            return None

        if not isinstance(parsed, dict):
            return None

        match = parsed.get("match")
        confidence = parsed.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else 0.0
        except (TypeError, ValueError):
            confidence_value = 0.0

        if match in candidates and confidence_value >= self._llm_confidence_threshold:
            return match
        return None

    @staticmethod
    def _best_similarity_match(query: str, candidates: Sequence[str]) -> Optional[str]:
        if not candidates:
            return None
        best_candidate = None
        best_score = -1.0
        for candidate in candidates:
            score = SequenceMatcher(None, query, candidate).ratio()
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate

    @staticmethod
    def _deduplicate(candidates: Sequence[Optional[str]]) -> List[str]:
        seen = set()
        results: List[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            results.append(candidate)
        return results
