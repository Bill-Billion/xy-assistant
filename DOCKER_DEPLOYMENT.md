# Docker 部署指南

## 适用范围

本文档只描述当前仓库里真实存在的 Docker 交付路径：

- `Dockerfile`
- `.env.example`
- 本地自备的 `.env.docker`
- `docker buildx build`
- `docker save` / `docker load`

当前仓库中不存在以下资产，因此本文不再描述它们：

- `deploy.sh`
- `deploy/`
- `docker-compose.yml`
- `nginx/`

## 当前镜像行为

当前 `Dockerfile` 采用多阶段构建，运行时特征如下：

- 基础镜像：`python:3.11-slim`
- 服务入口：`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`
- 对外端口：`8000`
- 健康检查：`GET /health`
- 构建阶段会执行 `COPY .env.docker ./.env`

最后一条很重要：镜像构建时会把 `.env.docker` 一并复制进镜像。如果你不希望敏感配置进入镜像，需要先修改 `Dockerfile`，再执行构建。

## 1. 构建前准备

先基于模板生成 Docker 环境文件：

```bash
cp .env.example .env.docker
```

至少确认这些变量已填写：

- `DOUBAO_API_KEY`
- `DOUBAO_API_URL`
- `DOUBAO_MODEL`

如果需要天气能力，还应填写：

- `WEATHER_API_ENABLED=true`
- `WEATHER_API_APP_CODE`
- `WEATHER_API_BASE_URL`

## 2. 本地构建镜像

```bash
DOCKER_CONTEXT=default docker buildx build \
  --platform linux/amd64 \
  --tag xy-assistant:latest \
  --load .
```

构建完成后可检查镜像：

```bash
docker images xy-assistant:latest
```

## 3. 本地运行容器

```bash
docker run --rm \
  --name xy-assistant \
  -p 8000:8000 \
  --env-file .env.docker \
  xy-assistant:latest
```

说明：

- `--env-file .env.docker` 会在运行时覆盖同名环境变量
- 即使传入了 `--env-file`，镜像里仍然已经包含构建时复制进去的 `.env`
- 如果只想做本地验证，`--rm` 方便容器退出后自动清理

## 4. 健康检查与接口验证

容器启动后，可以用下面的命令验证：

```bash
curl http://127.0.0.1:8000/health
```

预期响应：

```json
{"status":"ok"}
```

也可以直接打开接口文档：

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## 5. 导出镜像

如果需要把镜像发到其他机器，可以直接导出 tar：

```bash
docker save xy-assistant:latest -o xy-assistant-latest.tar
```

## 6. 服务器导入与运行

将 `xy-assistant-latest.tar` 和服务器使用的环境文件传到目标机器后，执行：

```bash
docker load -i xy-assistant-latest.tar
```

然后启动容器：

```bash
docker run -d \
  --name xy-assistant \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file /path/to/.env.docker \
  xy-assistant:latest
```

建议额外确认：

- 服务器的 `8000` 端口已放行
- 传入的 `.env.docker` 与目标环境一致
- 如果前面用的是旧镜像标签，先停掉旧容器再启动新容器

## 7. 常用运维命令

查看运行状态：

```bash
docker ps --filter name=xy-assistant
```

查看日志：

```bash
docker logs -f xy-assistant
```

停止并删除容器：

```bash
docker stop xy-assistant
docker rm xy-assistant
```

## 8. 常见问题

### 构建时报 `.env.docker` 不存在

原因：当前 `Dockerfile` 明确执行了 `COPY .env.docker ./.env`。

处理方式：

```bash
cp .env.example .env.docker
```

### 容器能启动，但天气功能不可用

优先检查：

- `WEATHER_API_ENABLED`
- `WEATHER_API_APP_CODE`
- `WEATHER_API_BASE_URL`

### 服务起来了，但接口请求超时

优先检查：

- 豆包相关环境变量是否正确
- 目标机器是否能访问 `DOUBAO_API_URL`
- 容器日志里是否有上游 API 错误

### 需要严格避免把密钥打进镜像

当前仓库默认不满足这一要求。正确做法是：

1. 修改 `Dockerfile`，移除 `COPY .env.docker ./.env`
2. 重新构建镜像
3. 只在运行时通过 `--env-file` 或宿主机环境变量注入配置
