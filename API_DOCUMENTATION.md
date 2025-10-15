# XY Assistant API 接口文档

## 概述

XY Assistant API 是一个基于 FastAPI 的语义指令解析服务，结合豆包大模型和规则引擎，实现智能语音助手的指令理解和多轮对话功能。

**服务地址**: http://localhost:8001  
**API 版本**: v0.1.0  
**技术栈**: FastAPI + 豆包AI + 规则引擎

---

## 快速开始

### 服务启动
```bash
# 确保依赖已安装
pip install fastapi uvicorn dateparser lunar-python loguru

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### 在线API文档
- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc

---

## 接口列表

### 1. 健康检查

**接口**: `GET /health`  
**描述**: 检查服务运行状态

**请求示例**:
```bash
curl -X GET http://localhost:8001/health
```

**响应示例**:
```json
{
  "status": "ok"
}
```

---

### 2. 语义指令解析 (核心接口)

**接口**: `POST /api/command`  
**描述**: 解析用户的自然语言指令，返回结构化的意图分析结果

#### 请求参数

| 字段 | 类型 | 必填 | 描述 | 示例 |
|------|------|------|------|------|
| sessionId | string | 否 | 会话ID，用于多轮对话，未提供则自动生成 | "test-session-001" |
| query | string | 是 | 用户输入的自然语言指令 | "帮我订个6点的闹钟" |
| meta | object | 否 | 元数据信息，如设备类型等 | {"device": "speaker"} |

#### 响应参数

| 字段 | 类型 | 描述 | 示例 |
|------|------|------|------|
| code | int | 响应状态码，200表示成功 | 200 |
| msg | string | 回复消息，面向用户的友好提示 | "好的，我已为您处理 新增闹钟 相关的请求。" |
| sessionId | string | 会话ID | "test-session-001" |
| function_analysis | object | 功能分析结果 | 见下表 |

**function_analysis 字段说明**:

| 字段 | 类型 | 描述 | 示例 |
|------|------|------|------|
| result | string | 识别的功能类型 | "新增闹钟", "今天天气", "血压监测" |
| target | string | 目标参数 | "0d18h0m", "今天", "爸爸" |
| event | string | 事件描述 | "煮饭", null |
| status | string | 状态信息 | "每天早上", null |
| confidence | float | 置信度 (0.0-1.0) | 0.95 |
| need_clarify | boolean | 是否需要澄清 | false |
| clarify_message | string | 澄清问题 | "您想听戏曲还是看电影呢？" |
| reasoning | string | 推理过程 | "用户明确表示要6点的闹钟，对应新增闹钟意图" |

---

## 使用示例

### 1. 闹钟设置

**请求**:
```bash
curl -X POST http://localhost:8001/api/command \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "alarm-test-001",
    "query": "帮我订个6点的闹钟",
    "meta": {"device": "speaker"}
  }'
```

**响应**:
```json
{
  "code": 200,
  "msg": "好的，我已为您处理 新增闹钟 相关的请求。",
  "sessionId": "alarm-test-001",
  "function_analysis": {
    "result": "新增闹钟",
    "target": "0d18h0m",
    "event": null,
    "status": null,
    "confidence": 0.95,
    "need_clarify": false,
    "clarify_message": "",
    "reasoning": "用户明确表示要6点的闹钟，对应新增闹钟意图"
  }
}
```

### 2. 相对时间提醒

**请求**:
```bash
curl -X POST http://localhost:8001/api/command \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "reminder-test-001",
    "query": "提醒我10分钟后煮饭"
  }'
```

**响应**:
```json
{
  "code": 200,
  "msg": "已为您设置10分钟后煮饭的提醒",
  "sessionId": "reminder-test-001",
  "function_analysis": {
    "result": "新增闹钟",
    "target": "+0d0h10m",
    "event": "煮饭",
    "status": "10分钟后",
    "confidence": 0.95,
    "need_clarify": false,
    "clarify_message": "",
    "reasoning": "用户请求10分钟后煮饭，属于新建提醒场景，对应MEDICATION_REMINDER_CREATE意图"
  }
}
```

### 3. 天气查询

**请求**:
```bash
curl -X POST http://localhost:8001/api/command \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "weather-test-001",
    "query": "今天天气怎么样"
  }'
```

**响应**:
```json
{
  "code": 200,
  "msg": "好的，我来为您查询今天的天气情况哦",
  "sessionId": "weather-test-001",
  "function_analysis": {
    "result": "今天天气",
    "target": "今天",
    "event": null,
    "status": null,
    "confidence": 0.95,
    "need_clarify": false,
    "clarify_message": "",
    "reasoning": "用户询问今天天气，对应意图为WEATHER_TODAY"
  }
}
```

### 4. 健康监测

**请求**:
```bash
curl -X POST http://localhost:8001/api/command \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "health-test-001",
    "query": "我要给爸爸血压监测"
  }'
```

**响应**:
```json
{
  "code": 200,
  "msg": "好的，我已为您处理 血压监测 相关的请求。",
  "sessionId": "health-test-001",
  "function_analysis": {
    "result": "血压监测",
    "target": "爸爸",
    "event": null,
    "status": null,
    "confidence": 0.95,
    "need_clarify": false,
    "clarify_message": "",
    "reasoning": "用户表示要给爸爸血压监测，属于健康监测相关，对应HEALTH_MONITOR_GENERAL意图"
  }
}
```

### 5. 需要澄清的情况

**请求**:
```bash
curl -X POST http://localhost:8001/api/command \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "clarify-test-001",
    "query": "我想娱乐一下"
  }'
