# 阶段 11 验收：教师复核工作台

## 当前状态与硬边界

- 阶段 11 已完成。用户于 2026-07-22 明确确认自动化、真实 PostgreSQL、双教师、真实论文和真实浏览器验收通过。
- AI 成功结果先进入 `needs_review`。只有教师确认后，单篇论文和最后一个批次才能进入 `completed`。
- 默认由用户执行 Supabase、真实模型和教师确认。只有用户在当前对话明确授权具体网站与具体批次后，自动验收代理才可执行不读取论文正文的迁移和只读状态核对；模型调用、完整反馈和最终成绩确认仍按当次授权与平台能力边界处理。
- 不把密码、access token、Secret Key、签名 URL、论文正文、完整反馈或模型原始响应贴到聊天。
- 基础迁移 `0015` 的回放要求 `teacher_reviews = 0`，真实复核产生数据后禁止再降到 `0014`。修复迁移 `0016` 只增加批次状态保护，可在保留复核数据时安全执行 `0015 ↔ 0016` 回放。

## 一、执行位置和资源分工

整个验收只使用下表中的位置。后文每个命令块都会再次标明位置。

| 名称 | 位置 | 用途 | 是否长期运行 |
|---|---|---|---|
| Supabase SQL Editor | Supabase Dashboard 网页 | 只读检查迁移、权限和最终数据 | 否 |
| 终端 A | macOS Terminal | FastAPI，端口 `8000` | 是 |
| 终端 B | macOS Terminal | Vite 前端，端口 `5173` | 是 |
| 终端 C | macOS Terminal | Celery Worker 与 Beat | 是 |
| 终端 D | macOS Terminal | 测试、登录、API 验收和生成 SQL | 否 |
| 应用浏览器 | 用户日常浏览器 | 教师 A/B 登录和真实页面验收 | 否 |

资源规则：

1. 迁移和真实 PostgreSQL 测试期间，终端 A、B、C 必须停止。
2. 终端 A、B、C 各自只能启动一个进程；看到端口或 Worker 已占用时，不要再启动第二份。
3. 创建真实批次前先保持终端 C 停止。批次创建后由用户明确接受模型费用，再启动终端 C。
4. API 失败时先检查 HTTP 状态和响应文件，再解析 JSON。禁止用缺失文件制造第二个错误。
5. 本文件推荐使用恰好 3 篇论文：1 篇验证单篇并发确认，2 篇验证错误批量全失败和正确批量全成功。

## 二、停止旧进程并做本地自动化验收

### 2.1 手动停止长期进程

手动操作：分别切到终端 A、B、C。如果进程仍在运行，各按一次 `Control+C`，等命令提示符重新出现。

### 2.2 确认没有抢占资源

执行位置：终端 D。

```bash
cd '/Users/a1-6/Documents/Paper Grading'

echo '8000 端口：'
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
echo '5173 端口：'
lsof -nP -iTCP:5173 -sTCP:LISTEN || true
echo '评分 Worker：'
pgrep -fl 'app.workers.supervisor|celery.*paper_grading' || true
```

预期三段都没有输出。若有输出，回到对应终端手动 `Control+C`；不要盲目 `kill`，也不要继续迁移。

### 2.3 运行全部本地门禁

执行位置：终端 D。整段从项目根目录执行；任一命令失败就停止。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e

  cd backend
  ../.venv/bin/pytest -q
  ../.venv/bin/pytest --collect-only -q -m postgres
  ../.venv/bin/ruff check app tests migrations scripts
  ../.venv/bin/ruff format --check app tests migrations scripts
  ../.venv/bin/mypy app tests scripts
  cd ..

  npm --prefix frontend test
  npm --prefix frontend run lint
  npm --prefix frontend run typecheck
  npm --prefix frontend run build

  git diff --check
)
```

验收点：普通 `pytest` 默认排除 `postgres` 测试；收集命令只收集、不连接数据库。

## 三、迁移前 Supabase 只读检查

执行位置：Supabase Dashboard → 当前独立测试项目 → SQL Editor → New query。

手动操作：复制下面 SQL，点击 Run。不要在终端执行。

```sql
select version_num
from public.alembic_version;

select 'teacher_reviews' as table_name, count(*) as row_count
from public.teacher_reviews
union all
select 'grading_jobs', count(*) from public.grading_jobs
union all
select 'grading_job_items', count(*) from public.grading_job_items
union all
select 'grading_attempts', count(*) from public.grading_attempts
order by table_name;
```

允许的起点：

- `version_num` 是 `20260719_0015` 或 `20260721_0016`；
- `teacher_reviews` 可以非 0，但不得删除或覆盖；
- 其他三张表可以非空，绝对不要删除已有数据。

若 `teacher_reviews` 非 0，禁止降到 `0014`；只允许回放不移除复核结构的 `0015 ↔ 0016`。

把四张表的计数留在 SQL Editor 结果页，稍后用于确认测试没有改动既有数据。

## 四、`0015 → 0016 → 0015 → 0016` 修复迁移回放

### 4.1 检查测试环境文件

执行位置：终端 D。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e
  test -f .env.stage2-test || {
    echo '缺少 .env.stage2-test，停止' >&2
    exit 1
  }
  test -f .env.stage7-local || {
    echo '缺少 .env.stage7-local，停止' >&2
    exit 1
  }

  set -a
  source .env.stage2-test
  source .env.stage7-local
  set +a
  export TEST_DATABASE_URL="${DATABASE_URL}"

  ./.venv/bin/python - <<'PY'
import os
from uuid import UUID

required = (
    "TEST_MIGRATION_DATABASE_URL",
    "TEST_DATABASE_URL",
    "TEST_SUPABASE_PROJECT_REF",
    "TEST_DATABASE_RESET_CONFIRMATION",
    "TEST_TEACHER_AUTH_USER_ID",
    "TEST_OTHER_AUTH_USER_ID",
)
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("缺少测试环境变量：" + ", ".join(missing))
teacher_a = UUID(os.environ["TEST_TEACHER_AUTH_USER_ID"])
teacher_b = UUID(os.environ["TEST_OTHER_AUTH_USER_ID"])
if teacher_a == teacher_b:
    raise SystemExit("两位测试教师 UUID 必须不同")
if os.environ["TEST_DATABASE_RESET_CONFIRMATION"] != (
    "I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA"
):
    raise SystemExit("TEST_DATABASE_RESET_CONFIRMATION 确认值不正确")
print("阶段 11 测试环境变量完整，两位教师 UUID 不同")
PY
)
```

