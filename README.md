# XY Assistant API

基于 FastAPI 的语义指令解析服务，结合豆包大模型和规则引擎，实现接口 `/api/command` 的功能分析与多轮对话。

## 开发环境

- Python 3.10+
- FastAPI, Uvicorn

## 快速开始

```bash
pip install -e .
uvicorn app.main:app --reload
```

default `.env.example` Provide keys.
