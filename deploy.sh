#!/bin/bash
# 通用 GEO 评估系统 - 服务器一键部署
# 在 xshell GEO 窗口中执行: bash <(curl -sL https://raw.githubusercontent.com/lious68/general-geo-eval/master/deploy.sh)
# 或者先 clone 再执行

set -e
echo "========================================="
echo "  通用 GEO 评估系统 - 服务器部署"
echo "========================================="

# 1. 克隆代码
INSTALL_DIR="/opt/general-geo-eval"
if [ ! -d "$INSTALL_DIR" ]; then
    echo "📦 克隆代码..."
    yum install -y git 2>/dev/null || apt-get install -y git 2>/dev/null
    git clone https://github.com/lious68/general-geo-eval.git $INSTALL_DIR
else
    echo "✅ 代码已存在，拉取最新..."
    cd $INSTALL_DIR && git pull
fi

cd $INSTALL_DIR

# 2. 安装 Python 依赖
echo "📦 安装 Python 依赖..."
if ! command -v python3 &> /dev/null; then
    yum install -y python3 python3-pip 2>/dev/null || apt-get install -y python3 python3-pip 2>/dev/null
fi
pip3 install --upgrade pip -q
pip3 install fastapi uvicorn aiosqlite python-dotenv openai snownlp pandas openpyxl numpy playwright -q

# 2b. 安装 Playwright Chromium（WebChat 评测模式需要）
echo "🌐 安装 Playwright Chromium..."
pip3 install playwright -q
playwright install chromium 2>/dev/null || echo "⚠️  Playwright Chromium 安装失败，WebChat 模式不可用"
playwright install-deps chromium 2>/dev/null || true

# 3. 安装 Node.js 和构建前端
echo "📦 构建前端..."
if ! command -v node &> /dev/null; then
    echo "  安装 Node.js 18..."
    curl -fsSL https://rpm.nodesource.com/setup_18.x | bash - 2>/dev/null && yum install -y nodejs 2>/dev/null || \
    (curl -fsSL https://deb.nodesource.com/setup_18.x | bash - 2>/dev/null && apt-get install -y nodejs 2>/dev/null)
fi
cd $INSTALL_DIR/frontend
npm install --registry=https://registry.npmmirror.com 2>/dev/null
npm run build 2>/dev/null
echo "✅ 前端构建完成"
cd $INSTALL_DIR

# 4. 初始化数据库
echo "🗄️ 初始化数据库..."
mkdir -p $INSTALL_DIR/data
cd $INSTALL_DIR/backend
PYTHONPATH=$INSTALL_DIR/backend:$INSTALL_DIR/core python3 -c "
import asyncio; from database import init_db; asyncio.run(init_db())
print('数据库初始化完成')
"
cd $INSTALL_DIR

# 5. 安装/配置 Nginx
echo "🌐 配置 Nginx..."
if ! command -v nginx &> /dev/null; then
    yum install -y nginx 2>/dev/null || apt-get install -y nginx 2>/dev/null
fi
cp $INSTALL_DIR/nginx.conf /etc/nginx/conf.d/ucloud-geo.conf
# 删除可能冲突的 default server
rm -f /etc/nginx/sites-enabled/default 2>/dev/null
# 修改 nginx.conf 中的 server 配置，确保没有冲突
if grep -q "default_server" /etc/nginx/nginx.conf; then
    sed -i 's/default_server//g' /etc/nginx/nginx.conf
fi
nginx -t 2>/dev/null && echo "✅ Nginx 配置验证通过"
systemctl enable nginx
systemctl restart nginx

# 6. 配置 systemd 服务
echo "⚡ 配置 systemd 服务..."
cp $INSTALL_DIR/ucloud-geo.service /etc/systemd/system/
# 更新 WorkingDirectory
sed -i "s|/opt/ucloud-geo-eval|$INSTALL_DIR|g" /etc/systemd/system/ucloud-geo.service
systemctl daemon-reload
systemctl enable ucloud-geo
systemctl restart ucloud-geo

# 7. 等待服务启动
sleep 3
STATUS=$(systemctl is-active ucloud-geo)

echo ""
echo "========================================="
if [ "$STATUS" = "active" ]; then
    echo "  ✅ 部署成功！"
else
    echo "  ⚠️ 服务状态: $STATUS"
    echo "  查看日志: journalctl -u ucloud-geo -n 50"
fi
echo "========================================="
echo ""
echo "  🌐 访问地址: http://$(hostname -I | awk '{print $1}')/"
echo "  📖 API文档:  http://$(hostname -I | awk '{print $1}')/api/docs"
echo ""
echo "  首次使用请访问 设置页面 配置 API Keys"
echo ""