这里不打印数据库密码或教师 UUID。当前项目直接复用 `.env.stage7-local` 中同一测试项目的 Session Pooler，并只在当前子进程映射为 `TEST_DATABASE_URL`，不会复制或改写密码。若失败，先核对两个环境文件，不要把内容发到聊天。

### 4.2 先验证两种连接入口

执行位置：终端 D。此步骤只执行 `select 1` 和读取迁移版本，不写数据库。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e
  set -a
  source .env.stage2-test
  source .env.stage7-local
  set +a
  export TEST_DATABASE_URL="${DATABASE_URL}"

  PYTHONPATH=backend ./.venv/bin/python - <<'PY'
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings


async def check() -> None:
    settings = TestMigrationSettings()
    for label, url in (
        ("Direct", settings.test_migration_database_url),
        ("Session Pooler", settings.test_database_url),
    ):
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"timeout": 15},
        )
        try:
            async with asyncio.timeout(20):
                async with engine.connect() as connection:
                    assert await connection.scalar(text("select 1")) == 1
                    revision = await connection.scalar(
                        text("select version_num from public.alembic_version")
                    )
                    print(f"{label} 只读连接成功，迁移版本：{revision}")
        finally:
            await engine.dispose()


asyncio.run(check())
PY
)
```

Direct 连接只用于迁移；Session Pooler 只用于权限、RLS 和事务测试。`nc` 成功只证明 TCP 可达，不能替代这里的 PostgreSQL TLS 握手。

### 4.3 回放阶段 11 迁移

执行位置：终端 D。此步骤只回放 `0015 ↔ 0016`，不会移除 `teacher_reviews` 或阶段 11 字段；只运行一次，执行前必须再次确认终端 A、B、C 均已停止。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e
  set -a
  source .env.stage2-test
  source .env.stage7-local
  set +a
  export TEST_DATABASE_URL="${DATABASE_URL}"

  ./.venv/bin/pytest \
    -m postgres \
    backend/tests/test_stage11_postgres_contract.py::test_stage_eleven_migration_replays_on_real_supabase \
    -q
)
```

预期通过 1 项。测试会在同一个 Direct 连接中串行回放修复迁移，失败时也会尽力恢复到 `20260721_0016`。已经取得一次通过结果后，不得为了重跑权限测试而重复执行本步骤。

### 4.4 验证教师权限和原子确认

执行位置：终端 D。此步骤会在测试库中临时写入随机夹具，但所有写入都位于外层事务并最终整体回滚，属于中风险操作。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
(
  set -e
  set -a
  source .env.stage2-test
  source .env.stage7-local
  set +a
  export TEST_DATABASE_URL="${DATABASE_URL}"

  ./.venv/bin/pytest \
    -m postgres \
    backend/tests/test_stage11_postgres_contract.py::test_partial_confirmation_keeps_queued_item_dispatchable \
    backend/tests/test_stage11_postgres_contract.py::test_stage_eleven_teacher_permissions_and_atomic_batch_confirmation \
    -q
)
```

预期通过 2 项。第一项复现“先确认一篇、另一篇仍排队”的真实状态并断言剩余论文仍可调度；第二项覆盖教师最小权限和原子批量确认。两项都固定走同一测试项目的 Session Pooler 5432，不再为普通权限事务建立新的 IPv6 Direct 连接。

### 4.5 再次核对版本和计数

执行位置：Supabase SQL Editor。重新运行第三部分的 SQL。

预期：

- 版本最终为 `20260721_0016`；
- 四张表计数与第三部分完全一致；
- 尤其不能为了让测试通过而清空 `grading_jobs`、`grading_job_items` 或 `grading_attempts`。

## 五、迁移后的函数、索引和最小权限

执行位置：Supabase SQL Editor。复制整段并点击 Run。

```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'teacher_reviews'
  and column_name in (
    'criteria_results',
    'deduction_results',
    'subtotal',
    'deduction_total',
    'final_score',
    'feedback'
  )
order by ordinal_position;

select function_record.proname,
       function_record.prosecdef as security_definer,
       function_record.proconfig,
       exists (
         select 1
         from pg_catalog.aclexplode(
           coalesce(
             function_record.proacl,
             pg_catalog.acldefault('f', function_record.proowner)
           )
         ) as privilege
         where privilege.grantee = 0
           and privilege.privilege_type = 'EXECUTE'
       ) as public_can_execute,
       has_function_privilege(
         'anon', function_record.oid, 'execute'
       ) as anon_can_execute,
       has_function_privilege(
         'authenticated', function_record.oid, 'execute'
       ) as authenticated_can_execute,
       has_function_privilege(
         'service_role', function_record.oid, 'execute'
       ) as service_role_can_execute,
       has_function_privilege(
         'paper_grading_teacher_api', function_record.oid, 'execute'
       ) as teacher_can_execute
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where namespace.nspname = 'paper_grading_private'
  and function_record.proname in (
    'validate_teacher_review_payload',
    'save_teacher_review_draft',
    'confirm_teacher_reviews'
  )
order by function_record.proname;

select has_table_privilege(
         'paper_grading_teacher_api', 'public.teacher_reviews', 'insert'
       ) as reviews_insert,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.teacher_reviews', 'update'
       ) as reviews_update,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
       ) as jobs_update,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
       ) as items_update,
       has_table_privilege(
         'paper_grading_teacher_api', 'public.audit_logs', 'insert'
       ) as audit_insert,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.teacher_reviews', 'insert'
       ) as reviews_column_insert,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.teacher_reviews', 'update'
       ) as reviews_column_update,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
       ) as jobs_column_update,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
       ) as items_column_update,
       has_any_column_privilege(
         'paper_grading_teacher_api', 'public.audit_logs', 'insert'
       ) as audit_column_insert;

select indexname, indexdef
from pg_catalog.pg_indexes
where schemaname = 'public'
  and indexname = 'teacher_reviews_one_attempt_idx';

select function_record.proname,
       function_record.prosecdef as security_definer,
       function_record.proconfig,
       has_function_privilege(
         'public', function_record.oid, 'execute'
       ) as public_can_execute
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where namespace.nspname = 'public'
  and function_record.proname = 'paper_grading_preserve_active_job_status';

select trigger_record.tgname,
       pg_catalog.pg_get_triggerdef(trigger_record.oid) as trigger_definition
from pg_catalog.pg_trigger as trigger_record
where trigger_record.tgrelid = 'public.grading_jobs'::regclass
  and trigger_record.tgname = 'grading_jobs_preserve_active_status'
  and not trigger_record.tgisinternal;
