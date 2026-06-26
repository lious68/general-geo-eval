# 我们如何用 Agent + UCloud CLI 从零搭一套真实 WebChat 的 GEO 评估系统

> 这是一篇实操复盘。记录我们怎么用 Claude Code（agent）写完一套 GEO（生成式引擎优化，Generative Engine Optimization）评估系统的代码，再用 UCloud CLI 把它部署到云上、让全世界能访问——以及中间踩过的每一个坑。
>
> 如果你也想用 agent 写代码、用 CLI 把服务上线，这篇能当脚手架。

---

## 一、先说结论：为什么市面上大多数 GEO 评估方案不能用

GEO 评估要回答的问题是：**当用户在 DeepSeek、Kimi、文心一言、通义、豆包这些 AI 里提问时，我家品牌（我们测的是 UCloud）有没有被提到、被排在第几、引用了什么来源、情感正面还是负面。**

听起来简单，但市面上很多方案做不到，根本原因是——**它们用的是 API 模拟，不是真实 WebChat。**

### API 模拟 vs 真实 WebChat：差在哪里

你在网上能找到的「大模型评测 SDK」大多是这么做的：调厂商的开放 API（DeepSeek API、Kimi API、智谱 GLM API……），发一个问题，拿回一段文本，然后数品牌词出现几次。

**这条路对 GEO 是错的**，原因有三：

1. **API 没有联网搜索，也就没有「引用源」。** GEO 最核心的指标之一是引用率——模型回答里有没有给出 UCloud 官网链接、有没有引用知乎/CSDN/雪球上的第三方内容。API 返回的是纯文本生成，**不带搜索、不带引用 URL**。你用 API 测，引用率永远是 0，这个指标直接废掉。

2. **API 的回答和用户在网页里看到的回答不一样。** 同一个问题，你在 kimi.com 网页版问（带联网搜索）和调 API 问（纯模型生成），答案是两回事。用户实际感知的是**网页版的回答**，GEO 评的也应该是网页版。API 测的是「模型能力」，不是「用户实际看到的内容」。

3. **API 测不出排名和推荐强度。** 模型在网页里回答「云服务器选哪家」时，会把几个品牌列出来排序（UCloud 排第几？是「强烈推荐」还是「可以考虑」？）。这种推荐结构是 WebChat 界面渲染出来的，API 的纯文本回包里没有稳定的结构化「品牌推荐列表」。

**所以只有一条路：用真实浏览器（Playwright）去模拟用户在网页里提问、等回答、把渲染出来的完整回答（含引用区）抓回来。** 这就是我们这套系统做的事——headless 都不行，必须 **headed（带界面的真实浏览器）**，因为有些模型会弹验证码、会检测自动化浏览器，headless 直接被拦。

这套「真实 WebChat」路线才是 GEO 评估该有的样子。下面讲我们怎么搭的。

---

## 二、系统架构：双机云联动

为什么是两台机器而不是一台？因为 headed 浏览器跑评测这件事，和后端 API 服务这件事，**对运行环境的要求完全冲突**：

- **后端**（FastAPI + 数据库 + Vue 前端）：Linux 上跑最舒服，systemd 守护、nginx 反代，标准 Web 服务那套。
- **WebChat 评测**（Playwright headed）：需要一台**有桌面**的 Windows，因为要开带界面的 Chrome、要能看见验证码、要登录模型账号。Linux 的 headless 服务器跑不了 headed 浏览器（xvfb 假桌面绕不过部分反爬）。

所以架构是：

```
┌─────────────────────────┐         webhook          ┌──────────────────────────┐
│  Linux 后端 (Ubuntu)     │  ──────────────────────> │  Win 守护进程 (Server 2022)│
│  - FastAPI :8000         │   推送批次配置            │  - aiohttp :8443          │
│  - sqlite + Vue 前端     │                          │  - Playwright headed      │
│  - nginx :80 (公网入口)  │ <──────────────────────  │  - 5 模型登录态           │
│  - 建批次/出分/看板      │   回传评测结果            │  - 任务计划 AtLogOn 自启  │
└─────────────────────────┘                          └──────────────────────────┘
        公网 EIP                                                  仅内网/RDP
   全世界访问 dashboard                                  人在 RDP 里才跑（decision-a）
```

