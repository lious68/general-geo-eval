
## 2026-10-15 IP HTTPS 已启用
- 入口 https://117.50.195.148/；HTTP 页面308到HTTPS；为兼容已安装客户端，HTTP /api/ 暂保留反代，ACME路径保持HTTP可用。不要部署旧nginx模板覆盖SSL。
- Let's Encrypt IP SAN证书，Certbot5.8独立venv /opt/geo-certbot；证书 /etc/letsencrypt/live/geo-ip/{fullchain.pem,privkey.pem}，私钥与ACME账号只在服务器，不提交Git。
- 首证 notAfter=2026-10-21 22:23:08 UTC；IP短期证书须自动续期。
- systemd geo-certbot-renew.timer enabled，每日00/06/12/18点+随机0–15分钟，Persistent=true；service运行 /opt/geo-certbot/bin/certbot renew --quiet --no-random-sleep-on-renew。
- deploy hook /etc/letsencrypt/renewal-hooks/deploy/geo-nginx：nginx -t成功后systemctl reload nginx。
- ACME webroot /var/www/geo-acme；Nginx /etc/nginx/conf.d/geo-eval.conf；原配置备份 /var/backups/geo-crowd/20261015-ip-ssl/geo-eval.conf。
- 已验证：正式IP证书签发；本机curl默认信任验证HTTPS200、HTTP308；服务health正常；certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew 成功；定时器enabled且已手动成功运行service。
- 检查命令：sudo systemctl list-timers geo-certbot-renew.timer；sudo journalctl -u geo-certbot-renew.service；sudo /opt/geo-certbot/bin/certbot certificates。日志 /var/log/letsencrypt/letsencrypt.log。
- 未配置邮件告警/账户邮箱；续期由服务器执行，不依赖Codex会话或桌面定时任务。80端口验证路径与443须保持可达。
- C:/Users/las/Codex/geo_ssl_issue.sh、geo_ssl_enable.sh、geo_ssl_step.py 为执行记录。初次Windows行尾导致证书名含CR，已规范archive/live/renewal及软链，续期模拟成功。上传shell必须转LF。

### 仓库中的配置副本
`deploy/ip-https/` 保存线上 Nginx、systemd service/timer 和续期 deploy hook，不包含证书、私钥或 ACME 账号。先签发证书，再安装配置并执行 `sudo nginx -t`、`sudo systemctl daemon-reload`、`sudo systemctl enable --now geo-certbot-renew.timer`。证书尚未签发时不要直接启用该 Nginx 配置。服务器已完成安装，无需重复申请。
