# Repository Guidelines

## 项目结构
- 应用源代码：`app/`（服务、路由、意图分类、天气等核心逻辑）
- 配置与环境：`.env`、`.env.docker`，Docker 相关脚本 `deploy.sh`、`deploy/`
- 测试：`tests/`（意图规则、时间解析、天气服务等）
- 工具脚本：`tools/`（意图数据集生成、延迟测量、模糊用例回归等）
- 数据与资源：`data/`、`app/data/`（城市列表等）

## 构建、运行与测试
- 本地运行：`uvicorn app.main:app --host 0.0.0.0 --port 8000`（启动 API 服务）
- 单元/集成测试：`pytest` 或按需运行单测 `pytest tests/test_intent_rules.py`
- 模糊用例回归：`python tools/run_fuzzy_tests.py --endpoint http://0.0.0.0:8000/api/command`
- Docker 构建：`DOCKER_CONTEXT=default docker buildx build --platform linux/amd64 --tag xy-assistant:latest --load .`
- 打包镜像：`docker save xy-assistant:latest -o xy-assistant-latest.tar`

## 代码风格与命名
- 语言：Python，缩进 4 空格，UTF-8
- 命名：模块/包用小写下划线，类用帕斯卡命名，常量全大写，下划线分隔
- 注释：关键业务逻辑和边界处理使用简洁中文注释
- 依赖：`pyproject.toml` 中声明，虚拟环境路径 `/venv`

## 测试规范
- 框架：`pytest`
- 覆盖范围：新增功能需具备对应单测/集成测试；时间解析、意图分类、天气调用等边界需覆盖
- 测试命名：文件 `test_*.py`，用例函数 `test_*`

## 提交与评审
- 每次在进行一个需求改动完成后，将修改的文件纳入版本管理，并写清楚本次的需求以及修改的思路
- 提交前确保测试通过、无多余调试输出
- 提交信息建议遵循“类型: 简述”格式（例：`fix: adjust weather city priority`）
- PR 要求：描述变更、影响范围、测试结果；涉及接口改动需附示例请求/响应

## 安全与配置
- 密钥与 API Key 仅放 `.env` / `.env.docker`，不要提交到仓库
- 生产部署使用 Docker，敏感配置通过环境变量注入

## 代理/自动化提示
- 遇到模糊指令优先依赖 LLM 澄清，不要输出模板化兜底；如使用 `meta.context.local_weather`，请根据语境自然引用，避免生硬拼接
