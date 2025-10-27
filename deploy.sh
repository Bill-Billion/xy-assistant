#!/bin/bash

# XY Assistant Docker 构建和部署脚本
# 用途：在macOS上构建x86_64镜像并推送到服务器

set -e

# 配置
IMAGE_NAME="xy-assistant"
IMAGE_TAG="latest"
REGISTRY_URL=""  # 如果使用私有仓库，在此填写
SERVER_HOST=""   # 目标服务器地址
SERVER_USER=""   # 服务器用户名

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 确保 buildx 构建器可用
ensure_builder() {
    if docker buildx inspect multiarch >/dev/null 2>&1; then
        docker buildx use multiarch >/dev/null 2>&1 || docker buildx inspect multiarch
    else
        docker buildx create --name multiarch --use --bootstrap >/dev/null
    fi
}

# 备份已有的 tar 包
backup_existing_tar() {
    local tar_file="${IMAGE_NAME}-${IMAGE_TAG}.tar"
    if [ -f "${tar_file}" ]; then
        local timestamp
        timestamp=$(date +%Y%m%d%H%M%S)
        local backup_name="${IMAGE_NAME}-previous-${timestamp}.tar"
        mv "${tar_file}" "${backup_name}"
        log_warn "检测到现有 tar 包，已自动备份为 ${backup_name}"
    fi
}

# 检查Docker是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker服务未启动，请启动Docker"
        exit 1
    fi
    
    log_info "Docker检查通过"
}

# 检查配置文件
check_config() {
    if [ ! -f ".env.docker" ]; then
        log_error "未找到.env.docker文件，请配置环境变量"
        exit 1
    fi
    
    # 检查必要的环境变量
    source .env.docker
    if [ -z "$DOUBAO_API_KEY" ] || [ "$DOUBAO_API_KEY" == "your_api_key_here" ]; then
        log_error "请在.env.docker中配置正确的DOUBAO_API_KEY"
        exit 1
    fi
    
    log_info "配置文件检查通过"
}

# 构建Docker镜像 (x86_64)
build_image() {
    log_info "开始构建x86_64 Docker镜像..."
    
    # 设置构建器支持多平台
    ensure_builder
    log_info "预拉取基础镜像 python:3.11-slim (linux/amd64)..."
    docker pull --platform linux/amd64 python:3.11-slim || log_warn "预拉取基础镜像失败，继续使用本地缓存/拉取"
    
    # 构建x86_64镜像
    docker buildx build \
        --platform linux/amd64 \
        --tag ${IMAGE_NAME}:${IMAGE_TAG} \
        --load \
        .
    
    if [ $? -eq 0 ]; then
        log_info "镜像构建成功: ${IMAGE_NAME}:${IMAGE_TAG}"
    else
        log_error "镜像构建失败"
        exit 1
    fi
}

# 保存镜像到tar文件
save_image() {
    log_info "保存镜像到tar文件..."
    backup_existing_tar
    docker save ${IMAGE_NAME}:${IMAGE_TAG} -o ${IMAGE_NAME}-${IMAGE_TAG}.tar
    
    if [ $? -eq 0 ]; then
        log_info "镜像已保存到: ${IMAGE_NAME}-${IMAGE_TAG}.tar"
        ls -lh ${IMAGE_NAME}-${IMAGE_TAG}.tar
    else
        log_error "镜像保存失败"
        exit 1
    fi
}

# 推送到私有仓库 (可选)
push_image() {
    if [ -n "$REGISTRY_URL" ]; then
        log_info "推送镜像到私有仓库..."
        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_TAG}
        docker push ${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_TAG}
        log_info "镜像推送完成"
    else
        log_warn "未配置REGISTRY_URL，跳过推送步骤"
    fi
}

# 上传到服务器
upload_to_server() {
    if [ -n "$SERVER_HOST" ] && [ -n "$SERVER_USER" ]; then
        log_info "上传文件到服务器..."
        
        # 创建临时目录
        ssh ${SERVER_USER}@${SERVER_HOST} "mkdir -p /tmp/xy-assistant-deploy"
        
        # 上传必要文件
        scp ${IMAGE_NAME}-${IMAGE_TAG}.tar ${SERVER_USER}@${SERVER_HOST}:/tmp/xy-assistant-deploy/
        scp docker-compose.yml ${SERVER_USER}@${SERVER_HOST}:/tmp/xy-assistant-deploy/
        scp .env.docker ${SERVER_USER}@${SERVER_HOST}:/tmp/xy-assistant-deploy/
        scp deploy/server-deploy.sh ${SERVER_USER}@${SERVER_HOST}:/tmp/xy-assistant-deploy/
        
        log_info "文件上传完成，请在服务器上执行部署脚本"
        log_info "ssh ${SERVER_USER}@${SERVER_HOST}"
        log_info "cd /tmp/xy-assistant-deploy && chmod +x server-deploy.sh && ./server-deploy.sh"
    else
        log_warn "未配置服务器信息，请手动上传文件"
        log_info "需要上传的文件:"
        log_info "  - ${IMAGE_NAME}-${IMAGE_TAG}.tar"
        log_info "  - docker-compose.yml"
        log_info "  - .env.docker"
        log_info "  - deploy/server-deploy.sh"
    fi
}

# 清理临时文件
cleanup() {
    log_info "清理临时文件..."
    rm -f ${IMAGE_NAME}-${IMAGE_TAG}.tar
    log_info "清理完成"
}

# 显示帮助信息
show_help() {
    echo "XY Assistant Docker 部署脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  build     构建Docker镜像"
    echo "  save      保存镜像到tar文件"
    echo "  push      推送镜像到仓库"
    echo "  upload    上传到服务器"
    echo "  deploy    完整部署流程 (build + save + upload)"
    echo "  cleanup   清理临时文件"
    echo "  help      显示帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 deploy     # 完整部署"
    echo "  $0 build      # 仅构建镜像"
}

# 主函数
main() {
    case "$1" in
        "build")
            check_docker
            check_config
            build_image
            ;;
        "save")
            save_image
            ;;
        "push")
            push_image
            ;;
        "upload")
            upload_to_server
            ;;
        "deploy")
            check_docker
            check_config
            build_image
            save_image
            upload_to_server
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            if [ -z "$1" ]; then
                show_help
            else
                log_error "未知选项: $1"
                show_help
                exit 1
            fi
            ;;
    esac
}

main "$@"
