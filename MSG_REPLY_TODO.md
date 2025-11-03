## TODO：一次 LLM 输出驱动的整体改造 + 轻量意图筛选层方案

### 1. 总体原则
- 通过 `IntentClassifier` 的单次 LLM 调用完成所有语义解析：意图、result、target、时间、事件、地点、健康建议等，禁止二次请求模型。
- 所有业务需求（闹钟、天气、健康、商城、家政、娱乐、聊天等）都在这一次调用中返回结构化字段；本地规则只做兜底或置信度校验。
- 若 LLM 输出异常或置信度不足，统一走兜底模板或澄清提示，避免接口超时/报错。
- 在豆包调用前新增“规则→轻量模型→豆包”的筛选层，为高频简单场景提供本地快速判定，同时保留灰度与回退。

### 2. 提示词与结构化要求
- 在 `app/services/prompt_templates.py` 中扩充结构：
  - `intent_candidates[]` 包含 `intent_code/result/target/parsed_time/event/event_confidence/status/status_confidence/advice/safety_notice/clarify_message/reply_hint/reason/confidence`。
  - 新增 `weather_info`：`location`（name/type/confidence）、`datetime`（text/iso/confidence）、`needs_realtime_data`、`weather_summary/condition/confidence`。
  - few-shot 覆盖所有业务场景：闹钟（绝对/相对时间、重复频次、人名）、天气（相对日期、地点缺失、天气要素）、日历、时间播报、健康监测/科普/医生、用药提醒、健康评估、家政、商城、娱乐、聊天等。

### 3. IntentClassifier 改造
- `_merge_results`：
  1. 解析 LLM 返回字段并校验置信度；
  2. 闹钟：直接使用 `parsed_time/event/status`，若置信度低则打标 `event_source=llm_low_conf`，完全缺失时再 fallback 规则；
  3. 天气：若 `needs_realtime_data=false` 则直接写入 `weather_summary`，否则标记交给 `WeatherService`；
  4. 健康/商城等：优先采用 LLM 提供的 `advice/safety/target`，缺失时用 `_default_reply` 兜底；
  5. reasoning 增加来源标记（`event_source`、`weather_source`、`alarm_details=llm` 等）。
- `_parse_alarm_with_llm` 仅在 LLM 无结果时兜底或删除。

### 4. WeatherService 改造
- `fetch(query, llm_weather_info)`：
  1. 接收 LLM 提供的 `location/date/weather_summary/needs_realtime_data`，不再调用 LLM 抽取地点/日期；
  2. 若置信度合格且无需实时数据，直接组装 `WeatherContext`；
  3. 需要实时数据时才调用外部天气 API，并与 LLM 信息合并；
  4. API 失败返回兜底提示并标记 `weather_source=api_failed`；
  5. 缓存 `(location_iso, date_iso)`，减少重复调用。

### 5. CommandService 流程
- 先跑分类器，再依据 `weather_info` 是否需要实时数据来决定是否调用 `weather_service.fetch`；
- `weather_service` 返回 `None` 或失败时，通过澄清提示/失败提醒兜底；
- `FunctionAnalysis` 扩展天气字段（summary/detail/confidence）。

### 6. 失败与兜底策略
- `DoubaoClient.chat`：超时上限 8s，失败重试 3 次，仍失败返回空 dict；分类器检测为空时立即兜底提示；
- 健康/告警场景若缺安全提示，强制补齐默认语；
- `CommandService` 在 `reply` 缺失时使用 `_compose_response_message` 生成自然语言。

### 7. 测试与监控
- 更新/新增测试：
  - `tests/test_intent_classifier.py`（闹钟、天气、健康字段检测）；
  - `tests/test_end_to_end.py`（天气实时/非实时、闹钟、人名、商城等）；
  - `tests/test_weather_service.py`（仅依赖 LLM 提供数据）；
  - 模拟天气 API 超时、LLM 空返回等异常。