```

预期：

1. 六个复核结果字段全部 `is_nullable = NO`。
2. 三个函数均为 `SECURITY DEFINER`，`proconfig` 显示空 `search_path`。
3. `PUBLIC`、`anon`、`authenticated`、`service_role` 对三个函数均不能执行。
4. 教师应用角色只能执行保存草稿和确认函数，不能执行内部校验函数。
5. 十个表级和列级写权限全部为 `false`。
6. 唯一索引定义包含 `UNIQUE` 和 `(grading_attempt_id)`。
7. `paper_grading_preserve_active_job_status` 为 invoker、固定空 `search_path`、`PUBLIC` 不可执行；`grading_jobs_preserve_active_status` 是 `BEFORE UPDATE OF status` 触发器。

## 六、启动本地真实教师环境

### 6.1 检查 Redis，只保留一份

执行位置：终端 D。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
redis-cli -u redis://127.0.0.1:6379/0 ping
```

预期输出 `PONG`。如果命令不可用或没有 `PONG`，先按本机既有方式启动一份 Redis，再重试；不要同时启动两份 Redis。

### 6.2 启动 API

执行位置：终端 A。该命令长期运行，看到 `Uvicorn running` 后不要在此终端执行其他命令。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
./.venv/bin/uvicorn app.main:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port 8000
```

### 6.3 启动前端

执行位置：终端 B。该命令长期运行。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export VITE_API_BASE_URL='http://127.0.0.1:8000'
export VITE_SUPABASE_URL="${SUPABASE_URL}"
export VITE_SUPABASE_PUBLISHABLE_KEY="${SUPABASE_PUBLISHABLE_KEY}"
npm --prefix frontend run dev -- --host 127.0.0.1
```

手动操作：应用浏览器打开 `http://127.0.0.1:5173`，使用教师 A 登录。

### 6.4 先修复并回归作业状态

执行位置：应用浏览器，教师 A。

风险与手动操作：本节会更新真实作业状态，属于可恢复的中风险操作。自动验收代理必须在点击“归档”前停下并取得用户确认；用户手工验收时，确认目标作业标题无误后再操作。不要在终端或 Supabase SQL Editor 直接改 `assignments.status`。

1. 打开“作业”。
2. 找到“阶段六验收 - 2026-07-16”。若它因旧逻辑显示为“草稿”但已有已确认 Rubric，先点“归档”，等状态变成“已归档”，再点“恢复”。新状态必须是“可批改”，并重新出现“上传论文”。
3. 对任一已有已确认 Rubric 的可批改作业执行“归档 → 恢复”，必须恢复为“可批改”。
4. 对没有已确认 Rubric 的纯草稿执行“归档 → 恢复”，必须恢复为“草稿”。
5. 草稿可以进入“编辑作业”；可批改作业不可改写已确认的历史题目和 Rubric，只能上传论文或建立新版本。

### 6.5 建立恰好 3 篇论文的验收批次

执行位置：应用浏览器，教师 A。此时终端 C 必须仍未启动。

1. 打开新的“Test”作业；确认状态是“可批改”。若不是，先确认其 Rubric。
2. 点击“上传论文”。若已经有至少 3 篇“解析完成”的真实 PDF/DOCX，不要重复上传；若不足 3 篇，才手工补齐并等待进入 `ready`。
3. 在论文表格第一列勾选恰好 3 篇“解析完成”的论文。未勾选时“创建批改任务”保持禁用，这是防止空批次，不是故障。
4. 点击“创建批改任务”。页面不应要求手工输入 UUID。
5. 创建成功后进入“批改任务”；此时没有 Worker，批次可以保持排队状态，不会产生模型调用。
6. 不要重复点击创建。若页面超时，先在“批改任务”确认是否已存在该批次。

创建后必须确认新批次的 `prompt_version = grading-prompt.v3`。历史 v1/v2 批次和 attempt 不得覆盖、改名或用于代替本次验收；item 显示 `needs_review` 时还必须同时满足 `review_available = true`，否则它只是失败结果等待人工处理，不能进入草稿或确认。

### 6.6 明确接受模型费用后启动 Worker

手动确认：这一步会产生至少 3 次初始模型调用；第十部分还会产生 1 次重评调用。确认使用真实供应商和费用后再继续。

先保持默认 `ALLOW_OFFICIAL_PROVIDER_FAKE_IP=false`。只有同时满足以下条件时，才允许在本次终端 C 临时改为 `true`：

1. 用户已经明确接受这次临时安全例外；
2. 当前是 `APP_ENV=development`；
3. 内置供应商仍使用代码固定的官方 Base URL；
4. DNS 只因本机 VPN 增强模式返回 `198.18.0.0/15`；
5. Worker 停止后立即关闭例外。

该开关不会放行自定义 Base URL、其他私网、环回或链路本地地址；生产环境即使误设也会拒绝启动。没有 VPN fake-IP 时不要开启。

执行位置：终端 C。该命令长期运行；若 `pgrep` 已显示 supervisor，不要再启动第二份。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL=redis://127.0.0.1:6379/0
# 默认关闭。仅在满足上方五项且用户已明确允许时，才把下一行临时改为 true。
export ALLOW_OFFICIAL_PROVIDER_FAKE_IP=false
cd backend
../.venv/bin/python -m app.workers.supervisor
```

预期看到 grading 和 maintenance 两个消费者 ready。`Discarding revoked task` 是历史撤销记录，不等于本次评分失败；本次任务状态以页面和 API 为准。

## 七、终端 D 安全登录和 HTTP 检查工具

### 7.1 创建仅当前用户可读的临时目录

执行位置：终端 D。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
umask 077
export STAGE11_TMP_DIR="$(mktemp -d /tmp/paper-grading-stage11.XXXXXX)"
export STAGE11_API='http://127.0.0.1:8000'
test -d "${STAGE11_TMP_DIR}"
```

### 7.2 交互登录两位教师

执行位置：终端 D。脚本会依次询问邮箱和密码；密码输入时不显示。access token 只进入当前终端环境，不写入临时文件。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export APP_ENV=development
export REDIS_URL='redis://127.0.0.1:6379/0'

stage11_login_teachers() {
  local teacher_a_token
  local teacher_b_token
  teacher_a_token="$(
    PYTHONPATH=backend ./.venv/bin/python \
      backend/scripts/stage11_teacher_token.py --label '教师 A'
  )" || return 1
  teacher_b_token="$(
    PYTHONPATH=backend ./.venv/bin/python \
      backend/scripts/stage11_teacher_token.py --label '教师 B'
  )" || return 1
  export STAGE11_TEACHER_A_TOKEN="${teacher_a_token}"
  export STAGE11_TEACHER_B_TOKEN="${teacher_b_token}"
}

