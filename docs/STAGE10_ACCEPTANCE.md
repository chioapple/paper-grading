# 阶段 10 验收：Celery 批量评分

## 当前状态

- 阶段 10 已完成并收口。用户最终确认曾获得 `0014` 真实教师权限回归 `2 passed`；该终端结果
  未保留可复查日志，因此按用户人工验收信号记录，而不是 Codex 独立复验结果。
- 本地实现已完成：批次创建、暂停、继续、取消、单篇重试、PostgreSQL 进度汇总、SSE、Celery 分发、Worker 租约、唯一纠正、原始响应审计和失败分类均已落地。
- Redis 只保存 Celery 消息；批次、论文、attempt、租约、重试次数和进度全部以 PostgreSQL 为准。
- 模型调用前必须先在数据库原子 claim。重复消息不会再次调用供应商；调用开始后失去 Worker 的结果一律进入 `needs_review`，不得自动重试计费。
- 成功的 AI 评分进入 `needs_review`；`completed` 留给阶段 11 的教师确认。
- 用户已确认初版第 1–5 部分通过；第 6.2 首次创建批次暴露了教师角色与多余行锁的权限冲突。
- 前向修复迁移 `20260718_0013` 保留教师最小权限，移除只读校验中的 `FOR UPDATE/FOR SHARE`；
  前向修复迁移 `20260718_0014` 分开处理两张表的延迟完整性触发器记录字段；
  必须先通过本文第 1–3 部分的新回归，再重新执行第六部分。
- 第六部分、`0014` 版本、模型快照、Celery/Redis 运行态和令牌清理均已确认通过。

## Supabase 操作边界

Codex 不执行本文件中的 Supabase SQL、迁移、Storage 写入或真实批次操作。用户应逐步执行，并只回传不含密码、Token、Secret Key、签名 URL、论文正文、模型原始响应或完整教师反馈的安全摘要。

## 一、权限修复迁移前只读检查

在独立 Supabase 测试项目的 SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select 'grading_jobs' as table_name, count(*) as row_count
from public.grading_jobs
union all
select 'grading_job_items', count(*)
from public.grading_job_items
union all
select 'grading_attempts', count(*)
from public.grading_attempts;
```

必须同时满足：

- 当前修复前版本是 `20260718_0013`；修复后重跑时允许是 `20260718_0014`；
- 三张评分表均为 `0` 行。

任一条件不满足就停止，不删除或修改现有记录，并把安全结果返回给 Codex。

## 二、执行 `0014` 真实迁移与教师权限回归

第一部分全部满足后，在项目根目录执行：

该命令只允许用于独立测试项目。权限回归会在确认三张评分表起始为空后，在一个外层事务中
创建临时数据；仓储内部事务使用保存点，最后整体回滚，不删除或截断任何既有数据。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e
  if [[ ! -f .env.stage2-test ]]; then
    echo '缺少 .env.stage2-test，停止' >&2
    exit 1
  fi
  set -a
  source .env.stage2-test
  set +a
  ./.venv/bin/pytest -m postgres backend/tests/test_stage10_postgres_contract.py -q
)
```

首次运行按 `0013 → 0014 → 0013 → 0014` 回放，最终停在 `0014`；如果测试在升级后失败，
只要三张评分表仍为空，同一命令也可从 `0014` 安全重跑。随后测试使用
`paper_grading_teacher_api` 的真实事务创建两篇临时批次并重复同一幂等请求。测试必须同时证明：

迁移回放的预检查、两次降级、两次升级和目录核验复用同一个 direct SSL 连接，不再为每一步
重新握手；教师权限回归使用第二个独立连接。连接首次建立失败时仍会直接报错，不做自动重试。

- `TEST_TEACHER_AUTH_USER_ID` 在迁移前已对应真实 Auth 用户；若已有 profile，必须是启用教师；
- 教师可以创建批次，重复请求命中同一批次；
- 教师仍没有三张表的表级或列级 `UPDATE` 权限，真实更新尝试返回 `42501`；
- 延迟批次完整性约束在教师角色下切换为立即执行并成功通过，不等到外层回滚；
- 临时数据随外层事务整体回滚；
- 新触发器函数不含 `FOR UPDATE` 或 `FOR SHARE`。

本部分最终必须返回 `2 passed`。

## 三、迁移后只读检查

回放通过后，在同一 SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and (table_name, column_name) in (
    ('provider_configs', 'model_profiles'),
    ('grading_jobs', 'expected_item_count'),
    ('grading_jobs', 'request_hash'),
    ('grading_jobs', 'model_parameters_hash'),
    ('grading_jobs', 'state_version'),
    ('grading_job_items', 'dispatch_version'),
    ('grading_job_items', 'lease_token'),
    ('grading_attempts', 'attempt_kind'),
    ('grading_attempts', 'provider_call_state'),
    ('grading_attempts', 'input_tokens'),
    ('grading_attempts', 'estimated_cost_amount')
  )
order by table_name, ordinal_position;

select indexname
from pg_catalog.pg_indexes
where schemaname = 'public'
  and indexname in (
    'grading_job_items_dispatch_idx',
    'grading_job_items_expired_lease_idx',
    'grading_attempts_one_running_idx',
    'grading_attempts_raw_response_object_key_idx'
  )
order by indexname;