**一次完整评测的流程：**

1. 你在 dashboard 上建一个批次（选模型、选题集）→ 后端生成配置，存数据库。
2. 后端 webhook 把批次配置推给 Win 守护进程。
3. Win 守护进程逐模型探登录态（有没有效的登录 cookie）。
4. **人在场确认**——守护进程弹一个确认页，你在 RDP 里点「开始评测」。这一步是故意设计的：headed 评测要人盯着验证码，机器不能自己闷头跑。
5. 守护进程调 runner，Playwright 开浏览器、逐题提问、等回答、抓回答正文（含引用 URL）。
6. 每模型跑 20 题/小时后自动休 1 小时（防封号）。
7. 跑完结果自动回传后端，后端算分、出 GEO 看板。

**关键约束（不可违反）：**
- 评测必须 headed，验证码才看得见能过；
- 每模型 20 题/小时后休 1 小时；
- 「人在才跑」——守护进程只在 Administrator 登录 RDP 时才工作，人不在批次留着，下次登录自动续；
- 含密钥的 `.env` 绝不进 GitHub。

---

## 三、四大指标怎么算（这是 GEO 的灵魂）

GEO 综合分 = **提及率×0.45 + 引用率×0.25 + TOP3推荐率×0.20 + 情感值×0.10**，再 ×100。四个指标各有口径，最容易踩坑的是「分母到底用谁」。

### 一个必须先讲清的区分：自然问题 vs 引导型问题

- **自然问题**：题干里**不出现**品牌词的提问，比如「云服务器选哪家」「海外云主机怎么选」。这是真实用户会问的。
- **引导型问题**：题干里直接点了品牌，比如「UCloud 云主机怎么样」。这是送分题——题干都点名了，模型当然会提。

**提及率和 TOP3 推荐率的分母只用自然问题，不用引导型。** 否则引导型送分会把分数虚高吹起来（我们联调时 kimi 一度虚高到 75 分，真实才 18 分，就是 fallback 逻辑把引导型当自然问题算进去了）。

判定规则（`is_natural_question`）：`分类 != "引导型"` **且** 题干不含任何品牌主词/别名（UCloud 默认档案里是 `UCloud` / `优刻得`）。

引用率和情感值的分母则是**全部有效问题**（含引导型），因为这两个指标和「题干有没有点名品牌」无关——模型引用了 UCloud 官网、或对 UCloud 的描述情感正面，即使题干没点名也算。

### 指标 1：提及率（coverage_rate）

```
提及率 = UCloud 被提及的自然问题数 / 自然问题总数
```

「被提及」= 响应正文里用品牌关键词（`UCloud`/`优刻得`/产品名/别名）正则命中 ≥1 次。ASCII 关键词大小写不敏感，中文大小写敏感。

### 指标 2：引用率（citation_rate）——重点解释「要不要链接」

> 这是我之前反复被问、也最容易误解的指标：**引用率是不是一定要引用链接才算？**
>
> **答案：不一定。引用率有 3 条有效路径，只有其中 2 条需要链接，第 1 条不需要。**

```
引用率 = 含「有效引用」的有效问题数 / 全部有效问题数
```

「有效引用」有 **3 条路径**，任一命中即算该问题有有效引用：

| 路径 | 要不要链接 | 判定 |
|---|---|---|
| ① 参考措辞 | **不需要链接** | 响应里出现「据UCloud」「UCloud官网」「UCloud数据显示」「根据UCloud」「UCloud报告」「UCloud官方」「UCloud白皮书」等措辞 |
| ② UCloud 官方 URL | 需要链接 | 响应里出现 UCloud 官方域名链接（ucloud.cn / ucloud.com / ucloudstack.com，含 docs.ucloud.cn 等子域） |
| ③ 第三方来源 URL | 需要链接 | 回答**提及了 UCloud** 且引用了第三方域名（知乎/CSDN/雪球/百度百科等 26 个域名）的链接，且该链接前后 ±180 字上下文里含品牌词 |

