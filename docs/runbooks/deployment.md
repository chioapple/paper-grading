# 部署 Runbook

## 安全边界

- Render Worker 与 Key Value 会计费；只有用户明确确认后才能创建。
- `autoDeployTrigger` 全部关闭，CI 失败不会触发部署。
- 生产数据库只允许前向迁移，不执行 downgrade。
- 自动清理、备份创建和备份清理保持关闭。
- 部署前必须保存当前数据库迁移版本、各服务成功构建 ID 和前端版本；不得保存密钥。
- API、两个 Worker 和前端必须部署同一个已通过 CI 的 commit SHA，不能手动选择其他提交。
- 首次创建 Render Blueprint 时，API 和 Worker 的 Redis 引用要求 Key Value 已存在。付费授权后的资源预置属于发布前准备，Worker 保持 Suspend 且不承载业务；下方固定顺序是版本发布与健康验证顺序，第 3 步不是首次创建 Redis。
- 发布前必须记录一个已在 `0019`、专用 Worker 数据库角色和精简环境变量下通过健康检查的 `STAGE14_ROLLBACK_SHA`。没有该证据时不得假定旧构建可回滚；失败后保持 Suspend 并走前向修复。

## 发布提交门禁

执行终端：本机项目根目录与 GitHub Actions。
前置条件：待发布改动已由用户按正式 Git 流程提交并推送；工作树干净。
预期结果：本地 HEAD、GitHub CI 成功 run 和 Render “Deploy a specific commit” 三处 SHA 完全一致。
安全回传：commit SHA 和 CI run URL；不回传环境变量。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
git diff --quiet
git diff --cached --quiet
test -z "$(git status --porcelain)"
STAGE14_RELEASE_SHA=$(git rev-parse HEAD)
test -n "$STAGE14_RELEASE_SHA"
test -n "${STAGE14_ROLLBACK_SHA:?missing verified rollback SHA}"
```

在 GitHub 确认该 SHA 的 CI 全部成功后，Render 每个服务都选择 “Deploy a specific commit”，并粘贴同一 SHA。任一服务无法选择该 SHA时停止部署。

## 固定顺序

### 1. 数据库迁移

执行终端：本机项目根目录。
前置条件：CI 全绿；用户已授权生产变更；API 和 Worker 已停止；`MIGRATION_DATABASE_URL` 是 Supabase 直连地址。
预期结果：只前向升级到 `20260728_0019`，版本核对成功；该迁移只开放既有最小评分 Worker 角色登录、私有 schema 使用权和两个 Storage 配额函数执行权，不增加表权限，也不写入密码。
安全回传：只回传最终 revision 和命令退出码。

```bash
cd "/Users/a1-6/Documents/Paper Grading/backend"
test -n "${MIGRATION_DATABASE_URL:?missing MIGRATION_DATABASE_URL}"
../.venv/bin/alembic upgrade 20260728_0019
../.venv/bin/alembic current
```

### 2. API

执行终端：Render Dashboard。
前置条件：迁移成功；API 环境变量已按 `infra/render.yaml` 配置；正式前端来源唯一；选择已记录的 `STAGE14_RELEASE_SHA`。
预期结果：API 部署成功，`/health/live` 与 `/health/ready` 均为 200。
安全回传：服务名、构建 ID、两个状态码；不回传响应头中的敏感值。

### 3. Redis

执行终端：Render Dashboard。
前置条件：用户已确认 Starter Key Value 费用；公网访问列表为空；策略为 `noeviction`。
预期结果：已预置的连接可用，三个队列起始长度已记录；禁止 `FLUSHALL`/`FLUSHDB`。
安全回传：资源名、区域、队列长度，不回传连接字符串。

### 4. 评分与维护 Worker

执行终端：受控 `psql` 终端与 Render Dashboard。
前置条件：API ready、Redis 可用；用户已授权生产角色密码写入；在仓库外准备权限为 `0600` 的 `MIGRATION_PGSERVICEFILE`，其中 `paper_grading_migration` 服务使用 direct 连接和独立 passfile；准备密码管理器生成的强随机密码。
预期结果：专用角色数据库连接与最小权限探针通过；`grading@`、`maintenance@` 心跳可见，只消费各自队列；一次不调用模型的过期任务维护调用明确成功。
安全回传：固定探针通过标记、Worker 名称、心跳和维护任务成功/失败；不回传数据库 URL、任务参数或业务计数。

```bash
test -f "${MIGRATION_PGSERVICEFILE:?missing migration service file}"
PGSERVICEFILE="$MIGRATION_PGSERVICEFILE" \
  PGSERVICE=paper_grading_migration \
  psql
