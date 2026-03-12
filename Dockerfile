# 多阶段构建Dockerfile for xy-assistant
# 构建阶段：安装依赖和编译
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml ./

# 安装Python依赖到虚拟环境
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip setuptools wheel \
    && pip install numpy>=1.26 cython>=3.0 \
    && pip install \
        fastapi>=0.110 \
        uvicorn[standard]>=0.27 \
        httpx>=0.27 \
        python-dotenv>=1.0 \
        pydantic-settings>=2.2 \
        dateparser>=1.2 \
        lunar-python>=1.0 \
        cachetools>=5.3 \
        pydantic>=2.6 \
        loguru>=0.7 \
        cn2an>=0.5.21 \
    && pip install --no-build-isolation pkuseg>=0.0.25

# 运行阶段：精简镜像
FROM python:3.11-slim AS runtime

# 创建非root用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 设置工作目录
WORKDIR /app

# 从构建阶段复制虚拟环境
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制应用代码
COPY app/ ./app/
COPY .env.docker ./.env

# 设置权限
RUN chown -R appuser:appuser /app
USER appuser

# 健康检查（slim 镜像无 curl，使用 python stdlib）
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