select rolname, rolcanlogin, rolbypassrls
from pg_catalog.pg_roles
where rolname = 'paper_grading_worker';

select tablename, policyname, roles
from pg_catalog.pg_policies
where schemaname = 'public'
  and 'paper_grading_worker' = any(roles)
order by tablename;

select namespace.nspname,
       function_record.proname,
       function_record.prosecdef,
       function_record.proconfig
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where (namespace.nspname, function_record.proname) in (
  ('public', 'paper_grading_require_ready_job_item'),
  ('public', 'paper_grading_protect_job_snapshot'),
  ('public', 'paper_grading_protect_job_item'),
  ('public', 'paper_grading_protect_attempt_history'),
  ('public', 'paper_grading_validate_job_item_count'),
  ('paper_grading_private', 'control_grading_job')
)
order by namespace.nspname, function_record.proname;

select has_table_privilege(
         'paper_grading_teacher_api', 'public.submissions', 'update'
       ) as teacher_can_update_submissions,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.submissions', 'update'
       ) as teacher_can_update_submission_columns,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
       ) as teacher_can_update_jobs,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
       ) as teacher_can_update_job_columns,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
       ) as teacher_can_update_items,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
       ) as teacher_can_update_item_columns;

select position(
         'FOR UPDATE' in upper(pg_get_functiondef(function_record.oid))
       ) = 0 as no_for_update,
       position(
         'FOR SHARE' in upper(pg_get_functiondef(function_record.oid))
       ) = 0 as no_for_share
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where namespace.nspname = 'public'
  and function_record.proname = 'paper_grading_require_ready_job_item';

select position(
         'IF TG_TABLE_NAME = ''GRADING_JOBS'' THEN'
         in upper(pg_get_functiondef(function_record.oid))
       ) > 0 as separates_job_record,
       position(
         'ELSIF TG_TABLE_NAME = ''GRADING_JOB_ITEMS'' THEN'
         in upper(pg_get_functiondef(function_record.oid))
       ) > 0 as separates_item_record,
       position(
         'ELSE NEW.GRADING_JOB_ID'
         in upper(pg_get_functiondef(function_record.oid))
       ) = 0 as no_cross_record_case
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where namespace.nspname = 'public'
  and function_record.proname = 'paper_grading_validate_job_item_count';

select 'grading_jobs' as table_name, count(*) as row_count
from public.grading_jobs
union all
select 'grading_job_items', count(*)
from public.grading_job_items
union all
select 'grading_attempts', count(*)
from public.grading_attempts;
```

预期：版本为 `0014`；列 11 个、索引 4 个、Worker Policy 7 个；Worker 为
`NOLOGIN/NOBYPASSRLS`；六个函数均为空 `search_path`，仅教师控制函数是
`SECURITY DEFINER`；六个教师表级/列级 `UPDATE` 权限均为 `false`，两个锁检查均为
`true`；三个延迟触发器字段分支检查均为 `true`；三张评分表仍为空。

## 四、本地队列运行环境

以下步骤不操作 Supabase，但后续真实批次使用 `.env.stage7-local` 中的测试项目应用配置。`.env.stage2-test` 只用于第二部分的破坏性迁移回放，不能用于启动 API 或 Worker。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
./.venv/bin/python -m pip install -e './backend[dev]'
brew install redis
brew services start redis
redis-cli ping
```

最后一行必须返回 `PONG`。启动 API 的终端：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
./.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

启动 Worker 的另一个终端：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
cd backend
../.venv/bin/python -m app.workers.supervisor
```

启动日志必须同时显示两个独立节点：`grading@...` 只列出 `paper_grading.grading`，
`maintenance@...` 只列出 `paper_grading.maintenance`。真实评分与周期维护不共享执行槽；维护任务
每 30 秒产生一次，25 秒内未开始就失效，开始后最多运行 25 秒。

## 五、确认 DeepSeek 模型能力快照

迁移只新增空 `model_profiles`，不会猜测现有模型能力。先只读找到目标配置：

```sql
select id, name, provider_type, default_model, status,
       config_version, tested_config_version,
       model_profiles ? default_model as has_default_model_profile
from public.provider_configs
where provider_type = 'deepseek'
order by created_at;
```

确认目标 UUID 后，把下方 `<PROVIDER_UUID>` 替换为该 UUID。以下示例只适用于已按阶段 9 验收确认的 `deepseek-v4-pro`；价格未在本步骤重新核验，因此明确保存为 `null`，不能记成 0 元：

```sql
update public.provider_configs
set model_profiles = jsonb_build_object(
  default_model,
  jsonb_build_object(
    'capabilities', jsonb_build_object(
      'capability_version', 'deepseek-official-2026-07-16',
      'model', default_model,
      'context_window_tokens', 1000000,
      'max_output_tokens', 384000,
      'structured_output', 'json_object',
      'schema_dialect', 'canonical',
      'sampling_policy', 'temperature_zero',
      'thinking_policy', 'disabled',
      'output_token_parameter', 'max_tokens',
      'supports_model_listing', true,
      'pricing', null
    ),
    'grading_max_output_tokens', 4096
  )
)
where id = '<PROVIDER_UUID>'::uuid
  and provider_type = 'deepseek'
  and default_model = 'deepseek-v4-pro'
returning id, name, default_model, status, config_version,
          tested_config_version, model_profiles ? default_model as profile_saved;