stage11_login_teachers
```

禁止使用 `教师A的访问令牌`、`教师B的访问令牌` 等示例文字。脚本若失败，不会导出伪造令牌。

### 7.3 定义“先看状态、再解析”的请求函数

执行位置：终端 D。后续命令依赖这个函数，关闭终端后必须重新执行。

```bash
stage11_expect() {
  local expected_status="$1"
  local output_file="$2"
  shift 2
  local actual_status
  actual_status="$(curl -sS -o "${output_file}" -w '%{http_code}' "$@")" || {
    echo 'curl 无法连接 API' >&2
    return 1
  }
  if [[ "${actual_status}" != "${expected_status}" ]]; then
    echo "HTTP 状态不符：预期 ${expected_status}，实际 ${actual_status}" >&2
    jq . "${output_file}" 2>/dev/null || true
    return 1
  fi
}
```

### 7.4 先验证身份，再访问业务接口

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/teacher-a-me.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/auth/me"

stage11_expect 200 "${STAGE11_TMP_DIR}/teacher-b-me.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_B_TOKEN}" \
  "${STAGE11_API}/auth/me"

jq -e '.role == "teacher" and .status == "active"' \
  "${STAGE11_TMP_DIR}/teacher-a-me.json" >/dev/null
jq -e '.role == "teacher" and .status == "active"' \
  "${STAGE11_TMP_DIR}/teacher-b-me.json" >/dev/null

export STAGE11_TEACHER_A_ID="$(jq -r '.id' "${STAGE11_TMP_DIR}/teacher-a-me.json")"
export STAGE11_TEACHER_B_ID="$(jq -r '.id' "${STAGE11_TMP_DIR}/teacher-b-me.json")"
test "${STAGE11_TEACHER_A_ID}" != "${STAGE11_TEACHER_B_ID}"

jq '{display_name, role, status}' "${STAGE11_TMP_DIR}/teacher-a-me.json"
jq '{display_name, role, status}' "${STAGE11_TMP_DIR}/teacher-b-me.json"
```

如果这里返回 401，重新运行 7.2；不要继续请求 `/grading-jobs`。如果返回 500，查看终端 A 的第一条异常并停止。

## 八、批次列表、安全详情和双教师隔离

### 8.1 等待同一批次的 3 篇论文进入复核

执行位置：终端 D。此循环只读取列表，不创建新批次；最多等待 5 分钟。

```bash
if [[ -z "${STAGE11_EXPECTED_JOB_ID:-}" ]]; then
  read -r "STAGE11_EXPECTED_JOB_ID?输入第 6.5 节创建的批次 UUID: "
fi
if [[ ! "${STAGE11_EXPECTED_JOB_ID}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
  echo '批次 UUID 格式错误；停止，不能从历史批次中自动猜测' >&2
  false
fi
export STAGE11_EXPECTED_JOB_ID

stage11_wait_for_batch() {
  STAGE11_JOB_ID="${STAGE11_EXPECTED_JOB_ID}"
  export STAGE11_JOB_ID
  for stage11_poll in {1..60}; do
    stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-a.json" \
      -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
      "${STAGE11_API}/grading-jobs" || return 1

    stage11_ready_job_id="$(
      jq -r --arg job "${STAGE11_JOB_ID}" '[.[]
        | select(.id == $job)
        | select(.total == 3 and .needs_review == 3 and .failed == 0)
        | select(all(.items[]; .status == "needs_review" and .review_available == true))
      ][0].id // empty' \
        "${STAGE11_TMP_DIR}/jobs-a.json"
    )"
    if [[ "${stage11_ready_job_id}" == "${STAGE11_JOB_ID}" ]]; then
      return 0
    fi
    sleep 5
  done
  return 1
}

if stage11_wait_for_batch; then
  jq --arg job "${STAGE11_JOB_ID}" \
    '.[] | select(.id == $job) |
     {id, assignment_title, model, status, total, needs_review, completed, failed,
      items: [.items[] | {id, original_filename, status, attempt_count,
                           review_available, review_status}]}' \
    "${STAGE11_TMP_DIR}/jobs-a.json"
else
  echo '5 分钟内当前指定批次没有达到 3 篇都有成功模型结果；请检查页面和终端 C，不要改用历史批次或新建重复批次' >&2
  false
fi
```

预期只命中第 6.5 节创建并人工输入的当前批次，不能从历史批次中自动选择。该批次必须满足 `status = needs_review`、`total = 3`、`needs_review = 3`、`failed = 0`，且三篇的 `review_available = true`。后端的 `review_available` 只在当前 `dispatch_version` 存在 `succeeded` attempt 时为真；`needs_review` 本身只表示必须由教师处理，模型调用结果未知或失败时也可能进入该状态。此时页面应显示带费用警告的“使用原模型重评”，不得把它当作可复核成功结果，也不得跳过后继续确认。

### 8.2 自动选择第一篇并读取安全详情

执行位置：终端 D。

```bash
export STAGE11_ITEM_ID="$(
  jq -r --arg job "${STAGE11_JOB_ID}" \
    '[.[] | select(.id == $job) | .items[]
      | select(.status == "needs_review" and .review_available == true)][0].id // empty' \
    "${STAGE11_TMP_DIR}/jobs-a.json"
)"
test -n "${STAGE11_ITEM_ID}"

stage11_expect 200 "${STAGE11_TMP_DIR}/review-before.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq '{job_id, item_id, item_status, assignment_title, original_filename,
     rubric_version, attempt_id: .attempt.id, attempt_number: .attempt.attempt_number,
     draft_status: .draft.status}' \
  "${STAGE11_TMP_DIR}/review-before.json"
```

### 8.3 检查详情没有敏感执行字段

执行位置：终端 D。必须输出 `[]`。

```bash
jq '[paths(scalars) as $path
     | ($path | map(tostring) | join("."))
     | select(test("raw_response|object_key|sha256|request_id|token|cost|api_key"; "i"))]
    | unique' \
  "${STAGE11_TMP_DIR}/review-before.json"
```

不要把该详情文件贴到聊天，因为它包含论文规范文本和反馈。

同一终端继续检查所有评分理由、扣分理由、修改建议和总体反馈均为英文脚本文本；只输出布尔结果，不输出反馈内容：