**为什么路径①不要链接也算？** 因为「据UCloud……」这种措辞本身就是模型在「引用」UCloud 的信息来源——它用文字而不是 URL 表达了引用关系，语义上等同。所以只要正文出现这些参考措辞，就算有效引用。

**为什么路径③要加「提及 UCloud + 上下文相关」两个条件？** 因为一个回答里出现一个知乎链接，不代表这个链接是「为 UCloud 做背书」的——它可能和 UCloud 毫无关系。只有「在讨论 UCloud 的语境下」引用的第三方来源才算。我们用 ±180 字符窗口检查上下文是否含品牌词来判定。

> 一个细节坑：UCloud 官方 URL 模式只匹配三个**根域**（ucloud.cn / ucloud.com / ucloudstack.com），但 `docs.ucloud.cn`、`astraflow.ucloud.cn` 这种**子域**匹配不到。所以我们额外维护了一个 `all_cited_urls` 全量 URL 列表，用子串匹配补漏这些子域——否则引用率会少算。

### 指标 3：TOP3 推荐率（recommendation_rate）

```
TOP3 推荐率 = UCloud 排名 ≤ 3 的自然问题数 / 自然问题总数
```

**排名怎么算**：若 UCloud 未被提及 → 无排名。否则收集 UCloud 首次出现位置 + 各竞品首次出现位置，按位置升序排序，UCloud 的 1-indexed 名次就是它的排名。`rank=1` 表示 UCloud 出现在所有竞品之前。

还有衍生指标：**强推荐率**（响应里出现「强烈推荐」「首选」「最佳选择」「首推」「不二之选」等）/ **中等推荐率**（「推荐」「建议」「可以考虑」「值得选择」等）。判定时取首次提及前后 150~300 字的扩展上下文按优先级匹配。

### 指标 4：情感值（sentiment_score）

```
情感值 = 所有有效响应 sentiment_score 的平均
```

这里我们没用手写关键词词典，用的是 **SnowNLP**（基于朴素贝叶斯的中文情感库）。取 UCloud 前 3 次提及，各取前后 100~200 字上下文，每段打分（0~1）取平均。阈值：`>0.6 正面`、`<0.4 负面`、之间中性。UCloud 未被提及时记 0.5（中性）。snownlp 导入失败时回退到关键词词典（正面词 +0.05、负面词 -0.05）。

---

## 四、引用源数据：从哪捞、怎么算、后续有什么用

引用源不只是算引用率的中间产物，它本身就是一座金矿。

### 数据从哪捞出来

一条模型响应进来，分析器干两件事，产出两个列表：

- **`citations`（严格列表）**——「算品牌引用」的条目，4 类：
  1. 正文 URL 命中 UCloud 官方根域正则 → 标记官方
  2. 参考措辞（「据UCloud」等）子串匹配 → 标记官方（这就是路径①，不要 URL）
  3. 第三方 URL + 提及 UCloud + ±180 字上下文含品牌词 → 标记非官方
  4. 模型 API 返回的 `search_results` 里的 URL → 全部入，不查上下文（因为搜索结果本身就是模型来源）

- **`all_cited_urls`（宽松列表）**——响应里出现的**所有** URL，用通用 URL 正则提取，每条带 `source_channel`（来源渠道，如「UCloud官网」「知乎」「CSDN」「雪球」「百度百科」）。

两个列表都序列化成 JSON 存进数据库的 `analysis_results` 表。

URL 提取正则长这样（很朴素，但够用）：
```python
url_pattern = re.compile(r'https?://[^\s<>"\')\]，。、；：！？】}]+')
```

### 一个聪明的设计：读侧动态重算

我们有两处算指标：**计算侧**（runner 跑完即算，存进 `geo_scores` 表）和**读侧**（dashboard 实时从 `analysis_results` 表读 JSON **重新算**一遍引用率）。