```

该更新会按设计把配置变回 `draft` 并清除旧测试。随后在管理员供应商页面重新执行连接测试并启用。不得在 SQL、命令或聊天中填写 API Key。

## 六、真实批次验收

当前阶段还没有批次前端页面，本部分使用本地 API。成功的 AI 结果按设计进入
`needs_review`，不是 `completed`；`completed` 要到阶段 11 经教师确认后产生。

真实 DeepSeek 不能稳定制造 408、429、服务端错误或两次非法结构。不得通过泄露或替换
Key、反复请求限流、修改生产 Base URL 等方式强行制造错误。这些确定性错误分支使用本地自动化
回归；真实环境负责验证队列、数据库、Storage 和一次真实模型调用的集成行为。

用户为排障把 Database Network Restrictions 改为全部 IP 可访问。用户在了解数据库与连接池的
公网暴露面后，明确决定继续保留全网放行；该决定作为用户接受的安全例外记录，不再阻塞阶段 10
收口，但不能描述为安全配置或生产最佳实践。该 Supabase 设置只由用户操作，阶段 14 上线安全验收
必须再次显式复核这项例外。

### 6.1 准备三个终端

- 终端 A：保持第四部分的 API 运行。
- 终端 B：按各小节要求启动或停止 Worker；真实评分时为方便观察，使用
  `--concurrency=1`。
- 终端 C：执行下面的控制命令。

先在终端 C 获取测试教师访问令牌。密码和令牌只保存在当前终端变量中，不得粘贴到聊天：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export API_BASE_URL=http://127.0.0.1:8000

stage10_expect_json() {
  local expected_status="$1"
  local output_path="$2"
  shift 2
  local actual_status
  actual_status="$(curl -sS -o "$output_path" -w '%{http_code}' "$@")" || return 1
  if [ "$actual_status" != "$expected_status" ]; then
    printf 'HTTP 预期 %s，实际 %s\n' "$expected_status" "$actual_status" >&2
    ./.venv/bin/python -m json.tool "$output_path" >&2 || true
    return 1
  fi
}

stage10_login() {
  setopt localtraps
  local teacher_email teacher_password auth_body auth_status auth_file old_umask
  unset ACCESS_TOKEN
  old_umask="$(umask)"
  umask 077
  auth_file="$(mktemp /tmp/paper-grading-stage10-auth.XXXXXX)" || {
    umask "$old_umask"
    return 1
  }
  umask "$old_umask"
  trap 'rm -f "$auth_file"; unset ACCESS_TOKEN' EXIT HUP INT TERM

  read -r "teacher_email?测试教师邮箱: "
  read -rs "teacher_password?测试教师密码: "
  printf '\n'
  auth_body="$(printf '%s\n%s\n' "$teacher_email" "$teacher_password" | \
    ./.venv/bin/python -c 'import json,sys; print(json.dumps({"email":sys.stdin.readline().rstrip("\n"),"password":sys.stdin.readline().rstrip("\n")}))')" || return 1
  auth_status="$(curl -sS -o "$auth_file" -w '%{http_code}' \
    -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
    -H "apikey: $SUPABASE_PUBLISHABLE_KEY" \
    -H 'Content-Type: application/json' \
    --data "$auth_body")" || return 1
  if [ "$auth_status" != 200 ]; then
    printf 'Auth HTTP 预期 200，实际 %s\n' "$auth_status" >&2
    return 1
  fi
  ACCESS_TOKEN="$(./.venv/bin/python -c 'import json,sys; value=json.load(open(sys.argv[1])).get("access_token"); assert isinstance(value,str) and value; print(value)' "$auth_file")" || return 1
  export ACCESS_TOKEN
  rm -f "$auth_file"
  trap - EXIT HUP INT TERM

  stage10_expect_json 200 /tmp/stage10-me.json \
    "$API_BASE_URL/auth/me" -H "Authorization: Bearer $ACCESS_TOKEN" || return 1
  ./.venv/bin/python -m json.tool /tmp/stage10-me.json
}
stage10_login
STAGE10_LOGIN_STATUS="$?"
unset -f stage10_login
if [ "$STAGE10_LOGIN_STATUS" -ne 0 ]; then
  unset STAGE10_LOGIN_STATUS
  false
else
  unset STAGE10_LOGIN_STATUS
fi
```

最后一条必须显示当前账户是启用的测试教师。随后列出可用作业和论文：

```bash
stage10_expect_json 200 /tmp/stage10-assignments.json \
  "$API_BASE_URL/assignments" -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-assignments.json")); [print(x["id"], x["status"], x["title"]) for x in rows]'

read -r "ASSIGNMENT_ID?选择一个 ready 作业 UUID: "
stage10_expect_json 200 /tmp/stage10-submissions.json \
  "$API_BASE_URL/assignments/$ASSIGNMENT_ID/submissions" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-submissions.json")); ready=[x for x in rows if x["status"]=="ready"]; print("ready_count=",len(ready)); [print(x["id"],x["original_filename"]) for x in ready]'
```

作业必须是 `ready`，论文必须是 `ready`。100 篇完整性检查必须有 100 篇不同的已解析
DOCX/PDF；不足时先通过现有论文上传页补齐。当前尚无删除接口，测试数据会保留在独立测试项目。

### 6.2 Worker 停止时验收幂等和 100 篇完整性

