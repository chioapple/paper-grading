# 阶段 12 验收：Excel 导出

当前状态：已完成。用户于 2026-07-26 明确确认本文档全部步骤执行通过，包括本地门禁、隔离数据库回归、真实 `20260722_0017` 前向迁移、权限与双教师隔离、草稿/最终导出、租约恢复、私有 Storage、真实 Excel 客户端和连接真实后端的桌面/手机浏览器验收。真实项目存在 `exports` 或 `export_items` 数据后继续禁止为验收回退。

## 1. 本地门禁

执行位置：终端，项目根目录。先确认项目虚拟环境已经安装 `pyproject.toml` 声明的 Excel 依赖。

```bash
(
set -euo pipefail
cd '/Users/a1-6/Documents/Paper Grading/backend'
../.venv/bin/python -c 'import openpyxl; print(openpyxl.__version__)'
../.venv/bin/python -m pytest -q
../.venv/bin/ruff check app tests scripts
../.venv/bin/ruff format --check app tests scripts
../.venv/bin/mypy app tests scripts

cd '/Users/a1-6/Documents/Paper Grading/frontend'
npm test -- --run
npm run lint
npm run typecheck
npm run build

cd '/Users/a1-6/Documents/Paper Grading'
STAGE12_OFFLINE_DIR=$(mktemp -d /private/tmp/stage12-offline.XXXXXX)
trap 'rm -rf "$STAGE12_OFFLINE_DIR"' EXIT
cd backend
MIGRATION_DATABASE_URL='postgresql+asyncpg://user@db.example.supabase.co:5432/postgres?ssl=require' \
  ../.venv/bin/alembic -c alembic.ini upgrade 20260722_0017 --sql \
  > "$STAGE12_OFFLINE_DIR/upgrade.sql"
MIGRATION_DATABASE_URL='postgresql+asyncpg://user@db.example.supabase.co:5432/postgres?ssl=require' \
  ../.venv/bin/alembic -c alembic.ini downgrade 20260722_0017:20260721_0016 --sql \
  > "$STAGE12_OFFLINE_DIR/downgrade.sql"
MIGRATION_DATABASE_URL='postgresql+asyncpg://user@db.example.supabase.co:5432/postgres?ssl=require' \
  ../.venv/bin/alembic -c alembic.ini upgrade 20260722_0017 --sql \
  > "$STAGE12_OFFLINE_DIR/reupgrade.sql"
test -s "$STAGE12_OFFLINE_DIR/upgrade.sql"
test -s "$STAGE12_OFFLINE_DIR/downgrade.sql"
test -s "$STAGE12_OFFLINE_DIR/reupgrade.sql"

cd '/Users/a1-6/Documents/Paper Grading'
git diff --check
while IFS= read -r -d '' STAGE12_NEW_FILE; do
  STAGE12_CHECK=$(git diff --no-index --check /dev/null "$STAGE12_NEW_FILE" || true)
  test -z "$STAGE12_CHECK"
done < <(git ls-files --others --exclude-standard -z)
! git diff -- . | \
  grep -E '(sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]{40,}|SUPABASE_SECRET_KEY=[A-Za-z0-9._-]{40,}|PROVIDER_MASTER_KEY=[A-Za-z0-9._-]{40,})'
! git ls-files --others --exclude-standard -z | xargs -0 grep -Il . | xargs grep -E \
  '(sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]{40,}|SUPABASE_SECRET_KEY=[A-Za-z0-9._-]{40,}|PROVIDER_MASTER_KEY=[A-Za-z0-9._-]{40,})'
)
```

普通 pytest 必须显示 PostgreSQL marker 被排除。工作簿测试必须重开文件，证明四个工作表、100 篇逐表行数和顺序、Decimal 数值、公式前缀、无外部链接、同一快照字节一致、超长组合文本失败。测试失败立即停止。

## 2. 隔离测试库回放和真实数据库契约

执行位置：终端。只允许连接可删除阶段 12 数据的独立 Supabase 测试项目；该测试会执行 `0016 → 0017 → 0016 → 0017`。

