# Docker 部署指南

## 部署方案概述

本项目提供完整的Docker化部署方案，支持从macOS构建x86_64镜像并部署到Linux服务器。

## 🏗️ 架构设计

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   开发环境       │    │   Docker镜像     │    │   生产服务器     │
│   (macOS)       │───▶│   (x86_64)      │───▶│   (Linux)       │
│                 │    │                 │    │                 │
│ • 源代码编译     │    │ • 多阶段构建     │    │ • Docker运行     │
│ • 跨平台构建     │    │ • 镜像优化       │    │ • 负载均衡       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📦 文件结构

```
xy-assistant/
├── Dockerfile              # 多阶段构建文件
├── .dockerignore           # Docker忽略文件
├── docker-compose.yml      # 服务编排文件
├── .env.docker            # Docker环境配置
├── deploy.sh              # 本地构建脚本
├── deploy/
│   └── server-deploy.sh   # 服务器部署脚本
├── nginx/
│   └── nginx.conf         # Nginx配置
└── logs/                  # 日志目录
```

## 🚀 快速部署

### 1. 本地构建（macOS）

```bash
# 1. 配置环境变量
cp .env .env.docker
vim .env.docker  # 修改为生产环境配置

# 2. 一键构建和部署
./deploy.sh deploy

# 或分步执行
./deploy.sh build    # 构建镜像
./deploy.sh save     # 保存镜像（会自动备份旧版 tar）
./deploy.sh upload   # 上传到服务器
```

### 2. 服务器部署（Linux）

```bash
# 在服务器上执行
cd /tmp/xy-assistant-deploy
chmod +x server-deploy.sh
./server-deploy.sh install
```

## 🔧 配置说明

### Docker配置 (.env.docker)

```bash
# 豆包API配置
DOUBAO_API_KEY=your_api_key_here
DOUBAO_API_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_MODEL=your_model_id
DOUBAO_TIMEOUT=10.0

# 应用配置
CONFIDENCE_THRESHOLD=0.7
ENVIRONMENT=prod
ENABLE_HIGH_CONFIDENCE_RULES=false

# 天气服务（如需关闭可设为 false）
WEATHER_API_ENABLED=true
WEATHER_API_APP_CODE=your_weather_appcode
WEATHER_API_BASE_URL=https://ali-weather.showapi.com
WEATHER_API_TIMEOUT=5.0
WEATHER_API_VERIFY_SSL=false
WEATHER_DEFAULT_CITY=长沙市
WEATHER_DEFAULT_LAT=28.22778
WEATHER_DEFAULT_LON=112.93886
WEATHER_CACHE_TTL=600
WEATHER_REALTIME_CACHE_TTL=60
WEATHER_GEO_CACHE_TTL=86400
WEATHER_LLM_ENABLED=true
WEATHER_LLM_CONFIDENCE_THRESHOLD=0.6
```

### 部署脚本配置 (deploy.sh)

```bash
# 修改以下变量
REGISTRY_URL=""      # 私有镜像仓库地址（可选）
SERVER_HOST=""       # 服务器IP地址
SERVER_USER=""       # 服务器用户名
```

## 🎯 部署选项

### 基础部署
仅部署API服务，适合简单场景：
```bash
docker-compose up -d xy-assistant
```

### 带Nginx的完整部署
包含反向代理和负载均衡：
```bash
docker-compose --profile with-nginx up -d
```

### 集群部署
多实例负载均衡：
```bash
docker-compose up -d --scale xy-assistant=3
```

## 📊 资源配置

### 容器资源限制
- **内存限制**: 512MB
- **CPU限制**: 0.5核
- **内存预留**: 256MB
- **CPU预留**: 0.25核

### 存储映射
- **日志目录**: `./logs:/app/logs`
- **Nginx日志**: `./logs/nginx:/var/log/nginx`

## 🔍 监控和维护

### 健康检查
```bash
# 检查服务状态
curl http://localhost:8000/health

# 查看容器状态
docker-compose ps

# 查看服务日志
docker-compose logs -f xy-assistant
```

### 常用运维命令
```bash
# 查看服务状态
./deploy/server-deploy.sh status

# 查看实时日志
./deploy/server-deploy.sh logs

# 重启服务
./deploy/server-deploy.sh restart

# 停止服务
./deploy/server-deploy.sh stop
```

## 🔒 安全配置

### 1. 防火墙设置
```bash
# 开放必要端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp
```

### 2. SSL配置（可选）
```bash
# 生成SSL证书
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/server.key \
  -out nginx/ssl/server.crt
```

### 3. 环境变量保护
```bash
# 设置文件权限
chmod 600 .env.docker
```

## 🚨 故障排除

### 常见问题

1. **镜像构建失败**
   ```bash
   # 清理Docker缓存
   docker system prune -a
   ```

2. **服务启动失败**
   ```bash
   # 查看详细日志
   docker-compose logs xy-assistant
   ```

3. **健康检查失败**
   ```bash
   # 检查端口占用
   netstat -tlnp | grep 8000
   ```

4. **内存不足**
   ```bash
   # 调整资源限制
   vim docker-compose.yml
   ```

### 日志分析
```bash
# 查看应用日志
tail -f logs/app.log

# 查看Nginx访问日志
tail -f logs/nginx/access.log

# 查看容器资源使用
docker stats
```

## 📈 性能优化

### 1. 镜像优化
- 使用多阶段构建减少镜像大小
- 选择Alpine基础镜像
- 清理不必要的依赖

### 2. 运行时优化
- 启用Gzip压缩
- 配置适当的worker数量
- 使用内存缓存

### 3. 网络优化
- 使用Nginx反向代理
- 配置HTTP/2
- 启用keep-alive

## 🔄 CI/CD集成

### GitHub Actions示例
```yaml
name: Build and Deploy
on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Build and Deploy
        run: |
          ./deploy.sh build
          ./deploy.sh save
          # 上传到服务器
```

## 📞 技术支持

如遇问题，请检查：
1. Docker和Docker Compose版本
2. 系统资源使用情况
3. 网络连接状态
4. 环境变量配置
5. 日志文件内容

---

**最后更新**: 2025-09-29  
**支持的架构**: x86_64  
**测试环境**: Ubuntu 20.04, CentOS 8, Debian 11