- 监控指标：
  - LLM 调用耗时、重试次数；
  - `event_source`、`weather_source` 分布；
  - 天气 API 成功率；
  - 轻量模型命中率/误判率（后续上线后）。

### 8. 实施顺序
1. 更新提示词与 few-shot；
2. 调整 `IntentClassifier` 合并逻辑与兜底；
3. 重构 `WeatherService`；
4. 精简 `_parse_alarm_with_llm`；
5. 更新 `CommandService` + `FunctionAnalysis`；
6. 补充/修复单测与集成测试；
7. 压测关键问句，确认一次 LLM 输出完整结构；
8. 上线后监控日志与耗时，迭代提示词。

### 9. 轻量意图筛选层方案（豆包前置）

#### 9.1 目标与约束
- 目标：对天气、闹钟、家政、商城等高频简单场景，本地快速判定，仅复杂/不确定请求交给豆包，降低平均时延。
- 约束：确保准确率，低置信度或无法识别时必须回退豆包；保留灰度/feature flag 以便随时关闭。

#### 9.2 架构流程
```
用户请求
   │
   ▼
规则 → 轻量模型 → (置信度高) 直接输出结构化结果
                            (置信度低) → 豆包 IntentClassifier
```
- 规则处理确定性指令（如“关闭音乐”），轻量模型处理自然语言变体。

#### 9.3 轻量模型设计
- 模型选择：
  - 首选 fine-tune 中文 BERT/ERNIE 或 ChatGLM 做多意图分类，输出意图标签+置信度；
  - 备选 fastText 等快速分类器 + 关键词/ngram 特征。
- 数据准备：
  - 基于日志/需求构造标注数据：天气、闹钟、健康监测、家政、商城等每类数百条；
  - 覆盖口语表达、方言、模糊表达、边界情况，标签对齐既有 `IntentCode`。
- 训练评估：
  - Train/validation 划分，关注 F1、召回、精度，重点关注“高置信度区间准确率”，目标 >98%；
  - 产出阈值（如置信度 >0.8 时可本地返回）。

#### 9.4 集成流程
1. 规则优先：沿用现有 `intent_rules`，命中直接返回。
2. 轻量模型：
   - 在豆包调用前运行，返回 `intent_code + confidence`；
   - 若置信度≥阈值且属于允许快速处理的意图，直接构造 `function_analysis`（时间/地点可借助 `time_utils` 等解析）；
   - 否则进入豆包原流程。
3. 结构化输出：轻量层需能填充 result/target 等关键字段；若信息不足则降低置信度走豆包。

#### 9.5 阈值策略
- 推荐三档：
  - ≥0.85：直接返回本地结果；
  - 0.6–0.85：可本地返回并记入“需复核”，或继续交给豆包验证；
  - <0.6：直接交给豆包。
- 阈值附近倾向保守处理，避免误判。

#### 9.6 实施步骤
1. 数据整理 + 模型训练（离线）：样本导出→标注→训练→验证→确定阈值。
2. 服务集成：在 `IntentClassifier` 前增加“规则→轻量模型→豆包”，引入缓存与 feature flag。
3. 灰度验证：并行记录轻量模型与豆包结果，监控命中率、误判、时延下降，确认准确后扩大覆盖。
4. 监控与回退：记录轻量模型命中率、平均耗时、直接返回比例；保留 feature flag 以便随时关闭。

#### 9.7 后续扩展
- 若精度达标，可逐步扩展至健康科普、家庭医生等意图；
- 引入语义缓存，高频问句直接返回缓存结果；
- 中长期训练多任务模型，输出 result/target/event 等结构字段，减少本地解析工作。

#### 9.8 风险与应对
- 误判：通过阈值控制和错判反馈机制缓解；
- 维护成本：轻量模型需定期训练/更新 → 训练脚本和数据版本化；
- 覆盖范围：先从高频意图起步，逐步扩展。

### 10. 数据质量提升与语感优化
- 挑战：
  - 模板生成易形成机械语感，缺乏方言、错别字、非标准语序；
  - 多轮上下文可能语义不连贯；
  - 长尾场景、情绪化表达覆盖不足。