本节不能省略：它单独验证同键同批次、同键异请求冲突、Worker 停止时零 attempt，以及
100 篇不漏、不重、不串。任一 `stage10_expect_json` 报错后必须立即停止当前小节，不得继续读取
空响应文件；修复后使用新的幂等键从本小节开头重跑。

先确认终端 B 的 Worker 已停止。构造前两篇论文请求：

```bash
stage10_check_two_item_idempotency() {
  local body2 idem_key reversed_body2
  body2="$(./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-submissions.json")); ids=[x["id"] for x in rows if x["status"]=="ready"][:2]; assert len(ids)==2; print(json.dumps({"submission_ids":ids}))')" || return 1
  idem_key="stage10-idempotency-$(date +%s)"

  stage10_expect_json 202 /tmp/stage10-idem-1.json \
    -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Idempotency-Key: $idem_key" \
    -H 'Content-Type: application/json' --data "$body2" || return 1
  stage10_expect_json 202 /tmp/stage10-idem-2.json \
    -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Idempotency-Key: $idem_key" \
    -H 'Content-Type: application/json' --data "$body2" || return 1

  ./.venv/bin/python -c 'import json; a=json.load(open("/tmp/stage10-idem-1.json")); b=json.load(open("/tmp/stage10-idem-2.json")); assert a["id"]==b["id"]; print("same_job_id=true",a["id"][:8])' || return 1

  reversed_body2="$(printf '%s' "$body2" | ./.venv/bin/python -c 'import json,sys; x=json.load(sys.stdin); x["submission_ids"].reverse(); print(json.dumps(x))')" || return 1
  stage10_expect_json 409 /tmp/stage10-idem-conflict.json \
    -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Idempotency-Key: $idem_key" \
    -H 'Content-Type: application/json' --data "$reversed_body2" || return 1
  ./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-idem-conflict.json")); assert x["detail"]["code"]=="grading_job_idempotency_conflict"; print("idempotency_conflict=409")'
}
stage10_check_two_item_idempotency
STAGE10_TWO_ITEM_STATUS="$?"
unset -f stage10_check_two_item_idempotency
if [ "$STAGE10_TWO_ITEM_STATUS" -ne 0 ]; then
  unset STAGE10_TWO_ITEM_STATUS
  false
else
  unset STAGE10_TWO_ITEM_STATUS
fi
```

预期冲突请求为 HTTP `409`，错误码为 `grading_job_idempotency_conflict`。取消前两篇批次，
避免稍后启动 Worker 时产生费用：

```bash
IDEM_JOB_ID="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-idem-1.json"))["id"])')"
stage10_expect_json 200 /tmp/stage10-idem-cancelled.json \
  -X POST "$API_BASE_URL/grading-jobs/$IDEM_JOB_ID/cancel" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -m json.tool /tmp/stage10-idem-cancelled.json
```

然后创建并立即取消 100 篇批次：

```bash
stage10_check_hundred_items() {
  local body100 key100 job100_id
  body100="$(./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-submissions.json")); ids=[x["id"] for x in rows if x["status"]=="ready"][:100]; assert len(ids)==100; print(json.dumps({"submission_ids":ids}))')" || return 1
  key100="stage10-hundred-$(date +%s)"
  stage10_expect_json 202 /tmp/stage10-hundred.json \
    -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Idempotency-Key: $key100" \
    -H 'Content-Type: application/json' --data "$body100" || return 1
  ./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-hundred.json")); assert x["total"]==100 and [i["position"] for i in x["items"]]==list(range(100)) and len({i["submission_id"] for i in x["items"]})==100 and sum(i["attempt_count"] for i in x["items"])==0; print("hundred_integrity=true",x["id"][:8])' || return 1

  job100_id="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-hundred.json"))["id"])')" || return 1
  stage10_expect_json 200 /tmp/stage10-hundred-cancelled.json \
    -X POST "$API_BASE_URL/grading-jobs/$job100_id/cancel" \
    -H "Authorization: Bearer $ACCESS_TOKEN" || return 1
  ./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-hundred-cancelled.json")); assert x["cancelled"]==100 and sum(i["attempt_count"] for i in x["items"])==0; print("cancelled_without_attempt=true")'
}
stage10_check_hundred_items
STAGE10_HUNDRED_STATUS="$?"
unset -f stage10_check_hundred_items
if [ "$STAGE10_HUNDRED_STATUS" -ne 0 ]; then
  unset STAGE10_HUNDRED_STATUS
  false
else
  unset STAGE10_HUNDRED_STATUS
fi
```

两类批次均确认已取消且 Worker 仍停止后，清掉本次无费用检查留在本机 Redis 的已取消消息，
避免它们延迟下一节真实评分。PostgreSQL 仍保存完整批次事实；该命令仅用于当前独立测试环境：

```bash
cd '/Users/a1-6/Documents/Paper Grading/backend'
../.venv/bin/celery -A app.workers.celery_app:celery_app purge --force
cd ..
[ "$(redis-cli LLEN paper_grading.grading)" -eq 0 ]
[ "$(redis-cli LLEN paper_grading.maintenance)" -eq 0 ]
[ "$(redis-cli LLEN celery)" -eq 0 ]
```

### 6.3 真实评分、SSE、暂停和继续