```bash
./.venv/bin/python - <<'PY'
import json
import os
import unicodedata
from pathlib import Path

detail = json.loads(
    (Path(os.environ["STAGE11_TMP_DIR"]) / "review-before.json").read_text()
)
narratives = [detail["attempt"]["overall_feedback"]]
for criterion in detail["attempt"]["dimensions"]:
    narratives.append(criterion["reason"])
    narratives.extend(criterion["revision_suggestions"])
for deduction in detail["attempt"]["deductions"]:
    narratives.append(deduction["reason"])

def is_english_script(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    return bool(letters) and all(
        "LATIN" in unicodedata.name(character, "") for character in letters
    )

if not all(is_english_script(value) for value in narratives):
    raise SystemExit("失败：复核详情存在非英文叙述字段")
print("english_narrative=true")
PY
```

### 8.4 教师 B 看不到教师 A 的批次

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-b.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_B_TOKEN}" \
  "${STAGE11_API}/grading-jobs"

jq -e --arg job "${STAGE11_JOB_ID}" \
  'all(.[]; .id != $job)' \
  "${STAGE11_TMP_DIR}/jobs-b.json" >/dev/null

stage11_expect 404 "${STAGE11_TMP_DIR}/teacher-b-detail.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_B_TOKEN}" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq -e '.detail.code == "review_not_found"' \
  "${STAGE11_TMP_DIR}/teacher-b-detail.json" >/dev/null
```

教师 B 自己可以有历史批次；这里只断言教师 A 的本次批次不在教师 B 列表中，且直接访问统一返回 404。

## 九、真实证据、草稿、总分和修改原因

### 9.1 从当前 AI 结果生成完整草稿

执行位置：终端 D。

```bash
jq '{
  attempt_id: .attempt.id,
  criteria: [.attempt.dimensions[] |
    {dimension_id, score, reason, revision_suggestions}],
  deductions: [.attempt.deductions[] |
    {deduction_id, applied, reason}],
  evidence: (
    [.attempt.dimensions[] as $item | $item.evidence[] |
      {target_type: "dimension", target_id: $item.dimension_id, block_id, quote}]
    +
    [.attempt.deductions[] as $item | $item.evidence[] |
      {target_type: "deduction", target_id: $item.deduction_id, block_id, quote}]
  ),
  overall_feedback: .attempt.overall_feedback,
  change_reason: null
}' "${STAGE11_TMP_DIR}/review-before.json" \
  > "${STAGE11_TMP_DIR}/draft-original.json"

jq -e '.criteria | length > 0' "${STAGE11_TMP_DIR}/draft-original.json" >/dev/null
jq -e '.evidence | length > 0' "${STAGE11_TMP_DIR}/draft-original.json" >/dev/null
```

如果证据数组为空，停止；不要伪造引文。

### 9.2 保存原 AI 草稿

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/saved-1.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-original.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

export STAGE11_REVISION_1="$(jq -r '.revision_number' "${STAGE11_TMP_DIR}/saved-1.json")"
jq '{id, revision_number, status, subtotal, deduction_total, final_score}' \
  "${STAGE11_TMP_DIR}/saved-1.json"
```

预期 `status = draft`，三个总分由后端返回为 JSON 字符串或精确十进制表示。

### 9.3 修改 AI 结果但不填原因，必须失败

执行位置：终端 D。

```bash
jq '.overall_feedback += " Teacher review adjustment."
    | .change_reason = null' \
  "${STAGE11_TMP_DIR}/draft-original.json" \
  > "${STAGE11_TMP_DIR}/draft-changed-no-reason.json"

stage11_expect 422 "${STAGE11_TMP_DIR}/changed-no-reason-result.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-changed-no-reason.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq -e '.detail.code == "review_change_reason_required"' \
  "${STAGE11_TMP_DIR}/changed-no-reason-result.json" >/dev/null
```

### 9.4 填写原因后保存，修订号必须加一

执行位置：终端 D。

```bash
jq '.change_reason = "Teacher corrected the overall feedback after reviewing the paper."' \
  "${STAGE11_TMP_DIR}/draft-changed-no-reason.json" \
  > "${STAGE11_TMP_DIR}/draft-current.json"

stage11_expect 200 "${STAGE11_TMP_DIR}/saved-2.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

export STAGE11_REVISION_2="$(jq -r '.revision_number' "${STAGE11_TMP_DIR}/saved-2.json")"
test "${STAGE11_REVISION_2}" -eq "$((STAGE11_REVISION_1 + 1))"
```

### 9.5 浏览器传入总分必须被拒绝

执行位置：终端 D。

```bash
jq '.final_score = "999"' \
  "${STAGE11_TMP_DIR}/draft-current.json" \
  > "${STAGE11_TMP_DIR}/draft-with-browser-total.json"

stage11_expect 422 "${STAGE11_TMP_DIR}/browser-total-result.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-with-browser-total.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq -e '.detail.code == "request_validation_failed"' \
  "${STAGE11_TMP_DIR}/browser-total-result.json" >/dev/null
```

### 9.6 错误引文和未知文本块必须失败，草稿不能变化

执行位置：终端 D。

```bash
jq '.evidence[0].quote += "X"' \
  "${STAGE11_TMP_DIR}/draft-current.json" \
  > "${STAGE11_TMP_DIR}/draft-bad-quote.json"

stage11_expect 422 "${STAGE11_TMP_DIR}/bad-quote-result.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-bad-quote.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq -e '.detail.code == "review_evidence_quote_mismatch"' \
  "${STAGE11_TMP_DIR}/bad-quote-result.json" >/dev/null

jq '.evidence[0].block_id = "b999999"' \
  "${STAGE11_TMP_DIR}/draft-current.json" \
  > "${STAGE11_TMP_DIR}/draft-unknown-block.json"

stage11_expect 422 "${STAGE11_TMP_DIR}/unknown-block-result.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-unknown-block.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

jq -e '.detail.code == "review_evidence_block_unknown"' \
  "${STAGE11_TMP_DIR}/unknown-block-result.json" >/dev/null

stage11_expect 200 "${STAGE11_TMP_DIR}/review-after-invalid.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

test "$(jq -r '.draft.revision_number' "${STAGE11_TMP_DIR}/review-after-invalid.json")" \
  -eq "${STAGE11_REVISION_2}"
```

### 9.7 浏览器验证真实证据定位

执行位置：应用浏览器，教师 A。

