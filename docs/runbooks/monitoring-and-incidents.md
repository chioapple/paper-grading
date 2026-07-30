# 监控与故障处理 Runbook

## 必须可见的指标

| 指标 | 告警条件 | 处置 |
|---|---|---|
| API `/health/live` | 非 200 | 停止部署，检查进程 |
| API `/health/ready` | 非 200 | 停止写流量，检查数据库 |
| Worker 心跳 | 任一 `grading@`、`maintenance@`、`exports@` 连续两次 60 秒采样缺失 | 停止对应新任务 |
| 队列等待 | 评分/导出最老任务超过 15 分钟、维护任务超过 2 分钟，或队列连续三个 5 分钟采样增长 | 检查消费者，不扩大并发前先确认费用 |
| 失败率 | 15 分钟至少 10 个终态任务且失败率达到 10% | 按安全错误分类排查，不记录模型原文 |
| 数据库/Storage 容量 | 70% 提醒，85% 阻断 | 保持写入门禁，不自动清理 |

## 心跳与队列

执行终端：Render Worker Shell。
前置条件：Shell 已安全注入 `REDIS_URL`，日志脱敏。
预期结果：三个 Worker 都返回 `pong`；验收结束时 active、reserved、三个队列、`unacked` 和 `unacked_index` 全部为 0。
安全回传：Worker 名称和计数，不回传 broker URL 或任务体。

```bash
cd "/opt/render/project/src/backend"
celery -A app.workers.celery_app:celery_app inspect ping --timeout 10
celery -A app.workers.celery_app:celery_app inspect active --timeout 10
celery -A app.workers.celery_app:celery_app inspect reserved --timeout 10
python -c 'import os, redis; r=redis.Redis.from_url(os.environ["REDIS_URL"]); counts={q:r.llen(q) for q in ("paper_grading.grading","paper_grading.maintenance","paper_grading.exports")}; counts["unacked"]=r.hlen("unacked"); counts["unacked_index"]=r.zcard("unacked_index"); print(counts)'
```

## 等待、失败率与容量

执行终端：Supabase SQL Editor，只读执行。
前置条件：选择当前项目；不得添加论文、反馈、对象路径或用户字段。
预期结果：只返回聚合队列等待秒数、15 分钟失败率、容量状态和告警计数；按本 Runbook 阈值判定。
安全回传：队列名、计数、秒数、失败率、资源状态和百分比；不回传行级数据。

```sql
with queue_wait as (
  select 'grading'::text as queue_name, count(*)::bigint as queued,
         coalesce(max(extract(epoch from (now() - available_at))), 0)::bigint
           as oldest_wait_seconds
  from public.grading_job_items where status = 'queued'
  union all
  select 'exports', count(*)::bigint,
         coalesce(max(extract(epoch from (now() - created_at))), 0)::bigint
  from public.exports where status = 'queued'
)
select * from queue_wait order by queue_name;

with recent_terminal as (
  select case when status = 'failed' then 1 else 0 end as failed
  from public.grading_attempts
  where finished_at >= now() - interval '15 minutes'
    and status in ('succeeded', 'needs_review', 'failed')
  union all
  select case when status = 'failed' then 1 else 0 end
  from public.exports
  where finished_at >= now() - interval '15 minutes'
    and status in ('completed', 'failed')
)
select count(*)::bigint as terminal_count,
       coalesce(sum(failed), 0)::bigint as failed_count,
       case when count(*) = 0 then 0
            else round(100.0 * sum(failed) / count(*), 2) end as failure_percent
from recent_terminal;

select resource, enabled,
       case
         when last_error_code is not null then 'unavailable'
         when not enabled then 'disabled'
         when last_used_bytes >= ceil(capacity_bytes * hard_limit_ratio) then 'blocked'
         when last_used_bytes >= ceil(capacity_bytes * warning_ratio) then 'warning'
         else 'ok'
       end as state,
       case when capacity_bytes is null or capacity_bytes = 0 then null
            else round(100.0 * last_used_bytes / capacity_bytes, 2) end
         as used_percent,
       last_checked_at,
       last_error_code
from public.quota_resource_states
order by resource;

select resource, state, count(*)::bigint as alert_count
from public.quota_alerts
where created_at >= now() - interval '15 minutes'
group by resource, state
order by resource, state;

select 'grading' as task_type, count(*)::bigint as running
from public.grading_job_items where status = 'running'
union all
select 'exports', count(*)::bigint
from public.exports where status = 'running';
```

Redis `LLEN` 不包含任务入队时间，因此维护队列的最老等待时长不能由当前 broker 查询证明。上线前必须在不记录任务体的监控平台配置 Celery 事件或等价指标并实际触发告警；取得该外部证据前，本项保持未通过。

## 告警验收

执行终端：监控平台和 Render Dashboard。
前置条件：`paper-grading-export-worker` 队列为 0，active、reserved、`unacked`、`unacked_index` 和数据库 running 都为 0；监控平台已按连续两次 60 秒心跳缺失配置告警和恢复通知。
预期结果：Suspend `paper-grading-export-worker` 后实际收到告警；Resume 后心跳恢复，并实际收到恢复通知。评分与维护 Worker 始终在线，Redis 不清空。
安全回传：告警触发时间、实际收到告警、恢复时间和恢复通知是否收到；不回传接收地址、环境变量或任务内容。

固定步骤：

1. 记录三个 Worker 心跳与全部队列为 0；
2. Suspend `paper-grading-export-worker`；
3. 等待连续两次 60 秒采样缺失并确认实际收到告警；
4. Resume 同一 Worker；
5. 确认 `exports@` 心跳恢复、队列仍为 0，并收到恢复通知。

## 故障分流

| 现象 | 首查 | 禁止动作 |
|---|---|---|
| API ready 失败 | 数据库入口、连接池、迁移 revision | 不把临时 IP 端口当固定入口 |
| 队列增长 | Worker 心跳、队列路由、租约 | 不清空 Redis |
| 模型失败 | 错误分类、供应商状态、是否已发送 | 不自动重试付费请求 |
| 导出失败 | export Worker、最小角色、Storage 配额 | 不改用 API 数据库角色 |
| 容量告警 | 权威数据库与 Storage 用量 | 不自动启用清理 |
| 疑似泄密 | 立即停服务、轮换密钥、保全脱敏日志 | 不在聊天或工单粘贴密钥 |

## Worker 丢失演练

执行终端：独立验收项目的 Render Dashboard、数据库只读终端和浏览器。
前置条件：用户已授权测试写入与可能的模型费用；队列中只有本次无敏感内容夹具；生产环境禁止执行。
预期结果：任务进入 `running` 后停止对应 Worker，重启后由 Redis 重投或数据库租约恢复；最终只有一个有效结果，旧领取令牌不能完成或删除新结果，队列回到 0，失败时进入稳定终态而非永久 `running`。
安全回传：任务类型、状态序列、领取次数、队列计数和通过/失败；不回传任务 ID、论文、对象路径、签名 URL或模型响应。

演练分别覆盖评分队列和导出队列。维护 Worker 不共享评分执行槽；停止其中一个时，另一个心跳必须继续存在。不得用 `FLUSHALL`、手工改状态或重复创建任务来“恢复”。

## 事件记录

只记录时间、服务、构建 ID、revision、错误分类、计数和处置。禁止记录 Token、密码、API Key、论文内容、Storage 对象路径、签名 URL、模型原始响应。