```bash
(
  set -euo pipefail
  cd '/Users/a1-6/Documents/Paper Grading'
  set -a
  source .env.stage7-local
  set +a

  printf '测试项目 ref: '
  IFS= read -r TEST_SUPABASE_PROJECT_REF
  stage12_read_secret() {
    printf '%s' "$1"
    trap 'stty echo; printf "\n"' INT TERM
    stty -echo
    IFS= read -r REPLY
    stty echo
    trap - INT TERM
    printf '\n'
  }
  stage12_read_secret '测试库 direct URL: '
  TEST_MIGRATION_DATABASE_URL=$REPLY
  stage12_read_secret '测试库 session pooler URL: '
  TEST_DATABASE_URL=$REPLY
  unset REPLY
  printf '测试教师 Auth UUID: '
  IFS= read -r TEST_TEACHER_AUTH_USER_ID
  printf '另一教师 Auth UUID: '
  IFS= read -r TEST_OTHER_AUTH_USER_ID

  printf '%s\n' "$TEST_TEACHER_AUTH_USER_ID" | \
    grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-4[0-9A-Fa-f]{3}-[89AaBb][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}$'
  printf '%s\n' "$TEST_OTHER_AUTH_USER_ID" | \
    grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-4[0-9A-Fa-f]{3}-[89AaBb][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}$'
  test "$TEST_TEACHER_AUTH_USER_ID" != "$TEST_OTHER_AUTH_USER_ID"

  export TEST_SUPABASE_PROJECT_REF TEST_MIGRATION_DATABASE_URL TEST_DATABASE_URL
  export TEST_TEACHER_AUTH_USER_ID TEST_OTHER_AUTH_USER_ID
  ./.venv/bin/python - <<'PY'
import os
from urllib.parse import urlsplit

project_ref = os.environ["TEST_SUPABASE_PROJECT_REF"]
supabase = urlsplit(os.environ["SUPABASE_URL"])
direct = urlsplit(os.environ["TEST_MIGRATION_DATABASE_URL"])
pooler = urlsplit(os.environ["TEST_DATABASE_URL"])
assert supabase.hostname == f"{project_ref}.supabase.co"
assert direct.hostname == f"db.{project_ref}.supabase.co"
assert pooler.username and pooler.username.endswith(f".{project_ref}")
PY
  export TEST_DATABASE_RESET_CONFIRMATION=I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA
  cd backend
  ../.venv/bin/python -m pytest -q -m postgres tests/test_stage12_postgres_contract.py
)
```

定向测试必须通过：迁移回放、函数和表权限、独立 Worker 禁止读取评分来源表、模型参数冻结、草稿来源快照、同请求复用、不同请求冲突、跨教师列表/详情/创建/下载隔离、双领取拒绝、错误令牌拒绝和当前令牌完成。失败时停止，不改真实项目。

## 3. 真实项目只做前向迁移

执行位置：终端。先停止 API、评分 Worker、维护 Worker和导出 Worker。

```bash
(
  set -euo pipefail
  cd '/Users/a1-6/Documents/Paper Grading'
  set -a
  source .env.stage7-local
  set +a
  stage12_read_secret() {
    printf '%s' "$1"
    trap 'stty echo; printf "\n"' INT TERM
    stty -echo
    IFS= read -r REPLY
    stty echo
    trap - INT TERM
    printf '\n'
  }
  stage12_read_secret '真实项目 direct MIGRATION_DATABASE_URL: '
  MIGRATION_DATABASE_URL=$REPLY
  unset REPLY
  printf '真实项目 ref: '
  IFS= read -r STAGE12_PROJECT_REF
  export MIGRATION_DATABASE_URL STAGE12_PROJECT_REF
  ./.venv/bin/python - <<'PY'
import os
from urllib.parse import urlsplit

project_ref = os.environ["STAGE12_PROJECT_REF"]
assert urlsplit(os.environ["SUPABASE_URL"]).hostname == f"{project_ref}.supabase.co"
assert urlsplit(os.environ["MIGRATION_DATABASE_URL"]).hostname == f"db.{project_ref}.supabase.co"
PY
  cd backend
  test "$(../.venv/bin/alembic -c alembic.ini current | tr -d '\r')" = '20260721_0016'
  ../.venv/bin/alembic -c alembic.ini upgrade 20260722_0017
  ../.venv/bin/alembic -c alembic.ini current | grep -F '20260722_0017 (head)'
)
```