1. 打开本批次第一篇论文的复核页。
2. 点击一条已有证据，页面必须滚动到正确文本块并出现可见焦点。
3. 在一个文本块内选择一段逐字英文原文，添加到明确的维度或扣分项；保存后刷新，证据仍绑定同一 `block_id` 且引文逐字不变。
4. 尝试跨两个文本块选择，页面必须明确拒绝，不能猜测或自动合并。
5. 不要在浏览器中确认；下一部分还要用这篇论文验证原模型重评。

## 十、原模型重评、快照和旧草稿隔离

### 10.1 明确接受一次额外模型费用

执行位置：终端 D。只有输入完整的 `REGRADING` 才会继续。

```bash
echo '这一步会产生 1 次真实原模型重评费用。输入 REGRADING 继续：'
read -r STAGE11_REGRADE_APPROVAL
test "${STAGE11_REGRADE_APPROVAL}" = 'REGRADING' || {
  echo '未确认费用，停止重评' >&2
  false
}
```

### 10.2 发起重评并等待新 attempt

执行位置：终端 D。

```bash
export STAGE11_ATTEMPT_BEFORE="$(
  jq -r '.attempt.id' "${STAGE11_TMP_DIR}/review-before.json"
)"

stage11_expect 200 "${STAGE11_TMP_DIR}/regrade-started.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review/regrade"

stage11_wait_for_regrade() {
  local stage11_item_ready='false'
  for stage11_poll in {1..60}; do
    stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-after-regrade.json" \
      -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
      "${STAGE11_API}/grading-jobs" || return 1
    stage11_item_ready="$(
      jq -r --arg job "${STAGE11_JOB_ID}" --arg item "${STAGE11_ITEM_ID}" \
        '.[] | select(.id == $job) | .items[] | select(.id == $item) |
         (.status == "needs_review" and .attempt_count >= 2)' \
        "${STAGE11_TMP_DIR}/jobs-after-regrade.json"
    )"
    [[ "${stage11_item_ready}" == 'true' ]] && return 0
    sleep 5
  done
  return 1
}

if stage11_wait_for_regrade; then
  stage11_expect 200 "${STAGE11_TMP_DIR}/review-after-regrade.json" \
    -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
    "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"

  export STAGE11_ATTEMPT_AFTER="$(
    jq -r '.attempt.id' "${STAGE11_TMP_DIR}/review-after-regrade.json"
  )"
  test "${STAGE11_ATTEMPT_AFTER}" != "${STAGE11_ATTEMPT_BEFORE}"
  jq -e '.draft == null' "${STAGE11_TMP_DIR}/review-after-regrade.json" >/dev/null
else
  echo '重评未在 5 分钟内回到 needs_review；检查终端 C，不要再次点击重评' >&2
  false
fi
```

`draft == null` 证明旧 attempt 的草稿没有误用于新 attempt。不要复用第九部分的旧草稿文件。

### 10.3 从新 attempt 重新生成当前草稿

执行位置：终端 D。

```bash
jq '{
  attempt_id: .attempt.id,
  criteria: [.attempt.dimensions[] |
    {dimension_id, score, reason, revision_suggestions}],
  deductions: [.attempt.deductions[] |
    {deduction_id, applied, reason}],
  evidence: (
    [.attempt.dimensions[] as $item | $item.evidence[] |
      {target_type: "dimension", target_id: $item.dimension_id, block_id, quote}]
    +
    [.attempt.deductions[] as $item | $item.evidence[] |
      {target_type: "deduction", target_id: $item.deduction_id, block_id, quote}]
  ),
  overall_feedback: .attempt.overall_feedback,
  change_reason: null
}' "${STAGE11_TMP_DIR}/review-after-regrade.json" \
  > "${STAGE11_TMP_DIR}/draft-current-attempt.json"
```

### 10.4 生成快照核对 SQL

执行位置：终端 D。该命令只生成 SQL 文件，不连接 Supabase。

```bash
./.venv/bin/python - <<'PY' > "${STAGE11_TMP_DIR}/regrade-check.sql"
import os
from uuid import UUID

item_id = UUID(os.environ["STAGE11_ITEM_ID"])
print(f"""
select item.id as item_id,
       job.provider_config_id,
       job.provider_config_version,
       job.model,
       job.rubric_version_id,
       job.prompt_version,
       encode(job.prompt_hash, 'hex') as prompt_hash,
       encode(job.model_parameters_hash, 'hex') as parameters_hash,
       attempt.id as attempt_id,
       attempt.attempt_number,
       attempt.scoring_round,
       attempt.status,
       attempt.reported_model
from public.grading_job_items as item
join public.grading_jobs as job on job.id = item.grading_job_id
join public.grading_attempts as attempt on attempt.grading_job_item_id = item.id
where item.id = '{item_id}'::uuid
order by attempt.attempt_number;
""")
PY

cat "${STAGE11_TMP_DIR}/regrade-check.sql"
```

执行位置：Supabase SQL Editor。手动复制终端 D 刚输出的完整 SQL，点击 Run。

预期至少两行 attempt；同一批次的 provider 配置版本、模型、Rubric、提示词和参数哈希不变；旧 attempt 仍存在，新 attempt 编号增加，两个结果都没有被覆盖。

## 十一、单篇并发确认和确认后不可变

### 11.1 保存新 attempt 草稿

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/current-attempt-saved.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"
```

### 11.2 同时发送两个相同确认请求

执行位置：终端 D。整段一次执行，不要拆开；两个请求会并发竞争同一论文。

```bash
curl -sS \
  -o "${STAGE11_TMP_DIR}/confirm-race-1.json" \
  -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review/confirm" \
  > "${STAGE11_TMP_DIR}/confirm-race-1.status" &
stage11_pid_1=$!

curl -sS \
  -o "${STAGE11_TMP_DIR}/confirm-race-2.json" \
  -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review/confirm" \
  > "${STAGE11_TMP_DIR}/confirm-race-2.status" &
stage11_pid_2=$!

wait "${stage11_pid_1}"
wait "${stage11_pid_2}"

./.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["STAGE11_TMP_DIR"])
statuses = [
    (root / "confirm-race-1.status").read_text().strip(),
    (root / "confirm-race-2.status").read_text().strip(),
]
if sorted(statuses) not in (["200", "200"], ["200", "409"]):
    raise SystemExit(f"并发确认状态不符合契约：{statuses}")
review_ids = set()
for index, status in enumerate(statuses, start=1):
    payload = json.loads((root / f"confirm-race-{index}.json").read_text())
    if status == "200":
        review_ids.add(payload["reviews"][0]["id"])
    elif payload.get("detail", {}).get("code") != "review_concurrent_conflict":
        raise SystemExit("409 必须是明确的并发冲突")
