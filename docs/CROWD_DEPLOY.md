# 三端接入与验证

## 配置

GEO 后端新增环境变量（不写入仓库）：

```
GEO_CROWD_SECRET=<至少32字符的独立随机集成密钥>
GEO_CROWD_DB=/opt/general-geo-eval/data/crowd.db
```

准活服务新增：

```
GEO_CROWD_SECRET=<与GEO一致>
GEO_CROWD_URL=https://<GEO的TLS入口>
```

如通过 SSH 隧道连接 GEO，准活可使用 `http://127.0.0.1:<隧道端口>`。不支持公网明文 HTTP。隧道需由系统服务维持，固定远端主机密钥，使用只允许转发至 GEO 本地端口的专用 SSH 账号/密钥。不要复用管理员密码常驻隧道。

服务未配置密钥时，网关拒绝所有访问；准活展示服务未配置，不回落到旧爬虫。管理员仍可保存项目。

## 发布顺序

1. 备份 GEO 数据目录、准活 PostgreSQL 和现有发布目录；记录当前版本。不要覆盖现有 `.env`。
2. GEO 安装新增模块及 app.py，构建 frontend；在服务配置中注入密钥，重启并检查健康接口。
3. 准活创建独立 release，加入 geo_crowd.py、server.py 和 public/geo；配置安全服务地址。现有 init() 会执行新增表的幂等建表语句。
   发布前在 GEO 仓库运行 `python scripts/package_crowd_skill.py --zhun-root <准活仓库路径>`，将生成的 `public/geo/geo-crowd.zip` 一同带入准活 release。ZIP 为生成产物，不提交 Git。
4. 在测试数据库验证 PostgreSQL 建表、绑定及并发兑换，再切换生产 current 链接，重启 youhuo。已有人工付款流程不变。
5. Nginx 两端请求体限制至少 6 MB；本应用单份原始样本限制 5 MB，准活已有请求体限制也继续生效。关闭对 Authorization 与绑定码的请求体日志。
6. 校验 GEO `/api/health`、管理员 `/crowd`、准活 `/geo/index.html`；未经认证访问管理接口必须失败。
7. 安装分发包中的 geo-crowd 目录到星图实际支持的 Skill 位置。安装方式需以客户端能力为准，没有实现虚构的一键安装协议。
8. 准活用户报名并绑定，选 1 道真实问题，核对问题/回答/引用/条件/截图、提交回执与验收结果，完成后再扩容。

## 测试命令

GEO 仓库：`python -m pytest tests -q`；前端目录：`npm ci` 后 `npm run build`。

准活仓库：`python -m unittest discover -p 'test_*.py' -q`。

跨仓库测试默认查找 GEO 同级的 youhuo，也可指定 `ZHUN_SOURCE_ROOT`。使用临时数据库和回环 HTTP，不触碰生产账号、AI 平台或收费接口。测试会跳过不存在的准活仓库，发布检查必须确认该项实际执行。

## 回滚

暂停 GEO 项目分配；准活切回上一 release，GEO 回滚代码/前端。保留新增数据表和 crowd.db 以供核对，不删除已提交的原始证据。旧 Windows 守护进程未修改。

## 第一版限制

- 验收人工执行；无自动评分、结算、自动通知和无人值守唤醒。
- 单次后台查询返回全部样本，适合小规模试点；规模化前增加分页、对象存储与保留策略。
- 图片签名/格式与文本字段校验不代表证据真实性验证。
- 标准 Skill 已提供，星图原生运行时和第三方 AI 平台未实机验收。
- SQLite 通过事务保证分题原子性；使用单机持久化目录，不支持多实例分散本地数据库部署。
