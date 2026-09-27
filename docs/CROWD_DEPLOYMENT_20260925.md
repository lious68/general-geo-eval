# 众包采集部署记录 · 2026-09-25

状态：两端应用已上线，星图 Skill 已提供下载；星图真实浏览器采集尚待参与者安装并登录后验证。

## 入口

- GEO 管理：http://117.50.195.148/crowd（沿用原管理员登录）
- 准活参与者：https://zhun.ai/geo/index.html
- Skill 下载：https://zhun.ai/geo/geo-crowd.zip

## 已发布内容

GEO 在 `/opt/general-geo-eval` 增量加入 crowd_store、crowd 路由及管理前端。发布使用线上现有源码构建，原有业务代码与 Windows 守护进程保留。

准活新版本：`/opt/youhuo/releases/20260925-geo-crowd`。
上一版本：`/opt/youhuo/releases/20260908-refinement`。
`/opt/youhuo/current` 已切换到新版本。

新增 PostgreSQL 表由应用正常初始化。上线前在独立 `zhun_test` 数据库验证建表、一次性绑定码及撤销，测试数据库随后删除。

## 通信与运行配置

准活 `geo-crowd-tunnel.service` 以 youhuo 身份运行，将 `127.0.0.1:18080` 转发到 GEO `127.0.0.1:8000`，验证固定 SSH 主机密钥。

GEO 专用账号 `geo-crowd-tunnel` 无交互 shell，仅允许到指定服务端口的本地转发。SSH 限制位于 `/etc/ssh/sshd_config.d/60-geo-crowd.conf`。

集成密钥分别保存在 GEO `/etc/geo-crowd.env`、准活 `/etc/youhuo/crowd.env`，root-only，由各自 systemd drop-in 加载。不保存在源码或本文中。

## 备份与回滚依据

两台服务器的备份目录均为 `/var/backups/geo-crowd/20260925-geo-crowd`。

GEO 保存发布前代码/前端 tar 包和 SQLite 一致性备份；准活保存完整 PostgreSQL custom-format dump，已验证归档可读。

应用回滚时，准活将 current 切回上述上一版本并重启 youhuo；GEO 恢复备份代码/前端并重启 geo-eval。保留新采集数据库和新增 PostgreSQL 表，不用旧数据库覆盖上线后的用户数据。

## 线上验证

- geo-eval、youhuo、geo-crowd-tunnel 均运行正常。
- 隧道内带服务认证的项目查询成功，发布时项目数为 0。
- GEO `/api/health`、`/crowd`、准活首页与采集页返回 200。
- 首页已出现 GEO 采集入口；Skill 在线文件与本地分发包 SHA256 一致。
- 未登录访问准活项目接口和 GEO 管理接口返回 401；未授权调用服务网关返回 401。
- 没有创建生产测试用户、虚构采集样本或收费记录。

下一步由负责人创建首个小批量项目，参与者安装 Skill、绑定设备并在星图浏览器本人登录，验证真实平台的回答和引用采集。