if len(review_ids) != 1:
    raise SystemExit("并发确认产生了多个 confirmed review")
print("并发确认结果确定，confirmed review 数量为 1")
PY
```

允许两种确定结果：两个请求都返回同一个确认结果，或一个成功、另一个明确并发冲突。禁止产生两个 confirmed review。

### 11.3 重复确认必须返回同一结果

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/confirm-repeat.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review/confirm"
```

手动核对：成功并发响应和重复响应中的 review ID 必须相同。

### 11.4 确认后保存、重评和跨教师写入必须失败

执行位置：终端 D。

```bash
stage11_expect 409 "${STAGE11_TMP_DIR}/save-after-confirm.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"
jq -e '.detail.code == "review_state_conflict"' \
  "${STAGE11_TMP_DIR}/save-after-confirm.json" >/dev/null

stage11_expect 409 "${STAGE11_TMP_DIR}/regrade-after-confirm.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review/regrade"
jq -e '.detail.code == "review_state_conflict"' \
  "${STAGE11_TMP_DIR}/regrade-after-confirm.json" >/dev/null

stage11_expect 404 "${STAGE11_TMP_DIR}/teacher-b-save.json" \
  -X PUT \
  -H "Authorization: Bearer ${STAGE11_TEACHER_B_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/draft-current-attempt.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/items/${STAGE11_ITEM_ID}/review"
jq -e '.detail.code == "review_not_found"' \
  "${STAGE11_TMP_DIR}/teacher-b-save.json" >/dev/null
```

执行位置：应用浏览器。刷新第一篇论文，必须显示只读确认结果；保存和重评按钮不可继续执行。

## 十二、错误批量全失败、正确批量全成功

### 12.1 为剩余两篇保存合法草稿

执行位置：应用浏览器，教师 A。

1. 返回本批次队列。
2. 逐篇打开剩余两篇 `needs_review` 论文。
3. 不修改时可以直接保存 AI 原结果；修改任何维度、扣分、理由、证据或反馈时必须填写修改原因。
4. 两篇都必须显示“草稿已保存”，不要单篇确认。

### 12.2 从最新列表生成批量引用

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-before-batch.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs"

jq --arg job "${STAGE11_JOB_ID}" '{reviews: [
  .[] | select(.id == $job) | .items[]
  | select(.status == "needs_review" and .review_status == "draft")
  | {item_id: .id, review_id: .review_id, revision_number: .review_revision}
]}' "${STAGE11_TMP_DIR}/jobs-before-batch.json" \
  > "${STAGE11_TMP_DIR}/batch-current.json"

jq -e '.reviews | length == 2' "${STAGE11_TMP_DIR}/batch-current.json" >/dev/null
```

如果不是 2，停止并回浏览器检查；不要跳过未保存或异常论文。

### 12.3 教师 B 的批量写入也必须不可见

执行位置：终端 D。

```bash
stage11_expect 404 "${STAGE11_TMP_DIR}/teacher-b-batch.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_B_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/batch-current.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/reviews/batch-confirm"
jq -e '.detail.code == "review_not_found"' \
  "${STAGE11_TMP_DIR}/teacher-b-batch.json" >/dev/null
```

### 12.4 制造一个过期修订号，整批必须失败

执行位置：终端 D。

```bash
jq '.reviews[0].revision_number += 1' \
  "${STAGE11_TMP_DIR}/batch-current.json" \
  > "${STAGE11_TMP_DIR}/batch-stale.json"

jq --arg job "${STAGE11_JOB_ID}" \
  '[.[] | select(.id == $job) | .items[]
    | select(.status == "needs_review")
    | {id, status, review_id, review_revision, review_status}]' \
  "${STAGE11_TMP_DIR}/jobs-before-batch.json" \
  > "${STAGE11_TMP_DIR}/batch-state-before.json"

stage11_expect 409 "${STAGE11_TMP_DIR}/batch-stale-result.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/batch-stale.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/reviews/batch-confirm"
jq -e '.detail.code == "review_concurrent_conflict"' \
  "${STAGE11_TMP_DIR}/batch-stale-result.json" >/dev/null

stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-after-bad-batch.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs"

jq --arg job "${STAGE11_JOB_ID}" \
  '[.[] | select(.id == $job) | .items[]
    | select(.status == "needs_review")
    | {id, status, review_id, review_revision, review_status}]' \
  "${STAGE11_TMP_DIR}/jobs-after-bad-batch.json" \
  > "${STAGE11_TMP_DIR}/batch-state-after.json"

cmp "${STAGE11_TMP_DIR}/batch-state-before.json" \
    "${STAGE11_TMP_DIR}/batch-state-after.json"
```

`cmp` 无输出且退出成功，证明坏数据没有导致部分确认。

### 12.5 提交正确批量并完成批次

执行位置：终端 D。

```bash
stage11_expect 200 "${STAGE11_TMP_DIR}/batch-confirmed.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/batch-current.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/reviews/batch-confirm"

jq -e --arg job "${STAGE11_JOB_ID}" \
  '.completed_job_ids | index($job) != null' \
  "${STAGE11_TMP_DIR}/batch-confirmed.json" >/dev/null

stage11_expect 200 "${STAGE11_TMP_DIR}/batch-repeat.json" \
  -X POST \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${STAGE11_TMP_DIR}/batch-current.json" \
  "${STAGE11_API}/grading-jobs/${STAGE11_JOB_ID}/reviews/batch-confirm"

stage11_expect 200 "${STAGE11_TMP_DIR}/jobs-completed.json" \
  -H "Authorization: Bearer ${STAGE11_TEACHER_A_TOKEN}" \
  "${STAGE11_API}/grading-jobs"

jq -e --arg job "${STAGE11_JOB_ID}" \
  '.[] | select(.id == $job)
   | .status == "completed"
     and .completed == .total
     and .needs_review == 0
     and .finished_at != null' \
  "${STAGE11_TMP_DIR}/jobs-completed.json" >/dev/null
```

正确批量重复提交必须返回同一组确认结果，不产生重复 confirmed review 或重复审计。

## 十三、最终 Supabase 数据核对

### 13.1 生成只针对本批次的 SQL

执行位置：终端 D。

```bash
./.venv/bin/python - <<'PY' > "${STAGE11_TMP_DIR}/final-check.sql"
import os
from uuid import UUID