为什么要读侧重算？因为引用判定规则会迭代（比如往 `THIRD_PARTY_CITATION_DOMAINS` 加一个新域名、或调整参考措辞词表）。读侧重算意味着**改了规则，历史所有 run 的引用率自动跟着更新**，不用重跑分析。原始的引用源 JSON 一直在表里，是可回溯的。

（注意：任务级分数是直接读 `geo_scores` 表不重算的，所以改了规则要让任务级分数更新，得重跑任务或删任务级分数重存。这是个小坑。）

### 引用源对后续的 6 层价值

1. **来源渠道聚类**——每条 URL 带 `source_channel`，能算「模型回答 UCloud 时主要从官网、还是从知乎/CSDN/雪球拿信息」。官方占比高说明 UCloud 官方内容被模型信任；第三方占比高说明口碑传播广但官方 SEO 可能不够。
2. **官方域名细分**——ucloud.cn（官网）/ ucloud.com（国际站）/ ucloudstack.com（私有云）/ docs 等子域各被引多少，知道该重点优化哪个站点。
3. **第三方口碑溯源**——路径③的引用能定位「模型在讨论 UCloud 时参考了哪些第三方页面」。被反复引用的页面就是 UCloud 在 AI 回答里的「信息源头」，那个页面的内容质量直接影响模型对 UCloud 的描述——这是**可优化的外部内容资产**。
4. **引用与提及/推荐的相关性**——「被提及但无引用」的问题意味着模型提了 UCloud 却没给来源，可能是凭训练记忆瞎说，可信度低，要重点关注。
5. **竞品对比上下文**——配合竞品提及数据，看 UCloud 和竞品在哪些来源上被一起讨论、谁排前面。
6. **历史趋势与规则迭代**——长期累积的引用源数据能做时间序列：某第三方站点被引频率上升还是下降，反映 UCloud 在该平台的内容热度变化。

---

## 五、踩过的坑（精选有代表性的）

整个过程踩了一堆坑，挑几个最能给人启发的讲。

### 坑 1：PowerShell 5.1 的 UTF-8 BOM 把守护进程搞崩了

Win 守护进程的配置文件 `win_daemon.env` 是用 PowerShell `Set-Content -Encoding UTF8` 写的。PowerShell 5.1 的「UTF8」**带 BOM**（文件头 `EF BB BF`）。python-dotenv 读这个文件时，把第一行 key 读成了 `﻿BACKEND_URL`（前面多了个 BOM 字符），于是 `os.environ["BACKEND_URL"]` 直接 `KeyError`，守护进程一启动就 exit 1。

更要命的是任务计划用 `pythonw.exe`（无控制台）跑，崩了**没有任何报错输出**，只表现为 8443 端口连不上、任务计划 LastTaskResult=1。排查了很久才发现是 BOM。

**修法**：写任何会被 Python dotenv/configparser 读的文件，都用无 BOM 的 UTF-8：
```powershell
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
```
调试时改用 `python.exe`（非 pythonw）前台跑，才能抓到 Traceback。

### 坑 2：Windows 服务跑在 session 0，headed 浏览器看不见

一开始想用 NSSM 把守护进程注册成 Windows 服务自启。结果服务跑在 **session 0**（无桌面的隔离会话），headed 浏览器和验证码在 session 0 里根本看不见 → 评测全废。

**修法**：不用 NSSM，改用**任务计划 + AtLogOn 触发**——只在 Administrator 登录 RDP（交互会话）时才启动守护进程。这恰好和我们「人在才跑」的设计一拍即合：人登录 RDP = 人在场 = 可以跑 headed 评测。人一退出，守护进程也停，批次留着下次登录续。

### 坑 3：文心一言迁域名，旧选择器全失效

文心一言 2026 年把域名从 `yiyan.baidu.com` 迁到了 `chat.baidu.com`，整个前端 DOM 重写。我们 ErnieWebChatClient 的选择器全失效了——输入框找不到、回答区提取不到。

