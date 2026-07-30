# 监控与故障处理 Runbook

## 必须可见的指标

| 指标 | 告警条件 | 处置 |
|---|---|---|
| Funnel API `/health/live` | UptimeRobot 连续检查非 200 | 检查 Funnel、网络和 API |
| API `/health/ready` | 非 200 | 停止新写入，检查数据库 |
| Watchdog heartbeat | API、Redis 或任一 Worker 心跳失败 | 修复目标进程，不清空队列 |
| 队列等待 | 评分/导出超过 15 分钟，维护超过 2 分钟 | 检查消费者，不盲目扩大并发 |
| 失败率 | 15 分钟至少 10 个终态任务且失败率达到 10% | 按稳定错误分类排查 |
| 数据库/Storage 容量 | 70% 提醒，85% 阻断 | 保持写入门禁，不自动清理 |

## 本机健康检查

执行终端：本机项目根目录。
预期结果：`launchd`、Redis、API、Tailscale Funnel 和三个 Worker 全部可见。
安全回传：固定通过标记、Worker 名称和队列计数。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/verify-runtime.sh
cd backend
../.venv/bin/celery \
  -A app.workers.celery_app:celery_app \
  inspect ping \
  --timeout 10
../.venv/bin/celery \
  -A app.workers.celery_app:celery_app \
  inspect active \
  --timeout 10
../.venv/bin/celery \
  -A app.workers.celery_app:celery_app \
  inspect reserved \
  --timeout 10
```

验收结束时 active、reserved、三个队列、`unacked`、`unacked_index` 和数据库 running
全部为 0。

## UptimeRobot

配置两个免费监控：

1. HTTP 监控：正式 Funnel 的 `/health/ready`，5 分钟间隔；
2. Heartbeat 监控：`infra/local/watchdog.sh` 每 60 秒在 API、Redis 和三个 Worker
   全部健康时发送一次。

Heartbeat URL 只保存在 `.env.stage14-production`，不得写入仓库或聊天。

## 告警验收

执行位置：UptimeRobot 与本机终端。
前置条件：没有真实业务任务；队列、active、reserved 和 running 均为 0。
预期结果：停止导出 Worker 后 heartbeat 中断并实际收到告警；恢复同一 Worker 后收到
恢复通知。Redis 不清空，评分与维护 Worker 始终在线。

固定步骤：

1. 记录全部健康状态和队列为 0；
2. `launchctl bootout gui/$UID ~/Library/LaunchAgents/com.paper-grading.export.plist`；
3. 等待 UptimeRobot heartbeat 告警并确认实际收到；
4. `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.paper-grading.export.plist`；
5. 确认 `exports@` 恢复、队列仍为 0，并收到恢复通知。

只看到 UptimeRobot 配置不算通过。安全回传只记录触发时间、是否收到告警、恢复时间和
是否收到恢复通知。

## 等待、失败率与容量

继续使用 Supabase SQL Editor 只读查询聚合等待时间、失败率、容量和 running 数量。
不得返回行级论文、反馈、对象路径或用户数据。

## 故障分流

| 现象 | 首查 | 禁止动作 |
|---|---|---|
| 外网 API 不可达 | Mac 网络、Tailscale LaunchAgent、Funnel 状态 | 不直接开放 8000 端口 |
| API ready 失败 | 数据库入口、连接池、迁移 revision | 不把临时 IP 端口当固定入口 |
| 队列增长 | Worker 心跳、路由和租约 | 不清空 Redis |
| 模型失败 | 错误分类、供应商状态、是否已发送 | 不自动重试付费请求 |
| 导出失败 | export Worker、最小角色、Storage 配额 | 不改用 API 数据库角色 |
| 容量告警 | 权威数据库与 Storage 用量 | 不自动启用清理 |
| 疑似泄密 | 停服务、轮换密钥、保全脱敏日志 | 不在聊天粘贴密钥 |

## 事件记录

只记录时间、Git SHA、Sites 版本、进程、revision、稳定错误分类、计数和处置。禁止记录
Token、密码、API Key、论文内容、Storage 对象路径、签名 URL、Tailscale 登录链接或
模型原始响应。
