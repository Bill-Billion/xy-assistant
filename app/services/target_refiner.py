from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, List, Optional, Sequence

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

_learning_prefixes = [
    "学习",
    "练习",
    "了解",
    "欣赏",
    "掌握",
    "研究",
    "学",
    "练",
    "看",
    "听",
    "习",
]

_learning_verbs = set(_learning_prefixes) | {f"{v}{v}" for v in ["学", "练", "听", "看"]}
_suffix_tokens = [
    "课程",
    "教学",
    "学习",
    "一下下",
    "一下",
    "吧",
    "嘛",
    "呀",
    "啊",
    "呢",
]
_noun_tags = {
    "n",
    "nr",
    "nr1",
    "nr2",
    "nrj",
    "nrf",
    "ns",
    "nt",
    "nz",
    "vn",
    "an",
}

_pkuseg_instance: Optional[Any] = None
_pkuseg_failed = False


def _get_pkuseg() -> Optional[Any]:
    global _pkuseg_instance, _pkuseg_failed
    if _pkuseg_failed:
        return None
    if _pkuseg_instance is None:
        try:
            import pkuseg

            _pkuseg_instance = pkuseg.pkuseg(postag=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pkuseg init failed", error=str(exc))
            _pkuseg_failed = True
            return None
    return _pkuseg_instance


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

        segmenter = _get_pkuseg()
        if segmenter:
            raw_candidates.extend(self._extract_candidates_via_seg(segmenter, query))

        if len(raw_candidates) == (1 if initial_target else 0):
            for pattern in [
                r"(学习|学|想学|练习|练|上课|上)([\u4e00-\u9fa5A-Za-z0-9]{2,})",
                r"(听|想听|听听|播放)([\u4e00-\u9fa5A-Za-z0-9]{2,})",
            ]:
                for match in self._findall(pattern, query):
                    raw_candidates.append(match)

        return self._deduplicate(
            self._sanitize_candidate(candidate, query) for candidate in raw_candidates
        )

    def _extract_candidates_via_seg(self, segmenter: Any, query: str) -> List[str]:
        try:
            tokens = segmenter.cut(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pkuseg segmentation failed", error=str(exc))
            return []

        results: List[str] = []
        length = len(tokens)
        i = 0
        while i < length:
            word, tag = tokens[i]
            word = word.strip()
            if not word:
                i += 1
                continue
            normalized = self._normalize_learning_token(word)
            if word in _learning_verbs or normalized in _learning_verbs or tag.startswith("v"):
                j = i + 1
                collected: List[str] = []
                while j < length:
                    next_word, next_tag = tokens[j]
                    next_word = next_word.strip()
                    if not next_word:
                        j += 1
                        continue
                    if next_word in {"，", "。", "、", "？", "!", "！"}:
                        break
                    if next_word in _learning_verbs:
                        break
                    if next_word in {"的", "地", "得"}:
                        j += 1
                        continue
                    if next_tag in _noun_tags or next_tag.startswith("n"):
                        collected.append(next_word)
                        j += 1
                        continue
                    break
                if collected:
                    results.append("".join(collected))
                i = j
                continue
            i += 1
        return results

    @staticmethod
    def _findall(pattern: str, text: str) -> List[str]:
        import re

        results: List[str] = []
        for match in re.finditer(pattern, text):
            candidate = match.group(2)
            if candidate:
                results.append(candidate)
        return results

    def _sanitize_candidate(self, candidate: Optional[str], query: str) -> Optional[str]:
        if not candidate:
            return None
        cleaned = candidate.strip()
        if not cleaned:
            return None

        cleaned = self._strip_redundant_prefix(cleaned, query)
        cleaned = self._strip_suffixes(cleaned)
        cleaned = cleaned.strip("。！？?、，, ")
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

    @staticmethod
    def _normalize_learning_token(token: str) -> str:
        if len(token) == 2 and token[0] == token[1] and token[0] in {"学", "练", "听", "看"}:
            return token[0]
        return token

    def _strip_redundant_prefix(self, text: str, query: str) -> str:
        working = text.strip()

        for prefix in sorted(_learning_prefixes, key=len, reverse=True):
            if working.startswith(prefix) and len(working) > len(prefix):
                trimmed = working[len(prefix) :]
                # 如果去除前缀后结果仍然在原句中，直接采用
                if trimmed and trimmed in query:
                    working = trimmed
                    break
                # 若不在原句中，但剩余部分没有再次出现学习动词，也视为冗余前缀
                if trimmed and not any(trimmed.startswith(p) for p in _learning_prefixes):
                    working = trimmed
                    break

        if len(working) >= 2 and working[0] == working[1] and working[0] in {"学", "练", "听", "看"}:
            working = working[1:]

        return working

    def _strip_suffixes(self, text: str) -> str:
        working = text
        for suffix in sorted(_suffix_tokens, key=len, reverse=True):
            if working.endswith(suffix) and len(working) > len(suffix):
                working = working[: -len(suffix)]
                break
        return working