真实项目不执行 downgrade。迁移失败立即停止并保留原始错误。

执行位置：Supabase SQL Editor。迁移创建的 `paper_grading_export_worker` 是可登录但没有初始密码的最小角色。使用本地密码管理器生成新的高强度密码，在 SQL Editor 中只为该角色执行一次 `ALTER ROLE ... PASSWORD ...`；密码不得发到聊天、提交到仓库或复用 postgres 密码。随后把该角色的 Supavisor session pooler 5432 地址保存为本机 `EXPORT_DATABASE_URL`；用户名必须是 `paper_grading_export_worker.<project-ref>`，并显式带 `ssl=require`。Render 的导出服务也只注入此变量，不注入通用 `DATABASE_URL`。

## 4. 启动全部本地进程

执行位置：终端 A。先确认 Redis 和当前进程，已有健康进程不重复启动。

```bash
redis-cli -u redis://127.0.0.1:6379/0 ping
pgrep -fl 'uvicorn|app.workers.supervisor|app.export.celery_app|vite' || true
```

执行位置：终端 A。启动评分 supervisor 前先做只读费用门禁。输出必须为 `0`；非零时停止，只有教师明确同意这些真实模型费用后才能启动 supervisor。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
cd backend
../.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from app.config import Settings
from app.db import Database

async def main() -> None:
    database = Database.from_settings(Settings.load())
    try:
        async with database.engine.connect() as connection:
            count = await connection.scalar(text(
                "select count(*) from grading_job_items "
                "where status in ('queued', 'running')"
            ))
            print(count)
    finally:
        await database.dispose()

asyncio.run(main())
PY
```

执行位置：终端 B，FastAPI。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
cd backend
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

执行位置：终端 C，健康检查。

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health/live
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready
```

执行位置：终端 D。只在费用门禁为 0 或教师明确授权现有排队任务费用后启动评分/维护 supervisor。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
cd backend
../.venv/bin/python -m app.workers.supervisor
```

执行位置：终端 E，独立导出 Worker；该进程显式移除供应商主密钥。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
test -n "$EXPORT_DATABASE_URL"
unset PROVIDER_MASTER_KEY
cd backend
../.venv/bin/celery -A app.export.celery_app:celery_app worker \
  --loglevel=INFO --concurrency=1 --queues=paper_grading.exports \
  --hostname=exports@%h
```