最隐蔽的一个：旧响应选择器是 `[class*='answerBox']`（**驼峰**），但新页面的类名是 `answer-box`（**短横线**），驼峰匹配直接命中 0 个。然后又试 `[class*='answer']`（小写），这个**过宽**了——`.last` 命中了页面底部一个空的 `answer-tips-wrapper`（innerText 为空），导致「等回答完成」的死循环（取空文本恒不满足条件，转满 180 秒超时），提取也返回空字符串。表现就是：卡在「回答问题后」没有任何提取动作。

**修法**：写了个诊断脚本，发一道题后 dump 主区所有可见元素（排除侧边栏、按文本长度倒序），看真实的 class 和父链。定位到正确容器是 `.answer-box.last-answer-box`，改成精确类名选择器，三处引用统一抽成类属性避免散落硬编码再次漂移。还发现 `answer-box.innerText` 会混入兄弟 UI 元素的文本（「深度思考」「对话支持收藏啦」「追问建议」），提取时优先取内容子区 `.chat-search-answer-generate` 去掉这些 chrome。

**教训**：别靠猜百度/大厂的 CSS 类名——它们用哈希化类名，经常变。写诊断脚本看真实 DOM 才靠谱。

### 坑 4：UCloud CLI 的 OAuth 在非交互环境跑不了

这是部署阶段最痛的一个。UCloud CLI 的 `ucloud auth login` 需要真正的交互式 TTY 来捕获浏览器回调，agent 的 Bash 工具和 `!` 前缀都不算交互终端 → 报「requires an interactive terminal」。token 过期后非交互环境也续不了。

**修法**：自动化场景用 AK/SK profile：`ucloud config add --profile <name> --public-key ... --private-key ... --active true`。密钥只存在本机 `~/.ucloud/`，命令里不嵌入密钥。

### 坑 5：UCloud 删主机删不掉，因为 profile 默认 Region 是上海

`uhost delete` 内部的预检（describe-by-ID）用的是 **profile 配置的默认 Region/Zone**（OAuth profile 默认常是上海 cn-sh2），而不是命令行传的 `--region`！于是用乌兰察布的主机 ID 在上海查 → 「does not exist」→ 中止，删除请求根本不发。但 `uhost list`/`stop`/`start` 都正常，因为它们尊重 `--region` 参数，唯独 delete 的预检不尊重。

**修法**：先 `ucloud config update --profile default --region cn-wlcb --zone cn-wlcb-01 --project-id <项目ID>` 把默认 region 改对，delete 立即成功。

### 坑 6：Windows Server 镜像创建要 `--hot-plug false`

UCloud 上用 Windows Server 2022 镜像 `uhost create` 会报 `RetCode:8041 UImage do not support hotplug`。Linux/Ubuntu 镜像没这问题。**修法**：创建 Windows 主机时加 `--hot-plug false`。另外 UCloud 乌兰察布没有桌面版 Win11，只有 Windows Server 2008~2022，要桌面体验就用 **Server 2022 带桌面体验**（能 RDP + 跑 Chrome headed + 处理验证码）等效替代。

### 坑 7：乌兰察布机房 pip 被墙

乌兰察布机房访问 PyPI 官方源 SSL EOF（被墙）。装依赖必须用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；Playwright 的 chromium 下载用 `PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`。

---

## 六、核心：怎么用 Agent 写完代码，再用 UCloud CLI 部署上线

这是这篇文章最想教给你的部分。整个工作流是：**Claude Code（agent）写代码 → UCloud CLI 建主机/部署 → 全世界访问**。

### 第 1 步：让 agent 写代码

你不用自己一行行敲。把需求讲清楚，agent 帮你产出代码、写测试、改 bug。我们这套系统从架构到 5 个模型的 WebChat 客户端、到指标计算引擎、到守护进程，绝大部分是 agent 写的。

