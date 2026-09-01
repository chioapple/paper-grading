# 生产冒烟测试 Runbook

## 无写入检查

执行终端：本机项目根目录。
前置条件：设置正式 HTTPS API 和唯一前端来源；变量值不得粘贴到聊天。
预期结果：Funnel HTTPS 可用、明文 HTTP 不可用、live/ready 为 200、API 四个安全响应头
存在、合法 Origin 被精确放行、恶意 Origin 没有 `Access-Control-Allow-Origin`。
安全回传：域名、状态码和三项布尔结果，不回传完整响应头。

```bash
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test -n "${STAGE14_API_BASE_URL:?missing STAGE14_API_BASE_URL}"
test -n "${STAGE14_FRONTEND_ORIGIN:?missing STAGE14_FRONTEND_ORIGIN}"
case "$STAGE14_API_BASE_URL" in https://*) ;; *) exit 1 ;; esac
case "$STAGE14_FRONTEND_ORIGIN" in https://*) ;; *) exit 1 ;; esac
STAGE14_SMOKE_DIR=$(mktemp -d)
trap 'rm -rf "$STAGE14_SMOKE_DIR"' EXIT

if curl --fail --silent --show-error --connect-timeout 5 \
  "${STAGE14_API_BASE_URL/https:/http:}/health/live" >/dev/null 2>&1; then
  exit 1
fi

curl --fail --silent --show-error --output /dev/null \
  --dump-header "$STAGE14_SMOKE_DIR/api-security.headers" \
  "${STAGE14_API_BASE_URL%/}/health/live"
curl --fail --silent --show-error "${STAGE14_API_BASE_URL%/}/health/ready" >/dev/null
tr -d '\r' <"$STAGE14_SMOKE_DIR/api-security.headers" |
  rg -Fxi 'x-content-type-options: nosniff'
tr -d '\r' <"$STAGE14_SMOKE_DIR/api-security.headers" |
  rg -Fxi 'x-frame-options: DENY'
tr -d '\r' <"$STAGE14_SMOKE_DIR/api-security.headers" |
  rg -Fxi 'referrer-policy: no-referrer'
tr -d '\r' <"$STAGE14_SMOKE_DIR/api-security.headers" |
  rg -Fxi 'permissions-policy: camera=(), microphone=(), geolocation=()'

curl --fail --silent --show-error --output /dev/null \
  --dump-header "$STAGE14_SMOKE_DIR/allowed-cors.headers" \
  -H "Origin: $STAGE14_FRONTEND_ORIGIN" \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "${STAGE14_API_BASE_URL%/}/auth/me"
tr -d '\r' <"$STAGE14_SMOKE_DIR/allowed-cors.headers" |
  rg -Fxi "access-control-allow-origin: $STAGE14_FRONTEND_ORIGIN"

blocked_status=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --dump-header "$STAGE14_SMOKE_DIR/blocked-cors.headers" \
  -H 'Origin: https://attacker.invalid' \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "${STAGE14_API_BASE_URL%/}/auth/me")
test "$blocked_status" = "400"
if tr -d '\r' <"$STAGE14_SMOKE_DIR/blocked-cors.headers" |
  rg -qi '^access-control-allow-origin:'; then
  exit 1
fi
```

## 页面只读检查

执行终端：桌面 Chrome、邮箱页面。
前置条件：使用一个已存在账户登录；阶段 14 保持 `PROVIDER_CALLS_ENABLED=false`；不邀请新账户、
不上传文件、不创建作业、不创建批改任务、不生成导出。
预期结果：`/login`、`/auth/callback`、`/assignments`、`/grading-jobs`、`/exports` 和已有详情页可访问；
页面不空白、不出现 404，桌面与 `390 × 844` 视口的 Console 错误和警告均为 0。
安全回传：已存在账户登录是否成功、五个路径是否可访问、桌面和手机视口 Console 计数。

固定步骤：

1. 以已存在账户完成登录；如果浏览器已保留有效会话，只需刷新并确认会话仍有效。
2. 只读打开 `/assignments`、`/grading-jobs`、`/exports` 和一个已有详情页；不得点击任何会产生写入或模型调用的按钮。
3. 打开 Chrome DevTools → Console，确认当前视口错误和警告都为 0。
4. 打开 Chrome DevTools → Network，重新加载 `/login`，检查页面主文档响应头也包含四个安全头。
5. 切换到 `390 × 844`，再次确认无横向滚动条，且 Console 错误和警告仍为 0。

## 部署后检查

执行终端：本机项目根目录和 Supabase SQL Editor。
前置条件：只读页面检查已结束，当前没有其他业务任务。
预期结果：三个 Worker 心跳正常；Celery active/reserved、Redis 三个队列、`unacked`、
`unacked_index` 和数据库 running 计数全部为 0；失败率和容量指标无未处理告警。
安全回传：心跳、active/reserved、队列、unacked、running 计数、失败率区间和容量百分比。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
set -a
source .env.stage14-production
set +a
cd backend
../.venv/bin/celery -A app.workers.celery_app:celery_app inspect ping --timeout 10
../.venv/bin/celery -A app.workers.celery_app:celery_app inspect active --timeout 10
../.venv/bin/celery -A app.workers.celery_app:celery_app inspect reserved --timeout 10
../.venv/bin/python -c 'import os, redis; r=redis.Redis.from_url(os.environ["REDIS_URL"]); counts={q:r.llen(q) for q in ("paper_grading.grading","paper_grading.maintenance","paper_grading.exports")}; counts["unacked"]=r.hlen("unacked"); counts["unacked_index"]=r.zcard("unacked_index"); print(counts); assert all(value == 0 for value in counts.values())'
```

```sql
select 'grading' as task_type, count(*)::bigint as running
from public.grading_job_items where status = 'running'
union all
select 'exports', count(*)::bigint
from public.exports where status = 'running';
```

两行 `running` 必须都是 0。
