from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional
from uuid import uuid4

from cachetools import TTLCache


@dataclass
class ConversationTurn:
    """记录一次对话轮次的角色与文本。"""

    role: str
    content: str


@dataclass
class ConversationState:
    """单个会话的上下文快照。"""

    session_id: str
    history: List[ConversationTurn] = field(default_factory=list)
    pending_clarification: bool = False
    clarify_message: Optional[str] = None
    last_function_analysis: Optional[dict[str, Any]] = None
    raw_llm_output: Optional[str] = None
    user_candidates: List[str] = field(default_factory=list)
    last_selected_user: Optional[str] = None

    def as_messages(self, limit: int = 6) -> list[dict[str, str]]:
        """以 OpenAI/豆包 兼容格式返回最近若干轮对话。"""
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.history[-limit:]
        ]


class ConversationManager:
    """基于 TTLCache 的轻量级会话管理器。"""

    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 1024) -> None:
        self._store: TTLCache[str, ConversationState] = TTLCache(
            maxsize=max_sessions,
            ttl=ttl_seconds,
        )

    def generate_session_id(self) -> str:
        """生成新的 session_id，供 stateless 场景使用。"""
        return uuid4().hex

    def get_state(self, session_id: str) -> ConversationState:
        """获取会话状态，不存在则返回空状态。"""
        return self._store.get(session_id) or ConversationState(session_id=session_id)

    def record_user(self, session_id: str, user_text: str) -> None:
        """记录用户轮次。"""
        state = self.get_state(session_id)
        state.history.append(ConversationTurn(role="user", content=user_text))
        self._store[session_id] = state

    def record_assistant(
        self,
        session_id: str,
        assistant_text: str,
        function_analysis: Any,
        raw_llm_output: Optional[str] = None,
    ) -> None:
        state = self.get_state(session_id)
        state.history.append(ConversationTurn(role="assistant", content=assistant_text))
        # 将 Pydantic 对象转为 dict，便于存储与下轮提示。
        fa_dict = function_analysis.model_dump() if hasattr(function_analysis, "model_dump") else function_analysis
        state.last_function_analysis = fa_dict
        # pending_clarification 控制下一轮是否需要追问。
        state.pending_clarification = bool(fa_dict.get("need_clarify"))
        state.clarify_message = fa_dict.get("clarify_message")
        target = fa_dict.get("target")
        if isinstance(target, str) and target:
            state.last_selected_user = target
        state.raw_llm_output = raw_llm_output
        self._store[session_id] = state

    def update_state(
        self,
        session_id: str,
        query: str,
        response_message: str,
        function_analysis: Any,
        raw_llm_output: Optional[str] = None,
        user_candidates: Optional[List[str]] = None,
    ) -> None:
        """统一入口：先追加用户消息，再保存助手回复。"""
        self.record_user(session_id, query)
        if user_candidates is not None:
            state = self.get_state(session_id)
            state.user_candidates = user_candidates
            self._store[session_id] = state
        self.record_assistant(session_id, response_message, function_analysis, raw_llm_output)

    def set_user_candidates(self, session_id: str, candidates: List[str]) -> None:
        state = self.get_state(session_id)
        state.user_candidates = candidates
        self._store[session_id] = state

    def clear_session(self, session_id: str) -> None:
        """在需要时主动清理会话缓存。"""
        if session_id in self._store:
            del self._store[session_id]