- 优化策略：
  1. **语料来源多元化**：引入脱敏真实日志、LLM 生成+人工复核、反向翻译增强自然度。
  2. **上下文一致性**：设计语义脚本，确保历史对话与当前指令逻辑一致；可用 LLM 做逻辑校验。
  3. **语感评分体系**：建立自然度/槽位准确度/上下文一致等审查指标；引入半自动质量评估工具。
  4. **覆盖率监测**：仪表板跟踪各意图/槽位覆盖，缺口提醒，驱动模板或真实语料补齐。
  5. **用户画像驱动**：针对老年人等目标用户补充方言、情绪化、生活化表达。
  6. **数据飞轮**：上线后监控误判案例 → 回流标注 → 更新数据与模型，保持语料新鲜与真实。
- 路线图：
  - 短期（1～2周）：扩充模板、引入 LLM 辅助生成、搭建抽样审核表单。
  - 中期（1～2月）：建立真实语料采集、语感评分工具、覆盖率仪表板。
  - 长期（持续）：形成数据飞轮，定期复审，确保轻量模型与豆包协同稳定。

### 11. 前置条件与执行提醒
- 当前缺乏轻量模型与充足标注数据，需要完成：
  1. **数据样本**：各主力意图至少几十至上百条真实问句与标签（含训练/验证划分）。
  2. **模型方案**：明确是否 fine-tune BERT/ChatGLM 或接入现成服务，并提供依赖说明。
  3. **集成要求**：确定模型部署方式与期望返回字段（仅 intent/confidence，或含 target/event）。
- 一旦基础准备就绪，可依次推进：训练脚本 → 推理接口 → IntentClassifier 合流 → 阈值&feature flag → 灰度测试 → 监控。

### 12. 当前阶段落地目标（规则泛化 + 结果归一）
- **用药提醒全覆盖**：
  - 整理“打开/查看/进入/帮我看”等前缀与“用药/服药/吃药/药物”关键词，统一映射 `result=用药提醒`，并保持 `parsed_time/time_text` 逻辑不变。
  - 在 `IntentClassifier` 中对规则命中的用药提醒执行 result 白名单校验，防止 LLM 生成其它描述。
- **特定日期天气统一化**：
  - 扩展日期解析支持“本/这/下周+周几”“第N天后”等表达，所有非今日/明日/后天场景统一返回 `result=特定日期天气`，`parsed_time` 保留 ISO，`time_text` 保存原短语。
  - WeatherService 复用上述结构，确保前端收到稳定字段用于播报。
- **娱乐与内容控制语义泛化**：
  - 构建“暂停/停止/别放”等停播词典映射到 `关闭音乐/戏曲/听书`；“继续/恢复/接着播”“继续听”统一映射 `result=继续播放`，必要时附带 `target` (`音乐/戏曲/听书`)。
  - 新增“讲笑话/段子/逗我笑”等表达映射 `result=笑话模式`，保证已有前端路径可用。
- **健康相关归一**：
  - `_normalize_topic` 剥离“判断方法/怎么办/有哪些症状”等后缀，保留疾病核心词，如“怎样判断有没有高血压”→`target=高血压`。
  - 在规则层优先识别“了解 XX 的健康状况/健康情况/身体情况”，统一返回 `result=健康画像`，允许无名情况下继续走科普。
- **农历问答准确化**：
  - 所有“农历多少”“农历 X 月 X 日是什么时候”依赖本地 `lunar_python` 推导；当表达为特定农历日时仅播报最近一次（无需同时给出历史值）。
  - `FunctionAnalysis` 一律包含 `parsed_time`（ISO）和 `time_text` 原短语，方便前端展示。
- **质量与测试**：
  - 为上述泛化场景新增参数化单测/集成测试，覆盖常见同义表达与边界情况。
  - 完成后更新基线快照（git 提交），确保可随时回退。