```

进入 `psql` 后执行 `\password paper_grading_worker`，在隐藏提示中输入密码，然后执行 `\q`。把 `paper_grading_worker.<project-ref>` 的 Supavisor Session Pooler 5432 地址仅粘贴到评分 Worker 的 `DATABASE_URL` Secret。密码不得写入文件、命令参数、终端历史或回传内容。

在仓库外准备权限为 `0600` 的 `GRADING_WORKER_PGSERVICEFILE`，其中 `paper_grading_worker` 服务使用与 Render 相同的 Session Pooler 角色和独立 passfile；运行只返回固定标记的权限探针。验收结束后销毁临时 service/passfile：

```bash
test -f "${GRADING_WORKER_PGSERVICEFILE:?missing worker service file}"
PGSERVICEFILE="$GRADING_WORKER_PGSERVICEFILE" \
  PGSERVICE=paper_grading_worker \
  psql -X --set ON_ERROR_STOP=1 --quiet <<'SQL'
select (
  current_user = 'paper_grading_worker'
  and has_schema_privilege(
    current_user, 'paper_grading_private', 'usage'
  )
  and has_table_privilege(
    current_user, 'public.grading_jobs', 'select'
  )
  and has_table_privilege(
    current_user, 'public.grading_jobs', 'update'
  )
  and has_table_privilege(
    current_user, 'public.grading_attempts', 'select'
  )
  and has_table_privilege(
    current_user, 'public.grading_attempts', 'insert'
  )
  and has_table_privilege(
    current_user, 'public.grading_attempts', 'update'
  )
  and not has_table_privilege(
    current_user, 'public.provider_configs', 'update'
  )
  and has_function_privilege(
    current_user,
    'paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)',
    'execute'
  )
  and has_function_privilege(
    current_user,
    'paper_grading_private.finalize_storage_growth(uuid,text)',
    'execute'
  )
)::int as contract_ok \gset
\if :contract_ok
\echo stage14_worker_database_probe_passed
\else
\quit 1
\endif
SQL
```

Worker 启动后，从受控 Render Shell 发送一次不调用模型的维护任务；记录返回的 task ID，并在评分 Worker 日志中确认同一 ID 明确显示 `succeeded` 且无异常。当前没有结果后端，命令成功只代表投递成功，不能单独作为任务成功证据。该任务可能正常收口已过期租约，因此只在已授权生产操作的维护窗口执行：

```bash
python -m celery -A app.workers.celery_app:celery_app call \
  paper_grading.expire_stale_attempts \
  --queue paper_grading.maintenance
```

### 5. Excel 导出 Worker

执行终端：Render Dashboard。
前置条件：`EXPORT_DATABASE_URL` 使用 `paper_grading_export_worker` 最小角色；阶段 12 已设置其独立密码，否则在受控 `psql` 终端用 `\password paper_grading_export_worker` 交互设置；选择同一 `STAGE14_RELEASE_SHA`。
预期结果：`exports@` 心跳可见，只消费 `paper_grading.exports`。
安全回传：Worker 名称、队列名、心跳状态。

### 6. 前端

执行终端：Render Dashboard。
前置条件：API ready；构建变量指向正式 HTTPS API 与同一 Supabase 项目；选择同一 `STAGE14_RELEASE_SHA`。
预期结果：静态站点部署成功，安全响应头存在，HTTP 跳转 HTTPS。
安全回传：正式站点域名、构建 ID、状态码。

### 7. 冒烟测试

执行终端：本机项目根目录。
前置条件：以上六步全部成功。
预期结果：按 `smoke-test.md` 全部通过。
安全回传：步骤编号、通过/失败数量、状态码；不回传账户、论文、对象路径或签名 URL。

## 停止条件

任一步失败立即停止后续部署并进入 `rollback.md`。不重试付费模型请求，不清空 Redis，不回退生产迁移。