先在终端 B 确认 DeepSeek 域名没有被 VPN、TUN 或代理的 fake-IP 模式映射为保留地址：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
./.venv/bin/python -c 'import ipaddress,socket; addresses={row[4][0] for row in socket.getaddrinfo("api.deepseek.com",443,type=socket.SOCK_STREAM)}; assert addresses and all(ipaddress.ip_address(value).is_global for value in addresses), addresses; print("provider_dns_public=true")'
```

必须输出 `provider_dns_public=true`。如果断言显示 `198.18.x.x` 等非公网地址，先完全关闭相关
VPN/代理的 TUN 或 fake-IP 模式并重新检查；不得启动 Worker。该安全检查不能为了通过而放宽。

先确认没有之前终端遗留的 Worker；发现任何旧进程都必须先停止，不能同时启动多个 Beat：

```bash
if pgrep -f '[a]pp.workers.supervisor|[c]elery.*app.workers.celery_app:celery_app worker' >/dev/null; then
  echo '检测到旧 Celery Worker，请先停止后再继续' >&2
  false
fi
```

此时保持终端 B 的 Worker 停止。先创建批次并连接 SSE，避免 Worker 在观察端连接前完成评分。

终端 C 创建 5 篇真实批次：

```bash
BODY5="$(./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-submissions.json")); ids=[x["id"] for x in rows if x["status"]=="ready"][:5]; assert len(ids)==5; print(json.dumps({"submission_ids":ids}))')"
LIVE_KEY="stage10-live-$(date +%s)"
stage10_expect_json 202 /tmp/stage10-live.json \
  -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $LIVE_KEY" \
  -H 'Content-Type: application/json' --data "$BODY5"
LIVE_JOB_ID="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-live.json"))["id"])')"
printf 'live_job=%s\n' "${LIVE_JOB_ID:0:8}"
```

新开终端 D，并重新执行 6.1 的令牌获取命令。下面的命令会主动要求输入终端 C 显示的
完整批次 UUID；只复制到本机终端 D，不要发到聊天。UUID 格式通过后开始观察 SSE：

```bash
read -r "LIVE_JOB_ID?粘贴终端 C 显示的完整 LIVE_JOB_ID: "
export LIVE_JOB_ID
if ./.venv/bin/python -c 'import sys,uuid; uuid.UUID(sys.argv[1]); print("live_job_uuid_valid=true")' "$LIVE_JOB_ID"; then
  curl -N -fS "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID/events" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
else
  echo 'LIVE_JOB_ID 不是完整 UUID，未发送 SSE 请求' >&2
fi
```

终端 D 收到初始 `queued` 快照后，在终端 B 启动单并发 Worker：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
cd backend
../.venv/bin/python -m app.workers.supervisor
```

看到至少一个 `running=1` 后，在终端 C 暂停：

```bash
stage10_expect_json 200 /tmp/stage10-paused.json \
  -X POST "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID/pause" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -m json.tool /tmp/stage10-paused.json
PAUSED_ATTEMPTS="$(./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-paused.json")); assert x["status"]=="paused"; print(sum(i["attempt_count"] for i in x["items"]))')"
sleep 10
stage10_expect_json 200 /tmp/stage10-paused-after-wait.json \
  "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -c 'import json,sys; x=json.load(open("/tmp/stage10-paused-after-wait.json")); assert x["status"]=="paused" and sum(i["attempt_count"] for i in x["items"])==int(sys.argv[1]); print("paused_without_new_attempt=true")' "$PAUSED_ATTEMPTS"
```

上面的断言要求批次为 `paused`，并证明等待 10 秒后没有新增 attempt；已经 `running` 的一篇
允许结束。终端 D 按 `Control-C` 断开，再执行同一条 SSE 命令，必须立即收到当前 PostgreSQL
快照。确认后再次按 `Control-C` 断开 SSE，并**回到终端 C**继续批次；终端 D 没有
`stage10_expect_json` 函数，不能在终端 D 执行下面命令：

```bash
stage10_expect_json 200 /tmp/stage10-resumed.json \
  -X POST "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID/resume" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -m json.tool /tmp/stage10-resumed.json
```

等待 SSE 自行结束，或轮询直到 `queued=0` 且 `running=0`：

```bash
SETTLED=no
for _ in {1..180}; do
  stage10_expect_json 200 /tmp/stage10-live-final.json \
    "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
  SETTLED="$(./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-live-final.json")); print("yes" if x["queued"]==0 and x["running"]==0 else "no")')"
  [ "$SETTLED" = yes ] && break
  sleep 2
done
[ "$SETTLED" = yes ] || { echo '6 分钟内批次未结束，本轮失败' >&2; false; }
./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-live-final.json")); counts=[x[k] for k in ("queued","running","needs_review","completed","failed","cancelled")]; assert sum(counts)==x["total"] and x["status"] in ("needs_review","failed"); forbidden={"raw_response","output_text","overall_feedback","criteria_results","deduction_results"}; stack=[x]; keys=set();
while stack:
 v=stack.pop(); keys.update(v.keys()) if isinstance(v,dict) else None; stack.extend(v.values()) if isinstance(v,dict) else stack.extend(v) if isinstance(v,list) else None
assert not keys & forbidden; print({k:x[k] for k in ("total","queued","running","needs_review","completed","failed","cancelled")})'
```

