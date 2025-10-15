from __future__ import annotations

from loguru import logger

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse, FunctionAnalysis
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.core.config import Settings
from app.utils.time_utils import describe_alarm_target, now_e8


HEALTH_MONITOR_RESULTS = {
    "健康监测",
    "血压监测",
    "血氧监测",
    "心率监测",
    "血糖监测",
    "血脂监测",
    "体重监测",
    "体温监测",
    "血红蛋白监测",
    "尿酸监测",
    "睡眠监测",
}


def _render_template(function_analysis: FunctionAnalysis) -> str | None:
    """根据结果字段选择固定回复模板。返回 (模板文本, 可能的枚举意图)."""
    result = function_analysis.result or ""

    if result == "新增闹钟":
        readable_target = describe_alarm_target(function_analysis.target or "", now_e8())
        message = f"好的，我已为您设置{readable_target}的闹钟。"
        if function_analysis.event:
            message += f" 提醒事项：{function_analysis.event}。"
        if function_analysis.status:
            message += f" 频次：{function_analysis.status}。"
        return message.strip()

    if result == "关闭音乐":
        return "好的，正在关闭音乐。"

    if result == "关闭听书":
        return "好的，正在关闭听书。"

    if result == "关闭戏曲":
        return "好的，正在关闭戏曲。"

    if result in HEALTH_MONITOR_RESULTS:
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开{result}功能。"
        return f"好的，我已为您打开{result}功能。"

    if result == "息屏":
        return "好的，正在为您息屏。"

    return None


def _compose_response_message(function_analysis: FunctionAnalysis, fallback: str) -> str:
    """
    根据分析结果动态拼接返回给前端的 msg。
    可执行意图优先使用模板，咨询类按“建议→安全提示→澄清”组合。
    """
    if function_analysis.need_clarify and function_analysis.clarify_message:
        return function_analysis.clarify_message.strip()

    parts: list[str] = []
    seen: set[str] = set()

    def add(text: str | None) -> None:
        if not text:
            return
        candidate = text.strip()
        if candidate and candidate not in seen:
            parts.append(candidate)
            seen.add(candidate)

    template_text = _render_template(function_analysis)

    if template_text:
        add(template_text)
    else:
        add(function_analysis.advice)
        add(function_analysis.safety_notice)
        add(fallback)

    if not parts:
        parts.append(fallback)

    return " ".join(parts)


class CommandService:
    """命令服务门面，负责协调意图识别与会话状态更新。"""

    def __init__(
        self,
        intent_classifier: IntentClassifier,
        conversation_manager: ConversationManager,
        settings: Settings,
    ) -> None:
        # 意图识别器：将用户输入转换为结构化 function_analysis。
        self._intent_classifier = intent_classifier
        # 会话管理器：维护多轮上下文、澄清状态等。
        self._conversation_manager = conversation_manager
        self._settings = settings

    async def handle_command(self, payload: CommandRequest) -> CommandResponse:
        session_id = payload.session_id or self._conversation_manager.generate_session_id()
        # 提取会话上下文，便于构造多轮提示词。
        context = self._conversation_manager.get_state(session_id)

        logger.info(
            "handling command",
            session_id=session_id,
            query=payload.query,
            meta=payload.meta,
        )

        try:
            classification = await self._intent_classifier.classify(
                session_id=session_id,
                query=payload.query,
                meta=payload.meta or {},
                conversation_state=context,
            )
            function_analysis = FunctionAnalysis.model_validate(classification.function_analysis)
            reply_message = classification.reply_message
            raw_output = classification.raw_llm_output
        except Exception as exc:  # noqa: BLE001
            logger.exception("classification failed, using fallback", error=str(exc))
            function_analysis = FunctionAnalysis(
                result="未知指令",
                target="",
                event=None,
                status=None,
                confidence=0.0,
                need_clarify=True,
                clarify_message="我暂时无法理解您的需求，可以换种说法吗？",
                reasoning="遭遇异常，使用兜底策略",
            )
            reply_message = function_analysis.clarify_message or "请再描述一次您的需求。"
            raw_output = ""

        response_message = _compose_response_message(function_analysis, reply_message)

        logger.debug(
            "classification_output",
            session_id=session_id,
            result=function_analysis.model_dump() if hasattr(function_analysis, "model_dump") else getattr(function_analysis, '__dict__', function_analysis),
            raw_llm_output=raw_output,
        )

        self._conversation_manager.update_state(
            session_id=session_id,
            query=payload.query,
            response_message=response_message,
            function_analysis=function_analysis,
            raw_llm_output=raw_output,
        )

        return CommandResponse(
            code=200,
            msg=response_message,
            sessionId=session_id,
            function_analysis=function_analysis,
        )