```

**响应**:
```json
{
  "code": 200,
  "msg": "您想听戏曲还是看电影呢？",
  "sessionId": "clarify-test-001",
  "function_analysis": {
    "result": "娱乐",
    "target": "",
    "event": null,
    "status": null,
    "confidence": 0.2,
    "need_clarify": true,
    "clarify_message": "您想听戏曲还是看电影呢？",
    "reasoning": null
  }
}
```

---

## 多轮对话机制

### 会话管理

系统通过 `sessionId` 维护用户的对话上下文，每个会话包含：

- **历史对话**: 最近6轮对话记录
- **状态信息**: 待澄清的问题、上次分析结果等
- **TTL机制**: 会话在30分钟无活动后自动过期

### 对话流程示例

**第一轮 - 模糊指令**:
```json
{
  "sessionId": "multi-001",
  "query": "我想娱乐"
}
```
响应: `need_clarify: true`, 系统要求澄清

**第二轮 - 澄清回复**:
```json
{
  "sessionId": "multi-001", 
  "query": "我想听戏曲"
}
```
响应: 系统理解为戏曲播放需求

**第三轮 - 上下文相关**:
```json
{
  "sessionId": "multi-001",
  "query": "换一首"
}
```
响应: 基于之前戏曲上下文，理解为切换戏曲

---

## 支持的指令类型

### 时间相关
- ✅ **闹钟设置**: "帮我订个6点的闹钟", "明天早上7点叫我"
- ✅ **时间查询**: "现在几点了", "播报时间"
- ✅ **提醒设置**: "提醒我10分钟后煮饭", "每天早上提醒我吃药"

### 天气相关
- ✅ **今天天气**: "今天天气怎么样"
- ✅ **明天天气**: "明天会下雨吗"
- ✅ **具体日期**: "10月2日天气如何"

### 健康相关
- ✅ **健康监测**: "血压监测", "给爸爸测血糖"
- ✅ **健康评估**: "健康评估", "健康画像"
- ✅ **用药提醒**: "新增用药提醒", "服药计划"

### 通讯相关
- ✅ **音频通话**: "给妈妈打电话"
- ✅ **视频通话**: "和儿子视频"
- ✅ **联系家人**: "联系家人", "小雅通话"

### 娱乐相关
- ✅ **音乐播放**: "听音乐", "播放邓丽君的歌"
- ✅ **戏曲播放**: "听戏曲", "播放京剧"
- ✅ **聊天陪伴**: "陪我聊聊", "聊天"

### 系统设置
- ✅ **音量调节**: "声音调大", "声音调小"
- ✅ **亮度调节**: "屏幕调亮", "亮度调低"
- ✅ **设置界面**: "打开设置"

---

## 错误处理

### 常见错误码

| 错误码 | 描述 | 原因 | 解决方案 |
|-------|------|------|----------|
| 500 | Internal Server Error | 服务内部错误 | 检查服务日志，确认豆包API配置 |
| 422 | Validation Error | 请求参数格式错误 | 检查JSON格式和必填字段 |

### 兜底机制

当出现异常时，系统会返回兜底响应：
```json
{
  "code": 200,
  "msg": "请再描述一次您的需求。",
  "sessionId": "xxx",
  "function_analysis": {
    "result": "未知指令",
    "target": "",
    "confidence": 0.0,
    "need_clarify": true,
    "clarify_message": "我暂时无法理解您的需求，可以换种说法吗？",
    "reasoning": "遭遇异常，使用兜底策略"
  }
}
```

---

## 配置说明

### 环境变量

在 `.env` 文件中配置以下参数：

```bash
# 豆包API配置
DOUBAO_API_KEY=your_api_key_here
DOUBAO_API_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_MODEL=your_model_id
DOUBAO_TIMEOUT=10.0

# 置信度阈值 (低于此值将触发澄清)
CONFIDENCE_THRESHOLD=0.7

# 运行环境
ENVIRONMENT=dev
```

### 系统参数

- **会话TTL**: 1800秒 (30分钟)
- **最大会话数**: 1024个
- **对话历史**: 保留最近6轮
- **超时时间**: 10秒

---

## 开发调试

### 日志查看
```bash
# 实时查看服务日志
tail -f logs/app.log

# 或直接查看控制台输出
```

### 测试工具推荐
- **Postman**: 图形化接口测试
- **curl**: 命令行快速测试  
- **httpie**: 更友好的HTTP客户端

### 性能监控
- 平均响应时间: ~3秒 (包含AI调用)
- 并发支持: 支持多用户同时访问
- 内存占用: 约200MB

---

## 开发扩展

### 添加新的意图类型

1. 在 `app/services/intent_definitions.py` 添加新的 `IntentCode`
2. 在 `app/services/intent_rules.py` 添加规则函数
3. 在 `RULE_CHAIN` 中注册新规则
4. 编写测试用例验证

### 自定义回复模板

修改 `app/services/prompt_templates.py` 中的系统提示词来调整AI回复风格。

### 扩展元数据处理

在 `app/services/intent_classifier.py` 中可以扩展对 `meta` 字段的处理逻辑。

---

## 联系支持

如有问题请查看:
- 项目README: `/README.md`
- 测试用例: `/tests/` 目录
- 在线文档: http://localhost:8001/docs

最后更新时间: 2025-09-28