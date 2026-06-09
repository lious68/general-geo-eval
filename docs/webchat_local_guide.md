# WebChat 本地评测使用指南

## 整体架构

```
┌───────────────────── 服务器 (Linux) ──────────────────────┐
│                                                             │
│  Evaluation.vue 前端                                        │
│  ├─ API 模式 → 直接调用模型 API + 联网搜索                   │
│  └─ WebChat 模式 → 下载任务配置 ↓                           │
│                                                             │
│                                    ┌─ 导入结果 ← 本地 .json  │
│                                    └─ Dashboard 展示结果      │
└─────────────────────────────────────────────────────────────┘
                              │
                    下载 task_config.json
                              │
                              ▼
┌───────────────────── 本地电脑 (Win10 / Mac) ───────────────┐
│                                                             │
│  python scripts/local_webchat_runner.py                     │
│    --config task_config.json --headed                       │
│                                                             │
│  → 弹出浏览器窗口（人可手动处理验证码/登录）                  │
│  → 自动提问 → 等待回复 → 分析 → 评分                        │
│  → 输出: output/webchat_评测_20260608_143022.json          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                    上传 .json 到服务器前端
                              │
                              ▼
                    服务器导入 → Dashboard 展示
```

## 使用流程

### 第一步：在服务器上选择 WebChat 评测

1. 登录服务器前端，进入「执行评测」页面
2. 选择「🌐 WebChat 模式」
3. 勾选要评测的模型（需已登录，显示「✓ 已登录」）
4. 选择品类筛选（可选）
5. 调整请求间隔（建议 8 秒以上）
6. 点击 **「下载任务配置」** → 获得 `webchat_task_XXX.json`

### 第二步：在本地电脑上运行评测

将 `webchat_task_XXX.json` 传到本地电脑后，有三种运行方式：

#### 方式 1：从配置文件运行（推荐）

```bash
# 显示浏览器窗口（可手动处理验证码/登录）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json --headed

# 后台运行（不显示窗口）
python scripts/local_webchat_runner.py --config webchat_task_XXX.json
```

#### 方式 2：交互式引导（新手友好）

```bash
# 无参数启动，进入交互式配置引导
python scripts/webchat_run.py

# 或显式
python scripts/webchat_run.py --interactive
```

交互式会逐步引导选择：
- 模型 → 品类 → 延迟 → 输出路径 → 是否显示浏览器 → 确认执行

#### 方式 3：手动指定参数

```bash
# Windows 快捷启动
scripts\run_webchat.bat kimi headed

# Mac/Linux
python scripts/local_webchat_runner.py --models kimi ernie --headed --delay 10
python scripts/local_webchat_runner.py --models kimi --categories 云数据库
```

### 第三步：处理验证码/登录

使用 `--headed` 参数时，浏览器会弹出窗口。运行过程中：
- 如果需要登录 → 在浏览器窗口中手动登录
- 如果出现验证码 → 在浏览器窗口中手动完成验证
- 登录状态会自动保存，下次运行无需重复登录

### 第四步：上传结果到服务器

评测完成后，会在 `output/` 目录生成结果文件：
```
output/webchat_评测_20260608_143022.json
```

1. 将此文件传到服务器
2. 在服务器前端「执行评测」页面，找到「导入本地 WebChat 结果」区域
3. 拖拽或点击上传 .json 文件
4. 导入成功后，点击「查看结果 →」跳转到 Dashboard

## 命令参考

```bash
# 从服务器下载的任务配置运行
python scripts/local_webchat_runner.py --config task.json

# 从服务器下载的任务配置 + 显示浏览器
python scripts/local_webchat_runner.py --config task.json --headed

# 交互式配置引导
python scripts/webchat_run.py

# 手动指定模型
python scripts/local_webchat_runner.py --models kimi ernie doubao

# 指定品类
python scripts/local_webchat_runner.py --models kimi --categories 云数据库

# 指定输出路径
python scripts/local_webchat_runner.py --models kimi --output results/kimi.json

# 后台运行（不显示浏览器）
python scripts/local_webchat_runner.py --models kimi --headless
```

## Windows 快捷启动

```powershell
# 交互式引导
scripts\run_webchat.bat

# 指定模型 + 显示浏览器
scripts\run_webchat.bat kimi headed

# 从配置文件运行
scripts\run_webchat.bat config task.json
```

## Mac/Linux 快捷启动

```bash
# 交互式引导
python scripts/webchat_run.py

# 指定模型 + 显示浏览器
python scripts/webchat_run.py --models kimi ernie

# 从配置文件运行
python scripts/webchat_run.py --config task.json
```
