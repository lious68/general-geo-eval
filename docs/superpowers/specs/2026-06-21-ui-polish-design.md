# UI 精修设计方案

> 日期：2026-06-21
> 范围：UCloud GEO 评估系统前端（Vue 3 + Element Plus + ECharts）
> 目标：精修现有企业仪表盘观感，统一配色/字号/间距/圆角，emoji 全量替换为 Element Plus 图标，删除脚手架死代码。不动业务逻辑、不重构结构。

## 背景

当前前端存在三类观感问题：

1. **脚手架死代码**：`src/style.css`（Vite 默认紫色主题，56px h1，`#app` 固定 1126px 居中）从未被任何文件 import；`src/components/HelloWorld.vue`、`src/assets/{hero.png,vite.svg,vue.svg}` 同样未引用。
2. **配色/字号分散**：各页面硬编码 `#1a1a2e`(16处)、`#409eff`(12处)、`#ebeef5`、`#0f172a`、`#64748b` 等；`CitationSources` 页标题 28px/800 与其余页面 22px 不一致。
3. **Emoji 渲染不一致**：37 处 emoji 散布于页标题、指标卡、表头 ⓘ、按钮，跨平台显示差异大。

## 设计原则

- **精修现状**：保留深色侧栏 + 浅色内容的企业仪表盘观感，不引入新设计语言。
- **全局变量化**：在 `App.vue` 全局样式中定义 CSS 变量，主色 `#409eff`、文本 `#1a1a2e/#666`、边框 `#ebeef5`、页背景 `#f0f2f5`、圆角 `10px`、页标题 `22px`、小标题 `16px`。
- **Emoji → 图标**：全部替换为已全局注册的 `@element-plus/icons-vue`，颜色随主题。
- **重点页精修**：Dashboard（指标卡/表格/图表）、Login、App 侧边栏；其余页面仅统一标题/图标/间距/圆角。

## 详细方案

### 1. 全局基础（App.vue）

- 删除 `src/style.css`、`src/components/HelloWorld.vue`、`src/assets/{hero.png,vite.svg,vue.svg}`。
- 在 `App.vue` `<style>`（全局）顶部新增 `:root` 变量：主色、文本三档、边框、背景、卡背景、圆角两档、标题/小标题字号、标准间距、成功/警告/危险色。
- `body`、`.main-content`、`.page-title`、`.section-title` 改用变量。

### 2. Emoji → 图标映射

| Emoji | 图标 | 用途 |
|---|---|---|
| 🎯 | Aim | logo / 首次提示 |
| 📊 | DataAnalysis | 仪表盘页标题 |
| 📈 | TrendCharts | 趋势对比 |
| 🚀 | Promotion | 执行评测 / 运行指示 |
| 🕐 | Clock | 历史评测 |
| 🔗 | Link | 引用源 |
| 📝 | Document | 问题管理 |
| ⚙️ | Setting | 系统设置 |
| 📡 | Aim | 提及率 |
| 🔗 | Link | 引用率 |
| 👍 | Medal | TOP3 推荐率 |
| 💛 | Sunny | 情感值 |
| 🏆 | Trophy | GEO 综合得分 |
| ⓘ | InfoFilled | 公式触发器（表头/卡片） |
| 📋 | View | 查看明细 |
| 🔄 | Refresh | 重算评分 |
| ➕ | Plus | 添加 |
| 📥 | Upload | 导入结果 |
| ⬇ | Download | 下载配置 |
| 🌐 | Monitor | WebChat 模式 |
| ⚠️ | Warn | 错误/警告提示 |
| 📎 | Paperclip | 引用详情标题 |
| 🔑 | Key | API Key |
| ⚖️ | Histogram | 评分权重 |
| 👥 | User | 用户管理 |

### 3. Dashboard 精修

- 指标卡：图标染对应主色，数值 28px 加粗，进度条保留，卡片圆角 10px、hover 微抬升。
- 渠道表格：表头 ⓘ 改 `InfoFilled`，得分高/低绿红保持。
- 下钻抽屉：状态标签 emoji 全换图标，预览/展开交互保留。
- 图表区四块卡片统一圆角与间距。

### 4. Login + 侧边栏精修

- Login：标题 🎯→`Aim`，卡片圆角 16px 保留，配色统一。
- 侧边栏：logo 🎯→`Aim`、🚀 运行指示→`Promotion`、🌐 WebChat→`Monitor`、⚠️→`Warn`；菜单 hover/active 精修。

### 5. 其余页面统一

History / CitationSources / Questions / Settings / TaskList / TaskDetail：
- 页标题 emoji→图标、`page-title` 统一 22px（CitationSources 由 28px 降为 22px，保留副标题）。
- 间距/圆角对齐变量。
- 按钮内 emoji→图标。
- 不改 props/store/router/接口。

## 验证

- `npm run build` 无报错。
- 不启动 dev server、不截图，交付源码后用户自行 `npm run dev` 预览。

## 风险

- 纯样式 + 图标替换，不动业务逻辑。
- 图标组件已在 `main.js` 全局注册，模板内直接 `<el-icon><Xxx/></el-icon>` 即可。