job_id = UUID(os.environ["STAGE11_JOB_ID"])
print(f"""
select job.status,
       job.finished_at,
       count(*) filter (where item.status = 'completed') as completed_items,
       count(*) as total_items
from public.grading_jobs as job
join public.grading_job_items as item on item.grading_job_id = job.id
where job.id = '{job_id}'::uuid
group by job.id;

select review.status, count(*)
from public.teacher_reviews as review
where review.grading_job_item_id in (
  select id
  from public.grading_job_items
  where grading_job_id = '{job_id}'::uuid
)
group by review.status
order by review.status;

select count(*) as confirmed_review_rows,
       count(distinct grading_job_item_id) as confirmed_items,
       count(distinct grading_attempt_id) as confirmed_attempts
from public.teacher_reviews
where status = 'confirmed'
  and grading_job_item_id in (
    select id
    from public.grading_job_items
    where grading_job_id = '{job_id}'::uuid
  );

select count(*) as confirmation_audit_rows
from public.audit_logs
where action = 'teacher_review.confirmed'
  and resource_id in (
    select review.id
    from public.teacher_reviews as review
    where review.grading_job_item_id in (
      select id
      from public.grading_job_items
      where grading_job_id = '{job_id}'::uuid
    )
  );

select item.id,
       item.status,
       count(distinct attempt.id) as attempt_rows,
       count(distinct review.id) filter (where review.status = 'confirmed')
         as confirmed_reviews
from public.grading_job_items as item
left join public.grading_attempts as attempt
  on attempt.grading_job_item_id = item.id
left join public.teacher_reviews as review
  on review.grading_job_item_id = item.id
where item.grading_job_id = '{job_id}'::uuid
group by item.id, item.status
order by item.position;
""")
PY

cat "${STAGE11_TMP_DIR}/final-check.sql"
```

### 13.2 在 Supabase SQL Editor 执行生成结果

执行位置：Supabase SQL Editor。手动复制终端 D 的完整输出，点击 Run。

预期：

- 批次是 `completed`，`finished_at` 非空，3/3 item 为 `completed`；
- confirmed review、confirmed item、confirmed attempt 均为 3；
- `teacher_review.confirmed` 审计恰好 3 行；
- 第一篇至少 2 个 attempt，另两篇至少 1 个；
- 每篇恰好 1 个 confirmed review。

不要把包含论文正文或反馈的行展开后发到聊天。

## 十四、真实浏览器桌面与手机验收

所有检查使用应用浏览器，教师 A。先打开开发者工具 Console，清空旧日志，再刷新页面。

### 14.1 桌面布局

手动操作：浏览器窗口设为约 `1440 × 900`，打开 `/grading-jobs`。

1. 页面直接列出教师自己的批次、进度、论文名和状态，不要求 UUID。
2. 打开一个复核任务后，左侧是论文队列，中间是英文规范文本和证据，右侧是 Rubric、扣分、分数、英文反馈、证据、修改原因和操作。
3. 已完成批次保持可读，确认结果不可编辑。
4. 加载、空数据、失败、401 和 409 都有明确文案；“重试”不会创建新批次。
5. 切换中文和英文，列表、三栏、按钮、冲突和空状态都完整翻译。

### 14.2 手机布局

手动操作：开发者工具打开设备模式，尺寸设为 `390 × 844`，刷新同一复核页。

1. 页面使用论文队列、论文正文、评分复核三个可切换标签或清晰纵向步骤，不压缩成三条窄栏。
2. 保存草稿、证据定位、修改原因、重评、单篇确认和批量确认入口仍能操作。
3. 页面没有横向溢出，正文和按钮不被遮挡。

### 14.3 键盘、焦点和控制台

手动操作：分别在桌面和手机设备模式完成。

1. 用 `Tab` 和 `Shift+Tab` 走完论文队列、语言切换、证据、表单和操作按钮。
2. 标签页可用方向键切换；焦点始终清晰可见。
3. 点击证据后，正确文本块获得可见焦点，不只滚动位置。
4. Console 的错误为 0、警告为 0。

若 Console 的来源或调用栈是 `chrome-extension://`，它属于浏览器扩展而不是本项目。关闭该扩展、清空 Console 并重新刷新；只有项目页面和 `127.0.0.1` 脚本的错误与警告均为 0，才能通过本项，不能用过滤器隐藏项目自身错误。

## 十五、结束进程和清理本地敏感临时文件

### 15.1 停止长期进程

手动操作：依次切到终端 C、B、A，各按一次 `Control+C`，等提示符返回。

若第 6.6 节曾临时开启 VPN fake-IP 例外，在终端 C 提示符返回后立即执行：

```bash
export ALLOW_OFFICIAL_PROVIDER_FAKE_IP=false
unset ALLOW_OFFICIAL_PROVIDER_FAKE_IP
```

不要把 `true` 写入生产环境或保留到下一次 Worker 启动。

### 15.2 清除当前终端令牌和临时目录

执行位置：终端 D。下面只删除本次由 `mktemp` 创建且路径符合固定前缀的目录。

```bash
unset STAGE11_TEACHER_A_TOKEN STAGE11_TEACHER_B_TOKEN
unset STAGE11_TEACHER_A_ID STAGE11_TEACHER_B_ID
unset STAGE11_JOB_ID STAGE11_ITEM_ID
unset STAGE11_ATTEMPT_BEFORE STAGE11_ATTEMPT_AFTER
unset STAGE11_REGRADE_APPROVAL

case "${STAGE11_TMP_DIR}" in
  /tmp/paper-grading-stage11.*)
    rm -rf -- "${STAGE11_TMP_DIR}"
    ;;
  *)
    echo '临时目录路径不符合固定前缀，未删除' >&2
    false
    ;;
esac
unset STAGE11_TMP_DIR STAGE11_API
```

## 十六、只回传安全结果

只回传下列摘要：

- 本地自动化通过/失败数量；
- 真实 PostgreSQL 通过/失败数量和最终迁移版本；
- 迁移前后四张表计数是否完全一致；
- 权限、双教师隔离、真实证据、草稿修订、服务器总分、修改原因、重评、单篇并发确认、错误批量、正确批量各自通过或失败；
- 桌面、`390 × 844` 手机、键盘焦点、中英文和 Console 各自通过或失败；
- 最终批次状态和 confirmed review 数量。

不要回传 Token、密码、Secret Key、签名 URL、论文正文、完整反馈、模型原始响应、对象路径或请求 ID。

用户已于 2026-07-22 明确确认上述真实验收成功，阶段 11 状态已改为“完成”，阶段 12 可以开始开发。
