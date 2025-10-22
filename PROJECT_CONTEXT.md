# XY Assistant 项目概览

本文件用于记录项目核心设计、关键模块与运行方式，确保在清理上下文或交接时仍能快速恢复对系统的完整认知。

## 1. 项目定位
- 基于 **FastAPI** 的语义指令解析服务，统一入口 `/api/command`。
- 结合 **规则引擎 + 豆包大模型**，识别 20+ 类功能，并支持健康咨询、澄清对话等复杂语义。
- 输出结构遵循原有 `function_analysis` 字段，扩展 `advice`/`safety_notice` 等字段，同时保持 `result/target/event/status/confidence/need_clarify` 等兼容。

## 2. 核心模块
| 模块 | 说明 |
| --- | --- |
| `app/main.py` | FastAPI 启动入口，挂载路由与健康检查 |
| `app/routers/command.py` | `/api/command` 路由，入参出参模型基于 Pydantic |
| `app/services/command_service.py` | 协调请求流程：会话管理 → 意图识别 → 响应组装 |
| `app/services/intent_classifier.py` | 核心分类器，整合规则结果与 LLM JSON，处理澄清、置信度、建议、安全提示等 |
| `app/services/intent_rules.py` | 功能规则链，覆盖天气/时间/健康/家政等多场景；含健康监测细分、医生联系、人名解析等 |
| `app/services/conversation.py` | 基于 `TTLCache` 的会话状态管理，保存最近若干轮消息及澄清状态 |
| `app/services/llm_client.py` | 豆包 ChatCompletions API 异步封装，含重试与 JSON 解析 |
| `app/services/prompt_templates.py` | 系统 Prompt 构造，列举所有意图枚举及 few-shot 示例 |
| `app/utils/time_utils.py` | 时间解析工具：东八区时间、相对时间/周期解析、闹钟 target 生成、人名净化等 |
| `app/utils/calendar_utils.py` | 使用 `lunar-python` 获取农历、节气、宜忌等信息 |
| `tests/` | 单元+集成测试，覆盖规则、分类器、接口以及澄清多轮逻辑 |

## 3. 需求映射
- **功能识别**：21+ 类别，`IntentDefinition` 中维护 `IntentCode` 与固定 `result` 字段；新增的健康监测细分意图（血压/血氧/心率等）满足原始需求细粒度跳转。
- **天气日期**：处理今天/明天/后天以及 15 天内指定日期；超窗返回固定提示。
- **时间与闹钟**：解析模糊 6 点、相对时间/周期、事件、频次；`target` 返回东八区 ISO 8601 时间字符串。
- **健康场景**：
  - “健康监测/健康检测”→ `健康监测`；
  - “血压/血氧/…” → 对应细分 `result`；带人名时写入 `target`；
  - “联系医生/高医生”→ 音频/视频通话意图，`target` 精确到“高医生”。
- **澄清策略**：默认按照 `confidence` 触发；对可执行功能（健康监测细分、医生联系等）且置信度达阈值时直接确认，避免多余澄清。
- **建议与安全提示**：仅在非直接功能或 LLM 明确给出时保留；健康监测细分命中时默认清空 `advice/safety_notice`，符合“直接跳转”需求。

## 4. 运行与部署
### 本地运行
```bash
pip install -e .[dev]
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- 运行前配置环境变量（可参考 `.env.example`）：
  - `DOUBAO_API_KEY`
  - `DOUBAO_MODEL`
  - `DOUBAO_API_URL`
  - `CONFIDENCE_THRESHOLD`

### Docker 打包（x86_64）
Dockerfile 采用两阶段构建（builder 中执行 `pytest`），简要流程：
```bash
docker buildx build --platform linux/amd64 -t <registry>/xy-assistant:latest .
docker push <registry>/xy-assistant:latest
```
部署：
```bash
docker run -d --name xy-assistant \
  -p 8001:8000 \
  --env-file /path/to/.env \
  <registry>/xy-assistant:latest
```
健康检查：`GET /health`。

## 5. 测试体系
- `pytest` 全量覆盖 24 个用例：
  - `tests/test_time_utils.py`：时间解析、闹钟偏移等；
  - `tests/test_intent_rules.py`：天气、监测细分、睡眠、医生联系等规则链；
  - `tests/test_intent_classifier.py`：健康监测、医生通话、澄清流程、开场建议等；
  - `tests/test_api.py`：接口结构契约；
  - `tests/test_end_to_end.py`：多轮澄清到确认的闭环。

## 6. 已知注意事项
- **网络限制**：若环境无法访问外网，会在调用豆包接口时抛出 `httpx.ReadTimeout`；可在拥有网络的环境测试，或使用 Mock。
- **端口限制**：部分沙箱禁止监听 127.0.0.1:8000，可改用其他端口或在真实环境运行。
- **环境变量**：务必确保部署时正确配置豆包密钥，避免请求失败。

## 7. 后续扩展建议
- 将 Docker 流程集成至 CI，构建前自动运行测试。
- 若需支持更多功能，可在 `IntentCode`/规则链中按模板扩展，并更新 Prompt + 测试。
- 可考虑引入外部缓存或数据库持久化会话状态，以支撑多实例部署。

---
如需还原项目上下文，可首先阅读本文件，随后查看 `app/services/intent_classifier.py` 与 `app/services/intent_rules.py` 获取核心逻辑。
