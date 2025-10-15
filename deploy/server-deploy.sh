#!/bin/bash

# XY Assistant 服务器端部署脚本
# 在Linux服务器上运行此脚本

set -e

# 配置
IMAGE_NAME="xy-assistant"
IMAGE_TAG="latest"
SERVICE_NAME="xy-assistant"
INSTALL_DIR="/opt/xy-assistant"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查系统要求
check_system() {
    log_info "检查系统要求..."
    
    # 检查操作系统
    if [ ! -f /etc/os-release ]; then
        log_error "不支持的操作系统"
        exit 1
    fi
    
    # 检查架构
    ARCH=$(uname -m)
    if [ "$ARCH" != "x86_64" ]; then
        log_error "不支持的架构: $ARCH，需要 x86_64"
        exit 1
    fi
    
    log_info "系统检查通过: $(uname -s) $ARCH"
}

# 安装Docker
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker已安装"
        return
    fi
    
    log_info "安装Docker..."
    
    # 检测发行版
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
    elif [ -f /etc/redhat-release ]; then
        # CentOS/RHEL
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo yum install -y docker-ce docker-ce-cli containerd.io
        sudo systemctl start docker
        sudo systemctl enable docker
        sudo usermod -aG docker $USER
    else
        log_error "不支持的Linux发行版"
        exit 1
    fi
    
    log_info "Docker安装完成"
}

# 安装Docker Compose
install_docker_compose() {
    if command -v docker-compose &> /dev/null; then
        log_info "Docker Compose已安装"
        return
    fi
    
    log_info "安装Docker Compose..."
    
    # 获取最新版本
    DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
    sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    
    log_info "Docker Compose安装完成"
}

# 创建安装目录
setup_directories() {
    log_info "创建安装目录..."
    
    sudo mkdir -p $INSTALL_DIR
    sudo mkdir -p $INSTALL_DIR/logs
    sudo mkdir -p $INSTALL_DIR/nginx
    
    # 设置权限
    sudo chown -R $USER:$USER $INSTALL_DIR
    
    log_info "目录创建完成: $INSTALL_DIR"
}

# 加载Docker镜像
load_image() {
    if [ ! -f "${IMAGE_NAME}-${IMAGE_TAG}.tar" ]; then
        log_error "镜像文件不存在: ${IMAGE_NAME}-${IMAGE_TAG}.tar"
        exit 1
    fi
    
    log_info "加载Docker镜像..."
    docker load -i ${IMAGE_NAME}-${IMAGE_TAG}.tar
    
    if [ $? -eq 0 ]; then
        log_info "镜像加载成功"
        docker images | grep $IMAGE_NAME
    else
        log_error "镜像加载失败"
        exit 1
    fi
}

# 复制配置文件
copy_configs() {
    log_info "复制配置文件到安装目录..."
    
    cp docker-compose.yml $INSTALL_DIR/
    cp .env.docker $INSTALL_DIR/
    
    # 检查nginx配置是否存在
    if [ -f nginx.conf ]; then
        cp nginx.conf $INSTALL_DIR/nginx/
    fi
    
    log_info "配置文件复制完成"
}

# 启动服务
start_service() {
    log_info "启动XY Assistant服务..."
    
    cd $INSTALL_DIR
    
    # 停止现有服务
    docker-compose down 2>/dev/null || true
    
    # 启动服务
    docker-compose up -d
    
    if [ $? -eq 0 ]; then
        log_info "服务启动成功"
    else
        log_error "服务启动失败"
        exit 1
    fi
}

# 检查服务状态
check_service() {
    log_info "检查服务状态..."
    
    cd $INSTALL_DIR
    
    # 等待服务启动
    sleep 10
    
    # 检查容器状态
    docker-compose ps
    
    # 检查健康状态
    log_info "等待服务健康检查..."
    for i in {1..30}; do
        if curl -f http://localhost:8000/health &>/dev/null; then
            log_info "服务健康检查通过"
            break
        fi
        echo -n "."
        sleep 2
    done
    
    echo ""
    
    # 最终状态检查
    if curl -f http://localhost:8000/health &>/dev/null; then
        log_info "🎉 XY Assistant部署成功!"
        log_info "服务地址: http://$(hostname -I | awk '{print $1}'):8000"
        log_info "API文档: http://$(hostname -I | awk '{print $1}'):8000/docs"
    else
        log_error "服务健康检查失败"
        log_info "查看日志: docker-compose logs -f"
        exit 1
    fi
}

# 显示服务信息
show_service_info() {
    log_info "=== 服务信息 ==="
    echo "安装目录: $INSTALL_DIR"
    echo "服务状态: docker-compose ps"
    echo "查看日志: docker-compose logs -f"
    echo "停止服务: docker-compose down"
    echo "重启服务: docker-compose restart"
    echo "更新服务: docker-compose pull && docker-compose up -d"
}

# 显示帮助
show_help() {
    echo "XY Assistant 服务器部署脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  install   完整安装部署"
    echo "  start     启动服务"
    echo "  stop      停止服务"
    echo "  restart   重启服务"
    echo "  status    查看状态"
    echo "  logs      查看日志"
    echo "  help      显示帮助"
}

# 主函数
main() {
    case "$1" in
        "install")
            check_system
            install_docker
            install_docker_compose
            setup_directories
            load_image
            copy_configs
            start_service
            check_service
            show_service_info
            ;;
        "start")
            cd $INSTALL_DIR && docker-compose up -d
            ;;
        "stop")
            cd $INSTALL_DIR && docker-compose down
            ;;
        "restart")
            cd $INSTALL_DIR && docker-compose restart
            ;;
        "status")
            cd $INSTALL_DIR && docker-compose ps
            ;;
        "logs")
            cd $INSTALL_DIR && docker-compose logs -f
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