通过标准：状态总和始终等于 `total`；单并发时前一篇进入 `needs_review` 后后续论文仍继续；
最终正常 AI 建议位于 `needs_review`；API/SSE 没有原始响应、正文或完整反馈字段。

### 6.4 运行中取消

Worker 保持单并发，再创建一个 5 篇批次，并在 API 显示 `running=1` 后立即取消：

**终端 B（Worker 终端）确认。** 如果终端 B 正持续显示 Celery 日志，保持不动；如果已经回到
命令行提示符，说明 Worker 未运行，先执行：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
cd backend
../.venv/bin/python -m app.workers.supervisor
```

**终端 C（控制终端）执行。** 必须继续使用 6.1 中定义了 `stage10_expect_json`、且保存着
`ACCESS_TOKEN`、`ASSIGNMENT_ID` 和 `BODY5` 的同一个终端；终端 D 只负责 SSE，不能执行本段。

```bash
stage10_check_running_cancel() {
  local cancel_key cancel_job_id running cancel_attempts
  cancel_key="stage10-cancel-$(date +%s)"
  stage10_expect_json 202 /tmp/stage10-cancel-live.json \
    -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Idempotency-Key: $cancel_key" \
    -H 'Content-Type: application/json' --data "$BODY5" || return 1
  cancel_job_id="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-cancel-live.json"))["id"])')" || return 1
  printf 'cancel_job=%s\n' "$cancel_job_id"

  running=0
  for _ in {1..180}; do
    stage10_expect_json 200 /tmp/stage10-cancel-poll.json \
      "$API_BASE_URL/grading-jobs/$cancel_job_id" \
      -H "Authorization: Bearer $ACCESS_TOKEN" || return 1
    running="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-cancel-poll.json"))["running"])')" || return 1
    [ "$running" -ge 1 ] && break
    sleep 0.5
  done
  [ "$running" -ge 1 ] || {
    printf '90 秒内未捕获 running；批次 %s 已创建，请检查终端 B，禁止直接再建批次\n' "$cancel_job_id" >&2
    return 1
  }

  stage10_expect_json 200 /tmp/stage10-running-cancel.json \
    -X POST "$API_BASE_URL/grading-jobs/$cancel_job_id/cancel" \
    -H "Authorization: Bearer $ACCESS_TOKEN" || return 1
  ./.venv/bin/python -m json.tool /tmp/stage10-running-cancel.json || return 1

  cancel_attempts="$(./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-running-cancel.json")); print(sum(i["attempt_count"] for i in x["items"]))')" || return 1
  sleep 10
  stage10_expect_json 200 /tmp/stage10-running-cancel-final.json \
    "$API_BASE_URL/grading-jobs/$cancel_job_id" \
    -H "Authorization: Bearer $ACCESS_TOKEN" || return 1
  ./.venv/bin/python -c 'import json,sys; x=json.load(open("/tmp/stage10-running-cancel-final.json")); before=int(sys.argv[1]); after=sum(i["attempt_count"] for i in x["items"]); assert x["status"]=="cancelled" and x["queued"]==0 and after==before; print({k:x[k] for k in ("running","needs_review","failed","cancelled")},"attempts=",after); print("stage10_6_4_complete=true")' "$cancel_attempts"
}

if (( ! $+functions[stage10_expect_json] )); then
  echo '当前不是已完成 6.1 初始化的终端 C：缺少 stage10_expect_json' >&2
  false
else
  stage10_check_running_cancel
  STAGE10_RUNNING_CANCEL_STATUS="$?"
  unset -f stage10_check_running_cancel
  [ "$STAGE10_RUNNING_CANCEL_STATUS" -eq 0 ] || false
  unset STAGE10_RUNNING_CANCEL_STATUS
fi
```

预期：尚未开始的论文立即变成 `cancelled`；已开始的一篇允许收口，最终可能是
`needs_review` 或 `failed`；取消后不得再 claim 新论文。

### 6.5 单篇手动重试

从已结束的真实批次中选择一个 `needs_review` 或 `failed` item：

**终端 C（控制终端）执行。** 继续使用 6.3 的 `LIVE_JOB_ID`，不要在终端 D 执行。

```bash
stage10_expect_json 200 /tmp/stage10-retry-before.json \
  "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
RETRY_ITEM_ID="$(./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-retry-before.json")); print(next(i["id"] for i in x["items"] if i["status"] in ("needs_review","failed")))')"
stage10_expect_json 200 /tmp/stage10-retry.json \
  -X POST "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID/items/$RETRY_ITEM_ID/retry" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
RETRY_SETTLED=no
for _ in {1..180}; do
  stage10_expect_json 200 /tmp/stage10-retry-after.json \
    "$API_BASE_URL/grading-jobs/$LIVE_JOB_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
  RETRY_SETTLED="$(./.venv/bin/python -c 'import json,sys; x=json.load(open("/tmp/stage10-retry-after.json")); item=next(i for i in x["items"] if i["id"]==sys.argv[1]); print("yes" if item["status"] not in ("queued","running") else "no")' "$RETRY_ITEM_ID")"
  [ "$RETRY_SETTLED" = yes ] && break
  sleep 2
