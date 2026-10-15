> **2026-10-03 更新：Windows 双机与服务端 WebChat 爬虫已退役。** 以下旧采集步骤仅为历史记录，不再执行；当前流程见 [众包运行说明](docs/CROWD_ONLY.md)。

# UCloud GEO 评估系统 - 服务器部署指南

## 方法1: 从 GitHub 部署（推荐）

### 1. 在本地推送代码到 GitHub
```bash
cd C:\Users\las\Desktop\ucloud-geo-eval

# 登录 GitHub CLI
gh auth login

# 创建仓库并推送
gh repo create ucloud-geo-eval --public --source=. --push
```

或者手动创建：
1. 在 GitHub 网页创建仓库 `ucloud-geo-eval`
2. 然后执行：
```bash
git remote add origin https://github.com/YOUR_USERNAME/ucloud-geo-eval.git
git push -u origin master
```

### 2. 在服务器上部署
```bash
# SSH 连接服务器
ssh root@113.31.106.119

# 克隆代码
cd /opt
git clone https://github.com/YOUR_USERNAME/ucloud-geo-eval.git
cd ucloud-geo-eval

# 构建前端
cd frontend
npm install
npm run build
cd ..

# 运行部署脚本
bash deploy.sh
```

## 方法2: 直接传文件部署

### 1. 在本地打包
```bash
cd C:\Users\las\Desktop\ucloud-geo-eval
tar -czf ucloud-geo-eval.tar.gz --exclude=node_modules --exclude=output --exclude=data --exclude=__pycache__ --exclude=.git .
```

### 2. 用 scp 传到服务器
```bash
scp ucloud-geo-eval.tar.gz root@113.31.106.119:/opt/
```

### 3. 在服务器上解压并部署
```bash
ssh root@113.31.106.119
mkdir -p /opt/ucloud-geo-eval
cd /opt/ucloud-geo-eval
tar -xzf /opt/ucloud-geo-eval.tar.gz

# 构建前端
cd frontend && npm install && npm run build && cd ..

# 部署
bash deploy.sh
```

## 部署后配置 API Keys

访问 `http://113.31.106.119/` → 设置页面，填入各模型的 API Key。

## 常用运维命令
```bash
# 查看服务状态
systemctl status ucloud-geo

# 查看实时日志
journalctl -u ucloud-geo -f

# 重启服务
systemctl restart ucloud-geo

# 重启 Nginx
systemctl restart nginx

# 手动启动后端（调试用）
cd /opt/ucloud-geo-eval/backend
PYTHONPATH=/opt/ucloud-geo-eval/backend:/opt/ucloud-geo-eval/core uvicorn app:app --host 0.0.0.0 --port 8000
```
