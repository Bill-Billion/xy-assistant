# XY Assistant Docker 部署包

## 📦 包含文件

- `xy-assistant-latest.tar` - Docker镜像包 (463MB)
- `docker-compose.yml` - 服务编排文件
- `.env.docker` - 环境配置文件
- `deploy/server-deploy.sh` - 自动部署脚本

## 🚀 快速部署

### 1. 上传文件到服务器
```bash
# 将以下文件上传到服务器 /tmp/xy-assistant-deploy/ 目录
- xy-assistant-latest.tar
- docker-compose.yml  
- .env.docker
- deploy/server-deploy.sh
```

### 2. 一键部署
```bash
cd /tmp/xy-assistant-deploy
chmod +x deploy/server-deploy.sh
./deploy/server-deploy.sh install
```

### 3. 手动部署（可选）
```bash
# 1. 加载镜像
docker load -i xy-assistant-latest.tar

# 2. 启动服务
docker-compose up -d

# 3. 检查状态
docker-compose ps
curl http://localhost:8000/health
```

## 📊 镜像信息

- **镜像名称**: xy-assistant:latest
- **架构**: linux/amd64 (x86_64)
- **大小**: 475MB (运行时)
- **tar包大小**: 463MB
- **基础镜像**: python:3.11-slim

## 🔧 服务配置

- **端口**: 8000
- **健康检查**: /health
- **API文档**: /docs
- **内存限制**: 512MB
- **CPU限制**: 0.5核

## 📝 服务器要求

- **操作系统**: Linux x86_64
- **Docker**: >= 20.10
- **内存**: >= 1GB
- **磁盘**: >= 2GB

## 🌐 访问服务

部署成功后：
- 健康检查: http://SERVER_IP:8000/health
- API文档: http://SERVER_IP:8000/docs
- 主要接口: http://SERVER_IP:8000/api/command

## 🔍 故障排除

```bash
# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 检查镜像
docker images | grep xy-assistant
```

---
**生成时间**: 2025-10-27  
**镜像版本**: latest  
**包含豆包API配置**: ✅