done
[ "$RETRY_SETTLED" = yes ] || { echo '6 分钟内手动重试未结束，本轮失败' >&2; false; }
./.venv/bin/python -c 'import json,sys; before=json.load(open("/tmp/stage10-retry-before.json")); after=json.load(open("/tmp/stage10-retry-after.json")); target=sys.argv[1]; b={i["id"]:i for i in before["items"]}; a={i["id"]:i for i in after["items"]}; assert set(a)==set(b); assert a[target]["dispatch_version"]==b[target]["dispatch_version"]+1 and a[target]["attempt_count"]>b[target]["attempt_count"]; fields=("dispatch_version","attempt_count","status","error_code"); assert all(tuple(a[k][f] for f in fields)==tuple(b[k][f] for f in fields) for k in b if k!=target); print("only_target_retried=true")' "$RETRY_ITEM_ID"
```

该检查会产生一次新的真实供应商调用；只有目标篇的 `dispatch_version` 和 `attempt_count`
允许增加，其余论文必须保持不变。

### 6.6 Worker 丢失后的模糊结果

该检查可能已经产生一次供应商费用，只使用 1 篇测试论文。

**终端 B（Worker 终端）执行。** 先按 `Control-C` 停止 6.3 使用的普通 Worker，确认回到命令行
提示符后，再执行下面命令启动专用单进程 Worker：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
cd backend
export STAGE10_AMBIG_PIDFILE="/tmp/paper-grading-stage10-ambiguous-${UID}.pid"
if [[ -e "$STAGE10_AMBIG_PIDFILE" ]]; then
  echo "PID 文件已存在，先确认旧 Worker 已停止：$STAGE10_AMBIG_PIDFILE" >&2
  false
else
  ../.venv/bin/celery -A app.workers.celery_app:celery_app worker \
    --queues=paper_grading.grading --hostname=ambiguous@%h \
    --pool=solo --loglevel=INFO --concurrency=1 --pidfile="$STAGE10_AMBIG_PIDFILE"
fi
```

**终端 C（控制终端）执行。** 创建单篇批次并轮询；一旦看到 `running=1`，立即终止终端 B
启动的专用 Worker：

```bash
BODY1="$(./.venv/bin/python -c 'import json; rows=json.load(open("/tmp/stage10-submissions.json")); ids=[x["id"] for x in rows if x["status"]=="ready"][:1]; assert len(ids)==1; print(json.dumps({"submission_ids":ids}))')"
AMBIG_KEY="stage10-ambiguous-$(date +%s)"
stage10_expect_json 202 /tmp/stage10-ambiguous.json \
  -X POST "$API_BASE_URL/assignments/$ASSIGNMENT_ID/grading-jobs" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $AMBIG_KEY" \
  -H 'Content-Type: application/json' --data "$BODY1"
AMBIG_JOB_ID="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-ambiguous.json"))["id"])')"

RUNNING=0
for _ in {1..100}; do
  stage10_expect_json 200 /tmp/stage10-ambiguous-poll.json \
    "$API_BASE_URL/grading-jobs/$AMBIG_JOB_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
  RUNNING="$(./.venv/bin/python -c 'import json; print(json.load(open("/tmp/stage10-ambiguous-poll.json"))["running"])')"
  [ "$RUNNING" -eq 1 ] && break
  sleep 0.1
done
[ "$RUNNING" -eq 1 ] || { printf '未捕获 running 状态，本轮不能证明 Worker 调用中丢失\n'; exit 1; }

STAGE10_AMBIG_PIDFILE="/tmp/paper-grading-stage10-ambiguous-${UID}.pid"
if [[ ! -r "$STAGE10_AMBIG_PIDFILE" ]]; then
  echo '找不到专用 Worker PID 文件，停止' >&2
  false
else
  STAGE10_AMBIG_PID="$(cat "$STAGE10_AMBIG_PIDFILE")"
  STAGE10_AMBIG_COMMAND="$(ps -p "$STAGE10_AMBIG_PID" -o command=)"
  case "$STAGE10_AMBIG_COMMAND" in
    *'app.workers.celery_app:celery_app worker'*)
      kill -KILL "$STAGE10_AMBIG_PID" && rm -f "$STAGE10_AMBIG_PIDFILE"
      ;;
    *)
      echo 'PID 对应的不是本次验收 Worker，拒绝终止' >&2
      false
      ;;
  esac
fi
```

**终端 B（Worker 终端）执行。** 专用 Worker 被终止并且终端 B 回到命令行提示符后，完整执行：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
cd backend
../.venv/bin/python -m app.workers.supervisor
```

租约长度是供应商超时加 30 秒，Beat 每 30 秒检查一次；最迟等待约 6 分钟。

**终端 C（控制终端）执行。** 轮询模糊结果是否按单次 attempt 收口：

```bash
for _ in {1..210}; do
  stage10_expect_json 200 /tmp/stage10-ambiguous-final.json \
    "$API_BASE_URL/grading-jobs/$AMBIG_JOB_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
  SETTLED="$(./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-ambiguous-final.json")); print("yes" if x["queued"]==0 and x["running"]==0 else "no")')"
  [ "$SETTLED" = yes ] && break
  sleep 2
done
[ "$SETTLED" = yes ] || { echo '7 分钟内模糊结果未收口，本轮失败' >&2; false; }
./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-ambiguous-final.json")); item=x["items"][0]; assert item["status"]=="needs_review" and item["error_code"]=="provider_call_outcome_unknown" and item["attempt_count"]==1; print("ambiguous_without_retry=true")'
sleep 60
stage10_expect_json 200 /tmp/stage10-ambiguous-after-wait.json \
  "$API_BASE_URL/grading-jobs/$AMBIG_JOB_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
