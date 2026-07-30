# 生产冒烟测试 Runbook

## 无写入检查

执行终端：本机项目根目录。
前置条件：设置正式 HTTPS API 和唯一前端来源；变量值不得粘贴到聊天。
预期结果：HTTPS 可用、HTTP 返回 301/302/307/308 且 Location 为 HTTPS、live/ready 为 200、API 四个安全响应头存在、合法 Origin 被精确放行、恶意 Origin 没有 `Access-Control-Allow-Origin`。
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

curl --silent --show-error --max-redirs 0 --output /dev/null \
  --dump-header "$STAGE14_SMOKE_DIR/redirect.headers" \
  --write-out '%{http_code}' \
  "${STAGE14_API_BASE_URL/https:/http:}/health/live" \
  >"$STAGE14_SMOKE_DIR/redirect.status"
read -r STAGE14_REDIRECT_STATUS <"$STAGE14_SMOKE_DIR/redirect.status"
case "$STAGE14_REDIRECT_STATUS" in 301|302|307|308) ;; *) exit 1 ;; esac
tr -d '\r' <"$STAGE14_SMOKE_DIR/redirect.headers" | rg -qi '^location: https://'

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

curl --silent --show-error --output /dev/null \
  --dump-header "$STAGE14_SMOKE_DIR/blocked-cors.headers" \
  -H 'Origin: https://attacker.invalid' \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "${STAGE14_API_BASE_URL%/}/auth/me"
if tr -d '\r' <"$STAGE14_SMOKE_DIR/blocked-cors.headers" |
  rg -qi '^access-control-allow-origin:'; then
  exit 1
fi
```

## 认证与完整流程

执行终端：桌面 Chrome、邮箱页面和本机项目根目录。
前置条件：独立验收管理员、一名全新邀请教师 A、另一名既有教师 B、1 篇无敏感内容的验收 DOCX/PDF；一次完整 Rubric 与单篇评分费用已单独授权。
预期结果：管理员只发送一次邀请；教师 A 在真实邮箱完成回调、设密和首次登录。随后自动脚本只创建 1 个单篇批次，完成创建作业、上传、评分、复核、Excel 导出、同一签名 URL 过期、手机复用和教师 B 隔离。两个视口的 Console 错误和警告均为 0。
安全回传：邀请回调是否完成、`1 passed`、批次规模和 Console 计数；不回传邮箱、密码、Token、论文、对象路径、签名 URL或模型响应。

先由管理员在正式前端邀请教师 A。教师 A 必须在邮箱中打开本次一次性链接、设置新密码并首次登录；密码设置属于人工步骤，不由脚本输入。完成后安全注入以下变量并运行：

```bash
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test -n "${E2E_REAL_BASE_URL:?missing E2E_REAL_BASE_URL}"
test -n "${E2E_REAL_TEACHER_EMAIL:?missing activated teacher email}"
test -n "${E2E_REAL_TEACHER_PASSWORD:?missing activated teacher password}"
test -n "${E2E_REAL_TEACHER_DISPLAY_NAME:?missing teacher display name}"
test -n "${E2E_REAL_OTHER_TEACHER_EMAIL:?missing other teacher email}"
test -n "${E2E_REAL_OTHER_TEACHER_PASSWORD:?missing other teacher password}"
test -n "${E2E_REAL_MODEL_LABEL:?missing model label}"
test -n "${E2E_REAL_ASSIGNMENT_TITLE:?missing assignment title}"
test -n "${E2E_REAL_INSTRUCTIONS_PATH:?missing instructions path}"
test -n "${E2E_REAL_RUBRIC_PATH:?missing rubric path}"
test -n "${E2E_REAL_PAPER_PATH:?missing paper path}"
test -n "${E2E_REAL_TOTAL_SCORE:?missing total score}"
test -n "${E2E_REAL_SCORE_STEP:?missing score step}"
export E2E_REAL=true
export E2E_REAL_WRITES=I_ACCEPT_STAGE14_TEST_WRITES
export E2E_REAL_MODEL_CALLS=I_ACCEPT_ONE_COMPLETE_MODEL_FLOW
npm --prefix frontend run e2e:real
```

## 签名 URL 过期验证

真实脚本从首次下载响应中仅保留内存中的同一个签名 URL，等待超过
`expires_in_seconds` 5 秒后再次请求；必须返回 4xx。脚本不输出 URL，安全回传也不得
回传签名 URL。

## 部署后检查

执行终端：Render Worker Shell 和 Supabase SQL Editor。
前置条件：完整流程已结束，当前没有其他业务任务。
预期结果：三个 Worker 心跳正常；Celery active/reserved、Redis 三个队列、`unacked`、`unacked_index` 和数据库 running 计数全部为 0；失败率和容量指标无未处理告警。
安全回传：心跳、active/reserved、队列、unacked、running 计数、失败率区间和容量百分比。

```bash
cd "/opt/render/project/src/backend"
celery -A app.workers.celery_app:celery_app inspect ping --timeout 10
celery -A app.workers.celery_app:celery_app inspect active --timeout 10
celery -A app.workers.celery_app:celery_app inspect reserved --timeout 10
python -c 'import os, redis; r=redis.Redis.from_url(os.environ["REDIS_URL"]); counts={q:r.llen(q) for q in ("paper_grading.grading","paper_grading.maintenance","paper_grading.exports")}; counts["unacked"]=r.hlen("unacked"); counts["unacked_index"]=r.zcard("unacked_index"); print(counts); assert all(value == 0 for value in counts.values())'
```

```sql
select 'grading' as task_type, count(*)::bigint as running
from public.grading_job_items where status = 'running'
union all
select 'exports', count(*)::bigint
from public.exports where status = 'running';
```

两行 `running` 必须都是 0。