几个让 agent 高效干活的经验：
- **把约束讲死**。比如「评测必须 headed」「每模型 20 题/小时后休 1 小时」「`.env` 不进 GitHub」——这些硬约束一开始就告诉 agent，写进 CLAUDE.md，它会全程遵守，不用每次重复。
- **让 agent 先读再写**。改一个文件前让它先 Read，匹配现有代码风格（命名、注释密度、惯用法），不要凭空生成格格不入的代码。
- **用诊断脚本辅助调试**。像文心一言迁域名那种「DOM 变了选择器失效」的问题，让 agent 写个一次性诊断脚本 dump 真实 DOM，比让它瞎猜选择器高效十倍。
- **安全约束要明写**。我们有一条铁律：**绝不在说明文字、计划、命令预览、补丁文本或面向用户的摘要里打印、重复或嵌入 UCLOUD_PUBLIC_KEY / UCLOUD_PRIVATE_KEY 或原始密钥材料**。优先用已有 CLI profile。这条写进 agent 的记忆，它就不会把密钥泄露到 commit 或文档里。

### 第 2 步：用 UCloud CLI 准备云资源

代码写完，要上线。UCloud 有官方 CLI（`ucloud`），而且**它是 agent-ready 的**——纯命令行、可脚本化、有清晰的产品子命令，agent 能直接调用完成全部资源操作。

**前置：装 CLI + 配 profile**

macOS / Linux / Windows 分别按架构下载二进制：
```bash
# Linux amd64 为例
curl -o ucloud https://ucloud-infra.cn-bj.ufileos.com/cli/linux_amd64/ucloud
chmod +x ucloud && sudo mv ucloud /usr/local/bin/
ucloud --version
```

配 profile（自动化用 AK/SK，密钥只存本机不进命令历史）：
```bash
ucloud config add \
  --profile my-deploy \
  --public-key YOUR_PUBLIC_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --region cn-wlcb --zone cn-wlcb-01 \
  --project-id org-xxxxxx \
  --active true
```
配完先跑只读命令确认可用：`ucloud region` / `ucloud project list` / `ucloud vpc list`。

**复用现有网络资源**（别重复造）：
```bash
ucloud region                        # 看 region code
ucloud project list                  # 看项目
ucloud vpc list --region cn-wlcb     # 看可复用的 VPC
ucloud subnet list --region cn-wlcb  # 看子网
ucloud firewall list --region cn-wlcb # 看防火墙（乌兰察布默认有「Web服务器推荐」开 22/80/443）
```

**建 Linux 后端主机**（带公网 EIP）：
```bash
ucloud uhost create \
  --region cn-wlcb --zone cn-wlcb-01 --project-id org-xxxxxx \
  --name geo-eval-backend \
  --image-name "Ubuntu 22.04" \
  --cpu 4 --memory-gb 8 \
  --password YourAlphaNum123 \        # 纯字母数字，见坑5
  --vpc-id uvnet-xxxx --subnet-id subnet-xxxx \
  --firewall-id firewall-xxxx \
  --create-eip-line BGP --create-eip-traffic-mode Traffic \
  --bandwidth-mbps 5
```
注意：结尾可能蹦一个 `299 IAM permission error`，**那是 CLI 轮询 describe 时的权限报错，不影响主机创建**，主机照样 Running、EIP 照样绑定，忽略即可。

**建 Windows 守护进程主机**（要加 `--hot-plug false`，见坑6）：
```bash
ucloud uhost create \
  --region cn-wlcb --zone cn-wlcb-01 --project-id org-xxxxxx \
  --name geo-eval-win \
  --image-name "Windows Server 2022" \
  --hot-plug false \                  # Win 镜像必加，否则 8041
  --cpu 4 --memory-gb 8 \
  --password YourAlphaNum123 \
  --vpc-id uvnet-xxxx --subnet-id subnet-xxxx \
  --firewall-id firewall-xxxx \
  --create-eip-line BGP --create-eip-traffic-mode Traffic \
  --bandwidth-mbps 5
```

两台同 VPC，内网互通。Linux 主机 SSH 全程 paramiko 自动化；Windows 主机只能 RDP（22 开但镜像无 sshd、WinRM 开但不响应），所以 Win 上的安装/登录/跑批次得在 RDP 会话里人工做——这恰好符合「人在才跑」的设计。

### 第 3 步：部署应用