./.venv/bin/python -c 'import json; x=json.load(open("/tmp/stage10-ambiguous-after-wait.json")); assert x["items"][0]["attempt_count"]==1; print("still_one_attempt=true")'
```

如果杀进程前模型已经完成并写回，最终错误码不会是上述值，这一轮不算模糊结果验收；换一篇更长的
测试论文重做，不得把正常完成结果解释成 Worker 丢失。

### 6.7 确定性错误分支回归

真实供应商不能安全地按需返回指定错误。

**终端 C（控制终端）执行。** 该测试不会调用真实供应商：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
./.venv/bin/pytest -q \
  backend/tests/test_provider_adapters.py \
  backend/tests/test_grading_attempt_runner.py
```

这些测试必须确认：明确响应的 408/504、429、500/502/503/529 才按安全结果自动重试；
同一评分轮最多两次自动重试；无响应的网络/Worker 模糊结果不重试；结构错误最多纠正一次；
第二次结构错误进入 `needs_review`；所有重试保持同供应商、模型、配置版本和快照。

### 6.8 Supabase SQL Editor 只读审计

**Supabase Dashboard 的 SQL Editor 执行；不是终端 A、B、C 或 D。** 把全部
`<LIVE_JOB_UUID>` 替换为 6.3 真实批次的完整 UUID，把 `<BUCKET_NAME>` 替换为当前 Storage
bucket 名称，确认编辑器中不再存在尖括号占位符后再运行：

```sql
select id, status, expected_item_count, model, state_version,
       started_at, finished_at
from public.grading_jobs
where id = '<LIVE_JOB_UUID>'::uuid;

select item.position, item.status, item.dispatch_version, item.retry_count,
       item.error_code, count(attempt.id) as attempt_count
from public.grading_job_items as item
left join public.grading_attempts as attempt
  on attempt.grading_job_item_id = item.id
where item.grading_job_id = '<LIVE_JOB_UUID>'::uuid
group by item.id, item.position, item.status, item.dispatch_version,
         item.retry_count, item.error_code
order by item.position;

select attempt.attempt_kind, attempt.status, attempt.provider_call_state,
       attempt.error_code, attempt.reported_model,
       attempt.provider_request_id is not null as has_request_id,
       octet_length(attempt.raw_response_sha256) as sha256_bytes,
       attempt.raw_response_object_key is not null as has_storage_object,
       attempt.input_tokens, attempt.output_tokens,
       attempt.estimated_cost_amount, attempt.cost_currency,
       attempt.tariff_version
from public.grading_attempts as attempt
join public.grading_job_items as item
  on item.id = attempt.grading_job_item_id
where item.grading_job_id = '<LIVE_JOB_UUID>'::uuid
order by item.position, attempt.attempt_number;

select count(*) filter (where attempt.raw_response_object_key is not null) as object_key_count,
       count(distinct attempt.raw_response_object_key)
         filter (where attempt.raw_response_object_key is not null) as unique_object_key_count,
       bool_and(
         attempt.raw_response_sha256 is null
         or octet_length(attempt.raw_response_sha256) = 32
       ) as all_hashes_valid
from public.grading_attempts as attempt
join public.grading_job_items as item
  on item.id = attempt.grading_job_item_id
where item.grading_job_id = '<LIVE_JOB_UUID>'::uuid;

select count(*) as expected_object_count,
       count(storage_object.id) as existing_object_count
from public.grading_attempts as attempt
join public.grading_job_items as item
  on item.id = attempt.grading_job_item_id
left join storage.objects as storage_object
  on storage_object.bucket_id = '<BUCKET_NAME>'
 and storage_object.name = attempt.raw_response_object_key
where item.grading_job_id = '<LIVE_JOB_UUID>'::uuid
  and attempt.raw_response_object_key is not null;
```

成功或带明确上游响应的 attempt 必须有唯一对象路径和 32 字节哈希；成功结果必须有请求 ID、
实际模型和 Token；`expected_object_count` 必须等于 `existing_object_count`。当前价格快照为
`null` 时，费用三列应全部为 `null`，不能伪装成 0。

### 6.9 回传安全摘要

验收命令完成后清除两个登录终端中的访问令牌。

**终端 C（控制终端）执行：**

```bash
unset ACCESS_TOKEN
```

**终端 D（SSE 终端）执行：**

```bash
unset ACCESS_TOKEN
```

只回传：批次 ID 前 8 位、各状态计数、每篇 attempt 数、供应商调用总数、幂等冲突是否为
409、Worker 丢失是否保持单次 attempt、确定性错误分支测试通过/失败数量。不要回传访问令牌、
密码、论文、Storage 路径、签名 URL、请求 ID、模型原始响应或完整评分内容。

## 七、验收收口

`0014` 迁移与真实教师权限回归、模型快照、Celery/Redis 运行态和第六部分均已按上述证据完成。
用户接受数据库全网 IP 放行作为安全例外；该例外不阻塞阶段 10，但必须在阶段 14 上线安全验收
再次显式复核。阶段 10 已收口，下一步进入阶段 11 教师复核工作台。
