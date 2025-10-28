# LLM 驱动的交互升级路线

## 总体目标

- **LLM 主导语义理解与播报表达**，本地规则仅承担验证与兜底。
- **逐阶段落地**，优先改造天气播报，再迭代到其它领域（健康、闹钟等）。
- **保留现有能力**：所有既有接口契约、字段含义、测试用例全部保留且通过。

### 一、语义总线：意图与上下文理解

  1. 重构 IntentClassifier Prompt
      - 系统提示中列出全部可用 result、intent_code 枚举及字段含义，要求模型输出标准 JSON。
      - 把原 run_rules 的条件迁移为“提示约束 + 示例”，规则仅作为低置信度兜底。
      - 明确模型职责：判定意图、填充 result/target/event/status、反馈 reasoning、给出 confidence。
      - 对话上下文仍由 ConversationState 提供，但提示模型要合并历史信息（如上轮 clarifying 选择）。
  2. 动态参考消息
      - _build_reference_message 仅提供数据，如候选用户、当前时间、候选功能等；语言提示依靠 Prompt。
      - 当模型置信度低于阈值（例如 0.6），系统自动设置 need_clarify=True 及澄清话术，并回退至规则输出来防止空响应。
  3. 名字/候选用户匹配
      - 新增 _resolve_user_target 的 LLM 提示：输入“用户原话 + 前端候选名单”，让模型标记最接近的人名和置信度。
      - 若模型自信值低或给出列表外名字，则降级为 Levenshtein 最优匹配。
      - 对于“监测 vs 评估”同句并存的表达，让模型明确标注主意图。

  ———

  ### 二、领域专家模块

  1. 天气专家
      - 保留现有 WeatherService（地理解析、API 调用、缓存、天气判断）；新增 WeatherBroadcastGenerator：
          - 输入 weather_context.to_prompt_dict() + 用户原问题 + 条件判断结果；
          - 输出 JSON：{"broadcast_message": "...", "confidence": 0~1, "tags": [...]}；
          - 在 System Prompt 中规定模板和缺失数据处理；broadcast_message 用于 weather_summary。
      - 失败或 confidence 低于阈值时，回退到 WeatherContext.summary 并记录 llm_metadata["broadcast"]。
  2. 健康建议专家
      - 编写新的 Prompt：要求模型针对症状给出专业建议+风险提示，并提醒“非医疗诊断，以医生建议为准”；
      - 输出结构化字段：{ "reply": "...", "advice": "...", "safety_notice": "...", "confidence": 0~1 }；
      - CommandService 在健康类意图触发时调用，并对低置信度结果回退到模板提示或澄清。
  3. 闹钟/功能指令专家
      - 时效性要求高，继续保持本地解析时间/事件/重复规则；
      - 可选：让 LLM 再润色一条补充语句（“需要我再提醒其他事项吗？”），但核心播报仍由本地模板生成，防止格式错误。

  ———

  ### 三、验证与兜底层

  1. Schema 校验
      - 新增 LLMResponseValidator：
          - 校验 result 是否在白名单；
          - target 字段字符长度、是否包含非法字符；
          - 时间字段统一转换成 ISO/相对时长；
          - 失败时记录日志并回退到安全提示。
  2. 故障策略
      - 所有 LLM 调用使用带重试的 DoubaoClient，同时设定 timeout；
      - 在 Settings 加开关（如 LLM_BROADCAST_ENABLED），便于灰度启用；
      - 通过 llm_metadata 记录每次调用的原始 JSON、置信度和回退原因。
  3. 日志与追踪
      - Loguru 结构化日志添加字段：intent_code、llm_confidence、fallback_reason；
      - 指标：澄清率、回退次数、平均响应时长。

  ———

  ### 四、Prompt 模板建议（示例）

  1. 意图分类 System Prompt 摘要

     你是“小雅数字健康机器人”的指令分析助手。
     - 输出 JSON：{ "intent_code": "...", "result": "...", "target": "...", ... }
     - 可选 intent_code 列表：...
     - 字段含义说明：...
     - 必须诚实报告 confidence；低于 0.6 时设置 need_clarify=true 并给出澄清语句。
     - 不得出现未知 result；若无合适结果，设置 result="" 并澄清。
     （User Message 附 query、对话历史、参考信息）
     （User Message 附 query、对话历史、参考信息）
  2. 天气播报 System Prompt（上一条答复已详细列出，可直接引用）。
  3. 健康建议 System Prompt

     角色：小雅数字健康助手；
     任务：解读用户描述症状，输出 JSON:
     {
       "reply": "…",           # 自然语言回答
       "advice": "…",          # 具体建议
       "safety_notice": "…",   # 医疗免责声明
       "confidence": 0~1
     }
     规则：不得提供诊断；若风险高需提醒就医；回答要包含对症状的初步分析。

  ———

  ### 五、逐步实施计划

  | 阶段 | 目标                                                         | 核心任务                                                         |
  |------|--------------------------------------------------------------|------------------------------------------------------------------|
  | P0   | 天气播报升级                                                 | 新增 WeatherBroadcastGenerator；集成命令层调用；补充单测       |
  | P1   | 意图分类Prompt重构 + 校验层                                  | 重写 Prompt；引入 LLMResponseValidator；迁移规则到提示         |
  | P2   | 健康建议专家、名字匹配强化                                   | 接入健康专家 Prompt；新增用户候选匹配 LLM；扩展测试              |
  | P3   | 监控 & 配置开关                                              | 配置项+日志+指标；灰度启用；最终移除已冗余的规则分支             |

  每个阶段均需：

  - 保持现有 pytest 套件全部通过；
  - 新增针对 LLM 的单测（使用伪造响应）；
  - 更新文档（如 AGENT.md、Prompt 仓库）。

  ———

  ### 六、多智能体讨论

  - 当前方案本质上已形成“多阶段 LLM”：
      1. 意图理解；
      2. 领域专家（天气/健康等）；
      3. 验证器（纯本地）。
  - 若后续需求更复杂，可再引入：
      - 专门的澄清生成 Agent（根据失败原因组织澄清问句）；
      - 安全审计 Agent（对播报做最终审核）。
  - 但建议先把上述单模型协作跑稳，再评估是否需要进一步拆分，避免无谓膨胀。

  ———

  ### 七、风险与对策

  | 风险点                              | 对策                                                                 |
  |-------------------------------------|----------------------------------------------------------------------|
  | 模型输出超出白名单或字段缺失        | LLMResponseValidator 拦截，回退模板                               |
  | LLM 超时／400／网络问题             | 统一使用 DoubaoClient 重试策略，失败直接兜底                       |
  | 播报啰嗦或不符风格                  | Prompt 中明确短句/口吻要求；保留本地 summary 做 fallback            |
  | 业务字段未来扩展（新增 result）     | 统一维护枚举清单 + Prompt 模板；通过配置/脚本自动同步                |
  | 大模型成本                           | 缓存 weather/health 结果；仅在需要时调用；可通过配置关闭            |

  ———


