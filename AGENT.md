# 项目速览（压缩上下文）

## 业务目标
- 接口 `/api/command`，结合规则与豆包大模型，对用户中文指令做语义解析，输出结构化 `function_analysis`。
- 重点场景：健康监测与评估、闹钟/提醒、娱乐教育、生活服务、商城等；必须返回固定 `result`，并在必要时给出 `target/event/status/confidence/need_clarify`。
- 允许多轮对话，`requiresSelection`、`need_clarify + clarify_message` 用于引导用户补充信息。

## 核心模块
| 目录 | 说明 |
| --- | --- |
| `app/services/intent_rules.py` | 规则链（天气/日历/闹钟/设置/健康…），返回 `RuleResult`。 |
| `app/services/intent_classifier.py` | 结合规则 + LLM：合并结果、匹配候选用户、内容 target 二次校准、闹钟 target LLM 兜底。 |
| `app/services/target_refiner.py` | pkuseg 分词 + 启发式 + LLM/相似度，确保 `小雅教育/曲艺/音乐` 等目标规范化。 |
| `app/utils/time_utils.py` | 时间解析工具：中文数字归一、相对/绝对时间解析、闹钟 target 生成。 |
| `app/services/command_service.py` | API 门面：调用分类器、拼接 `msg`（去重处理）、更新会话、返回最终响应。 |

## 技术要点
- **时间解析增强**：`_normalize_time_phrases` 将“十分钟之后”“半小时”等转成标准格式；改进 `_relative_pattern` 支持任意组合；若规则失败，`IntentClassifier._ensure_alarm_target` 用 LLM 解析。`target` 格式 `yyyy-mm-dd hh-mm-ss`。
- **内容目标校准**：`TargetRefiner` 使用 pkuseg(postag=True) 提取名词短语，去除“学学/学习/一下”等冗余；必要时调用 LLM 进行候选排序，否则使用相似度兜底。
- **多轮澄清**：`CommandService._compose_response_message` 去重合并模板/建议；`requiresSelection` 标记需要用户继续补充的信息场景。
- **人名匹配**：`IntentClassifier._resolve_user_target` 利用候选名单 + LLM 匹配，支持语音转文本误差（如“小杨”→“晓阳”）。
- **测试覆盖**：`tests/test_time_utils.py`、`tests/test_end_to_end.py` 等包含中文数字、半小时、LLM 兜底、教育目标校准等场景；`pytest` 通过 47 项。

## 依赖
- `pkuseg`（分词 + 词性）。
- `cn2an`（中文数字转阿拉伯，缺失时回退简易映射）。
- `dateparser`（日期解析），`cn2an`、`pkuseg` 均已在 `pyproject.toml` 注册。

## 使用建议
- 若需进一步提升时间解析，先扩展 `_normalize_time_phrases`/`_relative_pattern`，只在明确失败时调用 LLM。
- 新增业务意图时更新：`intent_definitions.py`、`intent_rules.py`、`prompt_templates.py`、必要的测试用例。
- Docker 打包流程：先 `./deploy.sh build`（多平台构建），再 `./deploy.sh save`；脚本会自动备份旧版 tar 并导出新的 `xy-assistant-latest.tar`。 
