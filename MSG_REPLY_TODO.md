## TODO：一次 LLM 输出驱动的整体改造方案

### 1. 总体原则
- 通过 `IntentClassifier` 的单次 LLM 调用完成所有语义解析：意图、result、target、时间、事件、地点、健康建议等，禁止再次请求模型。
- 所有业务需求（闹钟、天气、健康、商城、家政、娱乐、聊天等）都在这一次调用中返回结构化字段；本地规则只做兜底或置信度校验。
- 若 LLM 输出异常或置信度不足，统一走兜底模板或澄清提示，避免接口超时/报错。

### 2. 提示词与结构化要求
- 在 `app/services/prompt_templates.py` 中扩充结构：
  - `intent_candidates[]` 包含 `intent_code/result/target/parsed_time/event/event_confidence/status/status_confidence/advice/safety_notice/clarify_message/reply_hint/reason/confidence`。
  - 新增 `weather_info` 区块：`location`（name, type, confidence）、`datetime`（text, iso, confidence）、`needs_realtime_data`、`weather_summary`、`weather_condition`、`weather_confidence`。
  - few-shot 覆盖所有场景：闹钟（绝对/相对时间、重复频次、人名）、天气（相对日期、地点缺失、天气要素）、日历、时间播报、健康监测/科普/医生、用药提醒、健康评估、人名候选、家政/商城/娱乐/聊天/闲聊等。

### 3. IntentClassifier 改造
- `_merge_results`：
  1. 解析 LLM 返回的所有字段并校验置信度；
  2. 对闹钟，将 `parsed_time/event/status` 直接入结构；若置信度低，在 `event_source=llm_low_conf` 标记；只有完全缺失时再 fallback 规则，不再额外调 LLM；
  3. 对天气，读取 `weather_info`，当 `needs_realtime_data=false` 时直接将 `weather_summary` 写入；若 `needs_realtime_data=true` 则标记，后续交给 WeatherService；
  4. 对健康/商城等场景，直接信任 LLM 提供的 `advice/safety/target` 等信息。若缺失，使用 `_default_reply` 补全；
  5. reasoning 中附带来源：`event_source=...`、`weather_source=...`、`alarm_details=llm`/`event_override=llm` 等。
- 删除 `_parse_alarm_with_llm` 或使其仅在 LLM 输入为空时兜底（极端情况）。

### 4. WeatherService 改造
- `fetch(query, llm_weather_info)`：
  1. 接收分类器提供的 `location/date/weather_summary/needs_realtime_data`；不再调用 `_extract_location_with_llm` 或 `_extract_date_with_llm`；
  2. 若 `llm_weather_info` 置信度 ≥ 阈值且 `needs_realtime_data=false`，直接生成 `WeatherContext`，无需外部接口；
  3. 若 `needs_realtime_data=true`，调用一次天气 API 获取实时天气，并与 LLM 信息合并；
  4. API 失败时返回带兜底提示的 `WeatherContext`，并标记 `weather_source=api_failed`，不抛异常；
  5. 缓存 `(location_iso, date_iso)`，减少重复查询。

### 5. CommandService 流程
- 保持先跑分类器，再视 `weather_info` 决定是否调用 `weather_service.fetch`；
- 若 `weather_service` 返回 `None`（信息不足/失败），设置 `reply_message` 为澄清提示或失败提醒；
- `FunctionAnalysis` 中填入 `weather_summary/detail/confidence` 等字段，供前端展示。

### 6. 失败与兜底策略
- `DoubaoClient.chat`：超时 ≤ 8s，失败重试 3 次，之后返回空 dict；分类器检测到空结果立即走规则兜底并给出提示；
- 健康/告警场景缺安全提示时强制补齐默认安全语；
- `CommandService` 如果 `reply` 缺失，用 `_compose_response_message` 生成自然语言。

### 7. 测试与监控
- 更新/新增测试：
  - `tests/test_intent_classifier.py`：验证闹钟、天气、健康等字段来自 LLM；
  - `tests/test_end_to_end.py`：覆盖天气（needs_realtime_data=true/false）、闹钟、人名候选、商城等；
  - `tests/test_weather_service.py`：验证只接收 LLM 信息、不再调用 LLM；
  - 添加 mock 场景测试天气 API 超时、LLM 空返回。
- 监控指标：
  - LLM 调用耗时、重试次数；
  - `event_source`、`weather_source` 分布；
  - 天气 API 调用成功率。

### 8. 实施顺序
1. 更新提示词和 few-shot 示例；
2. 调整 `IntentClassifier` 合并逻辑和兜底标记；
3. 重构 `WeatherService` 接口，仅用 LLM 提供的数据；
4. 精简 `_parse_alarm_with_llm`（必要时删除）；
5. 更新 `CommandService` 与 `FunctionAnalysis` 字段；
6. 扩充/修复相关单测与集成测试；
7. 本地压测关键问句（闹钟、天气、健康），确认一次 LLM 调用即可返回完整结构；
8. 上线后监控日志与耗时，及时调整提示词。