## 分阶段规划

### P0 天气播报升级（当前进行中）
- 引入 `WeatherBroadcastGenerator`，将结构化天气数据交给大模型生成播报文案。
- 明确 Prompt 模板、字段约束、缺失数据行为，并与本地摘要形成兜底链路。
- 新增日志、元数据记录与单元测试，确保回退策略可靠。

### P1 意图分类 Prompt 重构 + 输出校验
- 重写 `IntentClassifier` 的系统提示，迁移原规则到 Prompt 约束，模型按枚举给出结构化结果。
- 新增 `LLMResponseValidator` 对 `result/target/time` 等字段进行白名单检查。
- 低置信度时自动澄清并回退规则结果。

### P2 健康/人名解析增强
- 增设健康建议专家 Prompt，输出建议、免责声明、置信度。
- 使用 LLM + Levenshtein 的混合方式解析候选人名。
- 扩展集成测试验证复杂场景。

### P3 监控与渐进式上线
- 配置开关（Feature Flags）控制各阶段能力的启用。
- 完成日志、指标埋点并观察数据，逐步去除冗余规则。

## 多智能体策略

- 当前架构采用“多阶段 LLM + 本地验证”的轻量协同方式（意图理解 → 领域专家 → 校验兜底）。
- 若未来场景显著复杂，可追加澄清/审计子模型，但需谨慎评估复杂度与收益（KISS / YAGNI）。

## 当前状态

- 代码库已补充日期解析 LLM 兜底。
- 下一步将按照本计划自 P0 起实施，所有修改都会在提交信息中注明“LLM 升级阶段”和功能影响。

