from __future__ import annotations

from loguru import logger

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse, FunctionAnalysis
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.core.config import Settings


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

        logger.debug(
            "classification_output",
            session_id=session_id,
            result=function_analysis.model_dump() if hasattr(function_analysis, "model_dump") else getattr(function_analysis, '__dict__', function_analysis),
            raw_llm_output=raw_output,
        )

        self._conversation_manager.update_state(
            session_id=session_id,
            query=payload.query,
            response_message=reply_message,
            function_analysis=function_analysis,
            raw_llm_output=raw_output,
        )

        return CommandResponse(
            code=200,
            msg=reply_message,
            sessionId=session_id,
            function_analysis=function_analysis,
        )
