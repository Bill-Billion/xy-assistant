# 整改 TODO（代码级）

1. `app/services/prompt_templates.py`
   - 重写系统 Prompt：
     - 明确身份为「中南小雅数字健康机器人」。
     - 分层描述字段约束、严禁自造 `result`。
     - 补充 21 类功能表格及多组 few-shot 示例（涵盖澄清、未知意图、日期/时间边界等）。
     - 说明接收的参考信息仅作辅助，必须结合语义判断。

2. `app/services/intent_classifier.py`
   - 在调用 LLM 前插入辅助消息，将规则/解析结果作为“参考信息”传递。
   - 在 `_merge_results` 内：
     - 只要 `intent_code != UNKNOWN`，强制 `result` 使用 `IntentDefinition.result`。
     - 若 `result` 不在枚举中或为空且无明确意图，设置 `need_clarify=true` 并生成澄清文本。
     - 将模型原始 `result`、拒绝原因附加到 `reasoning`，便于审计。
   - 当 `need_clarify` 为真时，确保回复与 `clarify_message` 一致；澄清完成后重置 pending 状态。

3. `app/services/intent_rules.py` / `app/utils/time_utils.py`
   - 调整规则输出为“辅助信号”：暴露 `suggested_intent`、`suggested_target` 等供 prompt 使用，而不是直接覆盖模型结果。
   - 保留现有解析函数但返回结构化辅助信息（需要时可被 `_merge_results` 采纳）。

4. `app/services/conversation.py`
   - 增强会话状态：保存 `pending_clarification`、`clarify_message`、`raw_llm_output`，便于下一轮 prompt 拼接。
   - 提供获取最近澄清文本的辅助方法，用于多轮对话。

5. 测试增强
   - `tests/test_intent_classifier.py`
     - 增补场景：
       1. 「我想联系小张」→ `result=小雅音频通话`，`target=小张`。
       2. 「明天适合搬家吗」→ `result=日期时间和万年历`。
       3. 低置信度澄清回合 + 用户确认后的第二轮。
       4. 未知闲聊，期望 `result=""` 且 `need_clarify=true`。
   - `tests/test_intent_rules.py`
     - 针对边界：天气超 15 天、闹钟 6 点判定、相对时间 + 周期表达、农历请求。
   - 新增集成测试（`tests/test_end_to_end.py`）：使用假 LLM 校验多轮会话与澄清闭环。
   - 建立样例数据集（`tests/fixtures/sample_queries.json`）覆盖 21 类功能及若干噪声输入，供回归脚本使用。

6. 日志与监控
   - 在 `CommandService` 中增加对 `raw_llm_output` 的结构化日志字段，方便后续审计。
   - 为澄清/未知响应添加计数指标（预留 hooks）。

> 注：当前因沙箱限制无法在 `.git/` 写入，需待本地环境重新执行 `git add`/创建分支。
