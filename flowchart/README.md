# XY Assistant 流程图目录

本目录按照不同交互场景拆分 `XY Assistant` 中 `/api/command` 请求的处理流程。每个 Markdown 文件都包含一幅 Mermaid 流程图，可在支持 Mermaid 的 Markdown 预览工具中查看。

- `single_turn_intent.md`：单轮命中明确功能（例如闹钟、健康监测）的执行流程。
- `multi_turn_clarification.md`：需要澄清的多轮对话流程，展示澄清回合的生成与会话状态更新。
- `unknown_or_fallback.md`：无法匹配功能或模型异常时的兜底策略，包括建议、安全提示与澄清。

可以根据业务需求继续扩充新的场景图，并在此文件中登记说明。