执行位置：终端 F，Vite。

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
cd frontend
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000}" \
VITE_SUPABASE_URL="$VITE_SUPABASE_URL" \
VITE_SUPABASE_PUBLISHABLE_KEY="$VITE_SUPABASE_PUBLISHABLE_KEY" \
npm run dev -- --host 127.0.0.1
```

## 5. 真实 API、幂等和双教师隔离

执行位置：终端 C。先在浏览器或本机登录脚本取得两个真实教师 Token，并选择教师 A 自己的可复核批次。所有响应保存在本次 `mktemp` 目录，先断言 HTTP 状态再解析。

```bash
(
set -euo pipefail
STAGE12_TMP_DIR=$(mktemp -d /private/tmp/stage12-acceptance.XXXXXX)
chmod 700 "$STAGE12_TMP_DIR"
trap 'unset STAGE12_TOKEN_A STAGE12_TOKEN_B; rm -rf "$STAGE12_TMP_DIR"' EXIT

stage12_read_secret() {
  printf '%s' "$1"
  trap 'stty echo; printf "\n"' INT TERM
  stty -echo
  IFS= read -r REPLY
  stty echo
  trap - INT TERM
  printf '\n'
}
stage12_read_secret '教师 A access token: '
STAGE12_TOKEN_A=$REPLY
stage12_read_secret '教师 B access token: '
STAGE12_TOKEN_B=$REPLY
unset REPLY
printf '教师 A grading job UUID: '
IFS= read -r STAGE12_JOB_A
printf '%s\n' "$STAGE12_JOB_A" | \
  grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-4[0-9A-Fa-f]{3}-[89AaBb][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}$'

STAGE12_KEY="stage12-$(uuidgen | tr '[:upper:]' '[:lower:]')"
STAGE12_BODY=$(printf '{"grading_job_id":"%s","export_type":"draft"}' "$STAGE12_JOB_A")
STAGE12_STATUS=$(curl --silent --show-error \
  --output "$STAGE12_TMP_DIR/create.json" --write-out '%{http_code}' \
  -X POST http://127.0.0.1:8000/exports \
  -H "Authorization: Bearer $STAGE12_TOKEN_A" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $STAGE12_KEY" --data "$STAGE12_BODY")
test "$STAGE12_STATUS" = 201
STAGE12_EXPORT_ID=$(jq -er '.id' "$STAGE12_TMP_DIR/create.json")

STAGE12_STATUS=$(curl --silent --show-error \
  --output "$STAGE12_TMP_DIR/repeat.json" --write-out '%{http_code}' \
  -X POST http://127.0.0.1:8000/exports \
  -H "Authorization: Bearer $STAGE12_TOKEN_A" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $STAGE12_KEY" --data "$STAGE12_BODY")
test "$STAGE12_STATUS" = 200
test "$(jq -er '.id' "$STAGE12_TMP_DIR/repeat.json")" = "$STAGE12_EXPORT_ID"

STAGE12_CONFLICT=$(printf '{"grading_job_id":"%s","export_type":"final"}' "$STAGE12_JOB_A")
STAGE12_STATUS=$(curl --silent --show-error \
  --output "$STAGE12_TMP_DIR/conflict.json" --write-out '%{http_code}' \
  -X POST http://127.0.0.1:8000/exports \
  -H "Authorization: Bearer $STAGE12_TOKEN_A" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $STAGE12_KEY" --data "$STAGE12_CONFLICT")
test "$STAGE12_STATUS" = 409

STAGE12_STATUS=$(curl --silent --show-error \
  --output "$STAGE12_TMP_DIR/list-b.json" --write-out '%{http_code}' \
  -H "Authorization: Bearer $STAGE12_TOKEN_B" http://127.0.0.1:8000/exports)
test "$STAGE12_STATUS" = 200
jq -e --arg id "$STAGE12_EXPORT_ID" 'all(.[]; .id != $id)' "$STAGE12_TMP_DIR/list-b.json"

for STAGE12_PATH in "/exports/$STAGE12_EXPORT_ID" "/exports/$STAGE12_EXPORT_ID/download"; do
  STAGE12_STATUS=$(curl --silent --show-error \
    --output "$STAGE12_TMP_DIR/cross.json" --write-out '%{http_code}' \
    -X "$(test "$STAGE12_PATH" = "/exports/$STAGE12_EXPORT_ID/download" && printf POST || printf GET)" \
    -H "Authorization: Bearer $STAGE12_TOKEN_B" \
    "http://127.0.0.1:8000$STAGE12_PATH")
  test "$STAGE12_STATUS" = 404
done

STAGE12_STATUS=$(curl --silent --show-error \
  --output "$STAGE12_TMP_DIR/cross-create.json" --write-out '%{http_code}' \
  -X POST http://127.0.0.1:8000/exports \
  -H "Authorization: Bearer $STAGE12_TOKEN_B" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: other-$(uuidgen)" --data "$STAGE12_BODY")
test "$STAGE12_STATUS" = 404
printf 'stage12_export_id=%s\n' "$STAGE12_EXPORT_ID"
)
```

## 6. 草稿、最终、Worker 丢失和私有 Storage

执行位置：浏览器、终端 E 和 Supabase 控制台，按顺序执行。

1. 草稿批次必须实际包含 `ai_suggestion`、`teacher_draft`、`teacher_confirmed` 三种来源；创建响应和列表中的 `source_counts` 与真实每篇来源一致。创建后修改教师草稿，再下载原导出，原文件的 review ID、revision 和内容不得改变。
2. 对任一未确认论文的批次，前端最终导出按钮必须禁用；直接 API 请求必须返回拒绝。全部确认且批次为 `completed` 后，用新幂等键创建最终导出并成功，任何论文都不得回退到草稿或 AI。
3. 同时投递同一 export ID 两次，只能一个 Worker 从 queued 进入 running。终止终端 E 的 Worker，等待 600 秒租约过期后重启并重新投递；必须复用相同字节和 SHA-256 的固定对象。旧 Worker 令牌不得完成或失败新领取。
4. 模拟 Storage 拒绝上传时，导出必须为 `failed/export_storage_failed`，不能 completed。上传后若数据库完成失败，只有数据库仍能用该领取令牌原子标记 failed 时才允许按相同 SHA-256 删除；新 Worker 已领取或完成时旧 Worker不得删除。
5. Supabase Storage 桶保持私有；浏览器直接列目录失败。对象路径只含 `exports/<export UUID>/workbook.xlsx`，上传禁止覆盖。API、日志和浏览器响应均不得出现 object key、文件哈希、Token、Key 或内部数据库错误。
6. completed 导出调用 `POST /exports/{id}/download`，只返回短时 URL、到期秒数和安全文件名。URL 过期后再次调用下载接口，不创建新 export。

Supabase SQL Editor 只读核验：教师角色不能直接 INSERT/UPDATE/DELETE `exports` 或 `export_items`；`authenticated`、`service_role` 和 `PUBLIC` 不能执行创建、领取、完成、失败函数；导出 Worker 不能读取 provider、assignment、submission、attempt 或 review 来源表。

## 7. Excel 客户端

执行位置：Microsoft Excel 或 LibreOffice。

1. 分别打开草稿和最终文件，顺序必须为 `Summary`、`Criteria`、`Feedback`、`Metadata`；100 篇时三个明细表都无漏卷、重复、重排或跨论文错配。
2. 草稿顶部和每篇均显示“非最终成绩”；最终文件显示“教师已确认”。数值可计算，最多 4 位小数，重开总分与数据库 Decimal 一致。
3. `Criteria` 区分 dimension/deduction，保留固定 ID、英文理由和 evidence block ID。`Feedback` 不含论文正文或模型原始响应。
4. `Metadata` 包含导出/批次/Rubric/模型/提示词/参数哈希/attempt/review/revision/时间，ID 和纯数字哈希按文本显示；不得含密钥、费用、对象路径、文件哈希或原始响应。
5. 分别用 `=`, `+`, `-`, `@`、制表符、回车、换行开头的文件名、作业标题、Rubric 名称和教师反馈做负向测试；重开后必须为文本，无公式、DDE 和外部链接。NUL、非法 XML 控制字符、孤立代理字符、单字段或组合后超过 32767 字符必须整批失败，不能截断、删除、替换或跳过。

## 8. 桌面和手机浏览器

执行位置：浏览器开发者工具。

1. 桌面从 `/grading-jobs` 进入 `/exports?jobId=...`，检查创建说明、准确来源数量、草稿/最终选择、轮询、失败、下载和空状态。
2. 切换中文和英文；只用键盘完成选择和创建，焦点清晰，加载、成功、失败状态能被辅助技术读取。
3. 设为 `390 × 844`，确认无横向溢出、裁切或不可达按钮。
4. 分别验证 401、403、404、409、失败导出和下载地址过期后重新请求。
5. 桌面和手机检查期间，应用自身 Console 错误 0、警告 0。

## 9. 收尾

执行位置：终端。停止终端 B、D、E、F 的本次进程；终端 C 的子 Shell 结束后，确认 `STAGE12_TOKEN_A`、`STAGE12_TOKEN_B` 在当前 Shell 中均为空，且其自动创建的临时目录已经不存在。保留数据库导出历史和私有 Storage 文件，不为验收删除真实记录。

只有本地门禁、隔离数据库回归、真实前向迁移、权限/双教师、草稿/最终、租约恢复、私有 Storage、Excel 客户端和桌面/手机浏览器均由用户确认后，阶段 12 才能标记完成。

用户已于 2026-07-26 明确确认上述全部步骤执行通过，阶段 12 状态已改为“完成”，项目开发入口切换到阶段 13。