**Linux 后端**（标准 Web 服务那套，agent 用 paramiko 全程自动化）：
```bash
# SSH 上去（ubuntu 用户，免密 sudo）
ssh ubuntu@<EIP>
# 拉代码、建 venv、装依赖（清华镜像）、初始化数据库
# 写 systemd geo-eval.service（uvicorn :8000）+ nginx 反代 :80
# systemctl enable --now geo-eval
curl http://<EIP>/api/health   # 200 = 后端就绪
```

**Windows 守护进程**（RDP 里跑安装脚本，无 git/winget 依赖）：
```powershell
# RDP 进 Windows Server 2022，管理员 PowerShell
# 一行式拉安装脚本（PowerShell 多行粘贴会倒序执行，必须一行）
iex (irm "https://raw.githubusercontent.com/<你>/<repo>/master/scripts/win_setup.ps1") `
  -BackendUrl "http://<后端内网IP>" `
  -WebhookSecret "<你的webhook密钥>" `
  -ServicePassword "<后端admin密码>"
# 装完任务计划 WinDaemon 自启（AtLogOn），监听 :8443
# 然后逐个登录 5 个模型（headed 弹 Chrome）
python scripts\setup_webchat_auth.py all
```

### 第 4 步：开放公网、全世界访问

Linux 后端绑了公网 EIP + nginx :80，dashboard 直接 `http://<公网EIP>` 就能访问。乌兰察布机房国内访问延迟低、IP 稳定（我们风控实测 2 题×5 模型，**无验证码、无封号、无限流**，乌兰察布定稿）。

要 HTTPS 就再 `ucloud ucert` 申请证书或绑 ULB。日常管理：`ucloud uhost list/stop/start` 都尊重 `--region` 参数；删主机记得先把 profile 默认 region 改对（见坑5），再 `ucloud uhost delete --uhost-id <id> --region cn-wlcb --zone cn-wlcb-01 --project-id org-xxxxxx --destroy --release-eip`。

### 第 5 步：后续迭代——代码改了怎么同步到云上

这是 agent + CLI 工作流最爽的地方。代码在 GitHub，云上两台主机：

- **Linux 后端**：agent 用 paramiko SSH 上去 `git pull` + `systemctl restart geo-eval`，一条龙。
- **Windows 守护进程**：因为只能 RDP，单文件热更新用 `Invoke-WebRequest raw.githubusercontent.com/<你>/<repo>/master/<path> -OutFile <同路径>` 覆盖单个文件（**别重跑完整 setup，会 wipe 掉登录态**）。改完不用重启，守护进程下次拉批次自然用新代码。

整个循环：**agent 改代码 → push GitHub → CLI/SSH 同步到云 → 验证 → 上线**。从写代码到全世界能访问，中间不需要离开终端、不需要点网页控制台。

---

## 七、收尾：这套工作流带给我们的东西

复盘下来，这套「agent 写代码 + UCloud CLI 部署」的工作流，价值不在某个具体功能，而在三件事：

1. **真实而非模拟**。我们坚持用 headed 浏览器跑真实 WebChat，而不是 API 模拟。这让引用率、排名、推荐强度这些 GEO 的核心指标第一次变得可测、可信。市面上 API 模拟的方案测不出这些，本质上是在测一个用户根本看不到的接口。

2. **agent + CLI 闭环**。从需求到上线，全程在终端里完成：agent 写代码和测试，CLI 建主机和资源，SSH/RDP 部署。没有「写完代码还要去网页控制台点点点」的断点。UCloud CLI 是 agent-ready 的——纯命令行、产品子命令清晰、可脚本化，agent 能直接驱动它完成部署、测试、上线全流程。

3. **指标口径经得起推敲**。每个指标的分母是什么、引用要不要链接、自然问题怎么判定、读侧为什么动态重算——这些都写在代码注释和文档里，可追溯、可复现。GEO 评估最容易糊弄的就是口径，我们选择把它讲透。

如果你也想搭一套自己的 GEO 评估，或者只是想试试「agent 写代码 + CLI 部署」的工作流，希望这篇能帮你少踩几个坑。代码和完整文档都在 GitHub 上，欢迎拿来改。

——代码即部署，部署即上线。让 agent 写代码，让 CLI 把它推到全世界面前。
