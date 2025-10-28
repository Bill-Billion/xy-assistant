## TODO：msg 由大模型生成的代码级任务清单

1. **提示词强化**（`app/services/prompt_templates.py`）
   - 在系统提示词中新增“回复生成”说明，明确 `reply` 需涵盖功能确认、提醒信息以及安全提示。
   - 对闹钟、天气、健康监测、健康咨询等场景补充示例和硬性要求，确保模型直接输出完整回复。

2. **分类器合并逻辑调整**（`app/services/intent_classifier.py`）
   - `_merge_results`：保留结构化字段校验，但默认采用 LLM 提供的 `reply` 作为最终回复，仅在缺失或需要澄清时使用 `_default_reply`。
   - 在规则覆盖 LLM 候选时追加 `reply_override` 的 reasoning 标记，便于定位。
   - 清除 `reasoning` 重复内容，避免相同短语多次拼接。

3. **闹钟事件抽取增强**（`app/utils/time_utils.py`）
   - 扩展 `extract_event` 清洗词，覆盖“定个”“安排个”等口语表达，避免被作为事件返回。
   - `_parse_alarm_with_llm`：若模型返回事件或自然语言回复，在规则缺失时做兜底。

4. **CommandService 响应流程**（`app/services/command_service.py`）
   - 调整 `handle_command`，优先使用分类器提供的 `reply_message` 作为 `msg`。
   - 仅在 `reply_message` 为空、模型异常或澄清缺失时回退 `_compose_response_message`，并记录 `reply_source`。

5. **测试覆盖**
   - `tests/test_intent_classifier.py`：新增 reply 透传、澄清 fallback、规则覆盖等单测。
   - `tests/test_api.py`（如存在）或新增集成测试，验证 `/api/command` 响应 `msg` 与 LLM 输出一致。

