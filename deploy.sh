#!/bin/bash
# UCloud GEO 评估系统 - 一键部署脚本
# 用法: bash deploy.sh
set -e

INSTALL_DIR="/opt/ucloud-geo-eval"
echo "========================================="
echo "  UCloud GEO 评估系统 - 部署脚本"
echo "========================================="

# 1. 检测系统
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，正在安装..."
    yum install -y python3 python3-pip || apt-get install -y python3 python3-pip
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PYTHON_VERSION"

# 2. 安装依赖
echo ""
echo "📦 安装 Python 依赖..."
pip3 install fastapi uvicorn aiosqlite python-dotenv openai snownlp pandas openpyxl numpy

# 3. 检查/安装 Nginx
if ! command -v nginx &> /dev/null; then
    echo "📦 安装 Nginx..."
    yum install -y nginx || apt-get install -y nginx
fi
echo "✅ Nginx 已安装"

# 4. 部署代码
echo ""
echo "📁 部署代码到 $INSTALL_DIR ..."
mkdir -p $INSTALL_DIR
# 假设代码已在当前目录（git clone 下来的）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    cp -r $SCRIPT_DIR/* $INSTALL_DIR/ 2>/dev/null || true
    cp -r $SCRIPT_DIR/core $INSTALL_DIR/ 2>/dev/null || true
fi
mkdir -p $INSTALL_DIR/data

# 5. 初始化数据库
echo ""
echo "🗄️ 初始化数据库..."
cd $INSTALL_DIR/backend
python3 -c "import asyncio; from database import init_db; asyncio.run(init_db())"
echo "✅ 数据库初始化完成"

# 6. 配置 Nginx
echo ""
echo "🌐 配置 Nginx..."
cp $INSTALL_DIR/nginx.conf /etc/nginx/conf.d/ucloud-geo.conf
# 移除可能冲突的默认配置
nginx -t 2>/dev/null && echo "✅ Nginx 配置验证通过" || echo "⚠️ Nginx 配置有误，请检查"
systemctl enable nginx
systemctl restart nginx

# 7. 配置 systemd 服务
echo ""
echo "⚡ 配置 systemd 服务..."
cp $INSTALL_DIR/ucloud-geo.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ucloud-geo
systemctl restart ucloud-geo

# 8. 完成
echo ""
echo "========================================="
echo "  ✅ 部署完成！"
echo "========================================="
echo ""
echo "  访问地址: http://$(hostname -I | awk '{print $1}')/"
echo "  API文档:  http://$(hostname -I | awk '{print $1}')/api/docs"
echo ""
echo "  常用命令:"
echo "    查看服务状态: systemctl status ucloud-geo"
echo "    查看日志:     journalctl -u ucloud-geo -f"
echo "    重启服务:     systemctl restart ucloud-geo"
echo "    重启Nginx:    systemctl restart nginx"
echo ""
