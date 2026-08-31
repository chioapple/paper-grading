# 阶段 14 简易验收流程

本文件只保留阶段 14 上线前不可缺少的验收节点。具体操作细节按需查阅：

- [部署](runbooks/deployment.md)
- [冒烟测试](runbooks/smoke-test.md)
- [监控与故障](runbooks/monitoring-and-incidents.md)
- [回滚](runbooks/rollback.md)

若 Runbook 与本文件的顺序或安全边界冲突，以本文件为准并立即停止。

## 当前状态

| 项目 | 结果 | 是否还要重跑 |
|---|---|---|
| 本地预部署门禁 | 2026-08-30：`stage14_predeployment_gate=true` | 部署代码变化后重跑 |
| 阶段 14 聚焦后端测试 | 31 通过、0 失败 | 相关代码变化后重跑 |
| Sites 构建与路由测试 | 2 通过、0 失败 | 前端或 Sites 配置变化后重跑 |
| 历史候选 SHA CI | `71e377c251958fdd943a5f982bd9db4741a98db2`：8/8 通过，但不含最新部署脚本修复 | 不得作为最终候选 |
| 失败候选 SHA CI | `27c67ac`：前 7 项通过，第 8 项 Git SHA 高熵误判；已在本地修复 | 不得使用或 rerun |
| 修复候选 SHA CI | 尚未生成提交 | 提交后必须 8/8 通过 |
| 回滚 SHA CI | `7302f1e5a16fd3b113149098a94238bbfe20acdb`：8/8 通过 | 不需要 |
| PostgreSQL、Auth、Storage、Redis、Worker、供应商、100 篇结构证据 | 已完成 | 禁止在生产重复做破坏性测试或 100 次模型调用 |
| 生产部署、真实单篇业务流、告警、回滚 | 未执行 | 按下列节点执行 |

阶段 14 仍是“进行中”。本地与 CI 通过不代表生产验收完成。

## 不可违反的边界

1. 任何一步失败都停止，不直接重跑付费流程。
2. 生产数据库只允许前向升级到 `20260728_0019`，禁止 downgrade。
3. Sites 全程保持 owner-only；API 和 Redis 只监听本机回环地址。
4. Mac 后端和 Sites 必须来自同一个候选 SHA；回滚时两端也必须使用同一个回滚 SHA。
5. 自动清理、备份、恢复演练和生产配额继续关闭；启用时另行授权。
6. 密码、Token、Key、数据库 URL、论文内容、业务 ID 和签名 URL 不得写入 Git、文档、日志或聊天。
7. 真实业务只创建一个单篇批次；手机和第二位教师复用同一批次，不重复产生模型费用。

## 验收节点

| 节点 | 执行人/位置 | 只做什么 | 通过标准 | 失败时 |
|---|---|---|---|---|
| 1. 代码与版本门禁 | Codex；项目根目录、GitHub Actions | 跑本地门禁，确认候选和回滚 SHA 的 CI | 本地门禁为 `true`；两个 SHA 各 8/8 通过；部署只读取封存 SHA，不读取当前工作树 | 不进入生产 |
| 2. 私有发布准备 | 用户授权后；Mac、Tailscale、Sites | 准备两个封存 release，启用 Funnel，保存候选/回滚两个 Sites 版本 | Funnel HTTPS 可用；Sites owner-only；两端版本都能追溯到对应 SHA | 恢复原 Funnel/Sites 状态，不迁移数据库 |
| 3. 目标环境与前向迁移 | 用户授权后；Supabase、Mac | 核对目标项目、空闲队列、专用角色和环境文件；只前向迁移；安装并启动运行环境 | revision=`20260728_0019`；环境文件 `0600`；API/Redis 仅回环；6 个 LaunchAgent 正常；API、三个 Worker、Tailscale 强退和重新登录后能恢复 | API/Worker 保持停止；不 downgrade、不清 Redis |
| 4. 无写入生产冒烟 | Codex 可协助；正式 Sites 与 Funnel URL | 检查 Sites 页面、HTTPS、健康接口、安全响应头和 CORS | 页面可访问且深层路径不 404；API 健康；CORS 只允许正式 Sites origin；无业务写入 | 不进入真实业务流 |
| 5. 一次真实单篇业务流 | 用户明确授权费用后；正式网站 | 一名教师完成邀请、登录、作业、Rubric、上传一篇、评分、复核和 Excel 导出；手机与第二位教师复用结果 | 只创建 1 个批次；评分和复核成功；教师隔离正确；Excel 可打开；队列最终归零 | 使用同一任务恢复，禁止再建批次 |
| 6. 告警、回滚与收口 | 用户授权后；UptimeRobot、Mac、Sites、Supabase | 实际触发一次告警和恢复；Mac 与 Sites 同时回滚，再恢复候选；最后只读检查 | 告警和恢复均收到；两端回滚成功且已恢复候选；数据库仍为 `0019`；Redis 未清；队列为 0；关闭项仍关闭 | 进入维护状态，恢复最后一组一致版本 |

## 节点 1：本地检查完成后仍需新候选 CI

### 1.1 重跑本地门禁

执行位置：终端 A。生产写入：无。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/stage14-predeployment-gate.sh
git diff --check
print "stage14_local_candidate_gate=true"
)
```

预期依次看到 `stage14_predeployment_gate=true` 和 `stage14_local_candidate_gate=true`。

本轮结果：

| 检查 | 通过 | 失败 |
|---|---:|---:|
| 本地预部署门禁 | 1 | 0 |
| 阶段 14 聚焦后端测试 | 31 | 0 |
| Sites 构建与路由测试 | 2 | 0 |
| 历史候选 SHA GitHub CI | 8 | 0 |
| 回滚 SHA GitHub CI | 8 | 0 |

历史候选 CI 和回滚 CI 已通过，但不包含最新安全修复。`27c67ac` 的前 7 项通过，第 8 项因两个已知 Git SHA 被高熵扫描误判而失败；该误判已在本地逐行修正，但旧提交内容不可改变，不要 rerun。修复提交和新 CI 完成前，节点 1 仍为未通过。

### 1.2 生成并推送新候选

先执行 `git status --short`，人工确认只包含本轮 10 个文件：`CONTEXT.md`、两个阶段 14 测试文件、`docs/STAGE14_ACCEPTANCE.md`、`findings.md`、两个 `infra/local` 脚本、`lessons.md`、`progress.md`、`task_plan.md`。若出现其他文件，停止，不要提交。

用户确认允许提交和推送后，在终端 A执行：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test "$(git branch --show-current)" = "main"
git add -- \
  CONTEXT.md \
  backend/tests/test_stage14_delivery_contract.py \
  backend/tests/test_stage14_local_deployment_scripts.py \
  docs/STAGE14_ACCEPTANCE.md \
  findings.md \
  infra/local/update-production-env.sh \
  infra/local/verify-runtime.sh \
  lessons.md \
  progress.md \
  task_plan.md
git diff --cached --check
git commit -m "docs: add executable stage 14 acceptance guide"
git push origin HEAD:main
candidate_sha=$(git rev-parse HEAD)
remote_sha=$(git ls-remote origin refs/heads/main | /usr/bin/cut -f1)
test "$candidate_sha" = "$remote_sha"
print "candidate_sha=$candidate_sha"
print "stage14_candidate_pushed=true"
)
```

不要把 `candidate_sha` 当作验收记录提交 SHA；它必须是包含上述 10 个文件的部署候选。

### 1.3 核对新候选 CI

执行位置：GitHub 网页，不在终端输入命令。

1. 打开仓库 → **Actions** → `CI`；
2. 打开 `head_sha` 与终端打印的 `candidate_sha` 完全相同的 run；
3. 等待 run 状态变为 `completed`、结论为 `success`；
4. 展开 jobs，必须恰好 8 个，且 8 个全部为绿色 success；
5. 在本机验收记录中保存完整 `candidate_sha`，不要保存 Token 或 Actions 页面临时链接。

任何 SHA 不一致、job 少于/多于 8 个、job 被跳过或非 success，都判定节点 1 失败，不进入节点 2。

## 执行位置

每个终端都是新开的独立 zsh，会话之间不共享变量。除非步骤明确要求，前一个终端不要关闭。

| 名称 | 用途 | 工作目录 |
|---|---|---|
| 终端 A | release、环境文件、Redis、数据库迁移、LaunchAgent、只读探针 | `/Users/a1-6/Documents/Paper Grading` |
| 终端 B | Tailscale 登录、Funnel、临时 daemon 到 LaunchAgent 的交接 | `/Users/a1-6/Documents/Paper Grading` |
| 终端 C | 只运行一次的真实 E2E | 稳定 `current` release |
| 终端 D | 告警、回滚、恢复候选 | 稳定 `current` release |
| Supabase SQL Editor | revision、队列和安全状态的只读 SQL | 目标生产项目 |
| Supabase Dashboard | Auth、Storage、Network Restrictions | 目标生产项目 |
| Codex Sites | 保存、私有部署、回滚前端版本 | 现有 Sites 项目 |
| UptimeRobot | HTTP/Heartbeat 监控 | 当前个人账户 |
| Chrome/邮箱 | Tailscale 登录、Sites 页面、邀请和真实业务 | 用户本人操作 |

所有终端命令都复制完整代码块执行。任一块没有打印预期标记或返回非 0，立即停止，不执行下一块。

## 节点 2：私有发布准备

本节点会修改本机 Tailscale/Funnel、创建本机 release，并在 Sites 保存私有版本；执行前需用户明确授权。

### 2.1 登录 Tailscale

先关闭会制造 fake-IP 的 VPN 系统代理/虚拟网卡模式。密码、Passkey 和验证码只由用户在 Chrome 输入。

执行位置：终端 B。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/tailscale-login.sh start
./infra/local/tailscale-login.sh login
./infra/local/tailscale-login.sh status --expect-running
print "stage14_tailscale_logged_in=true"
)
```

如果终端显示登录链接，在 Chrome 完成登录，等待终端命令结束。不得把链接、设备名或 IP 发到聊天。

### 2.2 启用 Funnel

执行位置：终端 B。该操作把固定 HTTPS 入口转发到本机 `127.0.0.1:8000`。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/stage14-funnel.sh enable
./infra/local/stage14-funnel.sh status
print "stage14_funnel_enabled=true"
)
```

随后仍在终端 B执行下面的本机只读显示，目视确认只有一个 HTTPS 根路由，目标精确为 `http://127.0.0.1:8000`，不得存在额外 TCP 或子路径路由：

```zsh
(
set -euo pipefail
socket="$HOME/Library/Application Support/Paper Grading/shared/tailscale/tailscaled.sock"
/opt/homebrew/bin/tailscale --socket="$socket" funnel status
)
```

在本机密码管理器记录生成的 `https://*.ts.net` origin，不要回传原始输出。若节点 2 或 3 中途停止，且 LaunchAgent 尚未接管，终端 B执行：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/stage14-funnel.sh restore
./infra/local/tailscale-login.sh stop
./infra/local/tailscale-login.sh status --expect-stopped
print "stage14_temporary_funnel_restored=true"
)
```

### 2.3 准备候选和回滚 release

执行位置：终端 A。Supabase publishable key 使用隐藏输入；不要把任何 URL 或 Key 发到聊天。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
runtime_root="$HOME/Library/Application Support/Paper Grading"
read -r "candidate_sha?输入已取得 CI 8/8 的新候选完整 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="7302f1e5a16fd3b113149098a94238bbfe20acdb" # pragma: allowlist secret
read -r "VITE_API_BASE_URL?输入刚记录的 Funnel HTTPS origin："
read -r "VITE_SUPABASE_URL?输入生产 Supabase 项目 URL："
read -rs "VITE_SUPABASE_PUBLISHABLE_KEY?输入 Supabase publishable key："; print
export VITE_API_BASE_URL VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY
trap 'unset VITE_SUPABASE_PUBLISHABLE_KEY' EXIT

for release_sha in "$rollback_sha" "$candidate_sha"; do
  ./infra/local/prepare-release.sh "$release_sha"
  ./infra/local/validate-release.sh "$release_sha"
done

manager="$runtime_root/shared/bin/switch-release.sh"
test -x "$manager"
"$manager" "$candidate_sha" --prepare-only
test "$(/usr/bin/stat -f '%Y' "$runtime_root/current")" = \
  "$runtime_root/releases/$candidate_sha"
print "stage14_two_local_releases_prepared=true"
)
```

预期：每个 release 分别打印 `stage14_release_prepared=true` 和 `stage14_release_validated=true`，最后打印 `stage14_two_local_releases_prepared=true`。

### 2.4 保存并私有部署 Sites

执行位置：Codex Sites，不在终端输入命令。用户在聊天中明确回复：

```text
授权执行阶段14节点2.4：保存回滚和候选两个 Sites 版本，并仅私有部署候选版本。
```

Codex 必须按以下顺序执行：

1. 读取 `frontend/.openai/hosting.json`，复用已有 `project_id`，不得新建项目。
2. 在改动前记录当前正在部署的 Sites 版本号、部署状态和 owner-only 状态，标记为“节点 2 前版本”。
3. 确认当前用户是 owner，访问范围仅本人。
4. 回滚版本只能从本机封存目录 `~/Library/Application Support/Paper Grading/releases/7302f1e5a16fd3b113149098a94238bbfe20acdb/frontend` 构建；候选版本只能从 `~/Library/Application Support/Paper Grading/releases/<候选完整 SHA>/frontend` 构建。禁止读取项目当前工作树。
5. 从回滚封存目录保存一个 Sites 版本，再从候选封存目录保存一个不同版本。
6. 私有部署候选版本，轮询到 `succeeded`；禁止公开部署。
7. 本机记录“SHA ↔ Sites 版本号”及“节点 2 前版本号”；不记录 source credential 或 bypass token。

以上任一步失败，都私有重新部署“节点 2 前版本”，轮询到 `succeeded` 并复核 owner-only；恢复完成前不进入节点 3。

### 2.5 Chrome 页面检查

以 Sites owner 身份打开并刷新：`/login`、`/auth/callback`、`/assignments`、`/grading-jobs`、`/exports`。

通过标准：五个路径都不返回 404；无痕窗口不能直接进入应用；Sites 保持 owner-only。此时 API 尚未启动，页面暂时显示后端不可用可以接受。

## 节点 3：目标环境、迁移与自动恢复

本节点包含生产配置和可能的单次前向迁移，必须在用户明确授权后执行。

### 3.1 Supabase 只读预检

执行位置：目标生产 Supabase SQL Editor。

```sql
select version_num from public.alembic_version;

select
  (select count(*) = 0 from public.grading_jobs
   where status in ('queued', 'running')) as grading_jobs_idle,
  (select count(*) = 0 from public.grading_job_items
   where status in ('queued', 'running')) as grading_items_idle,
  (select count(*) = 0 from public.grading_attempts
   where status = 'running') as grading_attempts_idle,
  (select count(*) = 0 from public.exports
   where status in ('queued', 'running')) as exports_idle;

select rolname, rolcanlogin, rolinherit, rolbypassrls, rolsuper,
       rolcreaterole, rolcreatedb, rolreplication,
       rolpassword is not null as password_configured
from pg_catalog.pg_roles
where rolname in ('paper_grading_worker', 'paper_grading_export_worker')
order by rolname;

select count(*) = 1 and bool_and(c.relrowsecurity)
       as storage_objects_rls_enabled
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'storage' and c.relname = 'objects';

select policyname
from pg_catalog.pg_policies
where schemaname = 'storage' and tablename = 'objects';
```

通过标准：

- revision 只能是 `20260726_0018` 或 `20260728_0019`；
- 四个 `idle` 全为 `true`；
- 两个 Worker 角色存在，均非 superuser、非 bypass RLS、无继承和建库/建角色权限；
- `storage_objects_rls_enabled=true`，最后一条策略查询为 0 行。

任何一项不符都停止，不要自行改角色、删策略或迁移。

继续在 Supabase Dashboard → Storage 打开目标 bucket，目视确认：`Private`、文件上限 50MiB，允许 PDF、DOCX、JSON、XLSX。论文入口仍由应用限制为 20MiB。若角色 `password_configured=false` 或密码已经遗失，停止并在聊天中回复“需要单独授权设置对应 Worker 角色密码”；不要在 SQL Editor 直接写带明文密码的 `ALTER ROLE`。

### 3.2 配置 Supabase Auth 和暂停的监控

执行位置：Supabase Dashboard → Authentication → URL Configuration。

1. 先在本机记录旧 Site URL 和 Redirect URLs。
2. Site URL 填写正式 Sites origin，不带尾斜杠。
3. Redirect URLs 保留精确的 `<Sites origin>/auth/callback`，不要使用 wildcard。
4. 确认公开注册保持关闭，然后保存。

执行位置：UptimeRobot。

1. 创建 HTTP(S) monitor：`<Funnel origin>/health/ready`，检查间隔设为免费方案支持的 5 分钟，先保持暂停。
2. 创建 Heartbeat/Cron monitor：期望间隔设为 1 分钟，grace period 设为 2 分钟，先保持暂停。这与本机每 60 秒执行一次的 watchdog 匹配。
3. 两个 monitor 都选择用户实际能收到邮件或推送的同一通知联系人；先使用 UptimeRobot 的测试通知确认联系人可达。
4. Heartbeat URL只存入密码管理器，下一步由脚本隐藏输入，不要发送到聊天。

### 3.3 创建生产环境文件

执行位置：终端 A。脚本会逐项提示，密码和 Key 均隐藏输入。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
"$runtime_root/current/infra/local/update-production-env.sh" --create
print "stage14_environment_files_created=true"
)
```

输入来源：

| 提示 | 应输入内容 |
|---|---|
| API `DATABASE_URL` | Supabase Session Pooler 5432，用户 `postgres.<project-ref>` |
| `EXPORT_DATABASE_URL` | Session Pooler 5432，用户 `paper_grading_export_worker.<project-ref>` |
| 评分 Worker URL | Session Pooler 5432，用户 `paper_grading_worker.<project-ref>` |
| `SUPABASE_URL` | 正式 Supabase 项目 URL |
| publishable/secret key | 同一正式项目的对应 Key |
| Storage bucket | 已有私有 bucket 名称 |
| `PROVIDER_MASTER_KEY` | 与数据库现有供应商密文匹配的原 Key，不得新生成 |
| `FRONTEND_ORIGIN` | 正式 Sites origin，必须以 `https://` 开头且不带尾斜杠 |
| `VITE_API_BASE_URL` | 正式 Funnel origin，必须以 `https://` 开头且不带尾斜杠 |
| Heartbeat URL | UptimeRobot 新建的 Heartbeat URL |

输入错误时不要手工编辑文件；取得授权后运行同一脚本的 `--replace`。

随后仍在终端 A验证权限：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
env_dir="$runtime_root/shared/env"
for directory in "$runtime_root" "$runtime_root/shared" "$env_dir"; do
  test -d "$directory"
  test ! -L "$directory"
  test "$(stat -f '%Su' "$directory")" = "$USER"
  test "$(stat -f '%Lp' "$directory")" = "700"
done
for env_path in "$env_dir/production.env" "$env_dir/grading-worker.env"; do
  test -f "$env_path"
  test ! -L "$env_path"
  test "$(stat -f '%Su' "$env_path")" = "$USER"
  test "$(stat -f '%Lp' "$env_path")" = "600"
done
print "stage14_environment_file_permissions=true"
)
```

### 3.4 验证 Redis 只在本机运行

执行位置：终端 A。

```zsh
(
set -euo pipefail
brew services start redis
test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
test "$(/opt/homebrew/bin/redis-cli --raw CONFIG GET protected-mode | /usr/bin/tail -n 1)" = "yes"
test "$(/opt/homebrew/bin/redis-cli --raw CONFIG GET maxmemory-policy | /usr/bin/tail -n 1)" = "noeviction"
listeners=$(/usr/sbin/lsof -nP -iTCP:6379 -sTCP:LISTEN -Fn | /usr/bin/grep '^n' | /usr/bin/cut -c2-)
test -n "$listeners"
while IFS= read -r listener; do
  case "$listener" in
    127.0.0.1:6379|'[::1]:6379') ;;
    *) exit 1 ;;
  esac
done <<<"$listeners"
runtime_root="$HOME/Library/Application Support/Paper Grading"
source "$runtime_root/shared/env/production.env"
export REDIS_URL
PYTHONPATH="$runtime_root/current/backend" "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
import redis

client = redis.Redis.from_url(os.environ["REDIS_URL"])
counts = [
    client.llen("paper_grading.grading"),
    client.llen("paper_grading.maintenance"),
    client.llen("paper_grading.exports"),
    client.hlen("unacked"),
    client.zcard("unacked_index"),
]
if any(counts):
    raise SystemExit("stage14_broker_not_empty")
PY
print "stage14_redis_loopback_only=true"
)
```

### 3.5 停止旧进程并执行或跳过迁移

先在以前启动 API、评分/维护 Worker、导出 Worker 的各个旧终端中按 `Control-C`，等待全部退出。然后终端 A执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "stage14_api_still_running=true"
  exit 1
fi
source "$runtime_root/shared/env/production.env"
export REDIS_URL
PYTHONPATH="$runtime_root/current/backend" "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
import redis
from celery import Celery

app = Celery("stage14_freeze", broker=os.environ["REDIS_URL"])
nodes = app.control.inspect(timeout=3).ping() or {}
if nodes:
    raise SystemExit("stage14_worker_write_freeze_failed")
client = redis.Redis.from_url(os.environ["REDIS_URL"])
counts = [
    client.llen("paper_grading.grading"),
    client.llen("paper_grading.maintenance"),
    client.llen("paper_grading.exports"),
    client.hlen("unacked"),
    client.zcard("unacked_index"),
]
if any(counts):
    raise SystemExit("stage14_broker_not_empty")
PY
print "stage14_local_writes_frozen=true"
)
```

命令通过后立即重新执行 3.1 的四项 `idle` SQL；必须仍全部为 `true`，迁移结束前不得启动 API 或 Worker。

若 3.1 已是 `20260728_0019`，跳过下面迁移块。只有 3.1 是 `20260726_0018` 且用户明确授权后，才在终端 A执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current/backend"
source "$runtime_root/shared/env/production.env"
read -rs "MIGRATION_DATABASE_URL?输入同一项目的 Supabase Direct URL："; print
read -r "migration_auth?输入 I_AUTHORIZE_FORWARD_MIGRATION_TO_0019："
test "$migration_auth" = "I_AUTHORIZE_FORWARD_MIGRATION_TO_0019"
export MIGRATION_DATABASE_URL SUPABASE_URL
trap 'unset MIGRATION_DATABASE_URL migration_auth' EXIT

PYTHONPATH=. ../.venv/bin/python - <<'PY'
import os
import re
from urllib.parse import urlparse
from sqlalchemy.engine import make_url
from app.config import MigrationSettings

url = make_url(MigrationSettings().migration_database_url)
supabase = urlparse(os.environ["SUPABASE_URL"])
if supabase.scheme != "https" or not (supabase.hostname or "").endswith(".supabase.co"):
    raise SystemExit("stage14_supabase_url_invalid")
project_ref = (supabase.hostname or "").removesuffix(".supabase.co")
if (
    re.fullmatch(r"[a-z0-9]{10,40}", project_ref) is None
    or os.environ["SUPABASE_URL"] != f"https://{project_ref}.supabase.co"
    or url.host != f"db.{project_ref}.supabase.co"
    or url.port not in (None, 5432)
    or url.username != "postgres"
    or url.database != "postgres"
    or set(url.query) != {"ssl"}
    or url.query.get("ssl") not in {"require", "verify-ca", "verify-full"}
):
    raise SystemExit("stage14_migration_target_mismatch")
print("stage14_migration_target_verified=true")
PY

PYTHONPATH=. ../.venv/bin/alembic upgrade 20260728_0019
print "stage14_forward_migration_executed=true"
)
```

迁移后回到 Supabase SQL Editor：

```sql
select version_num from public.alembic_version;

select
  (select count(*) = 0 from public.grading_jobs
   where status in ('queued', 'running')) as grading_jobs_idle,
  (select count(*) = 0 from public.grading_job_items
   where status in ('queued', 'running')) as grading_items_idle,
  (select count(*) = 0 from public.exports
   where status in ('queued', 'running')) as exports_idle;
```

revision 必须唯一且为 `20260728_0019`，三个 `idle` 必须全部为 `true`。失败时保持服务停止；禁止 downgrade 或重复迁移。

### 3.6 验证三个数据库角色能连接

执行位置：终端 A。只输出固定标记，不输出连接地址。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
env_dir="$runtime_root/shared/env"
cd "$current"
read -r "candidate_sha?输入已取得 CI 8/8 的新候选完整 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="7302f1e5a16fd3b113149098a94238bbfe20acdb" # pragma: allowlist secret
for release_sha in "$candidate_sha" "$rollback_sha"; do
  "$runtime_root/releases/$release_sha/infra/local/validate-release.sh" \
    "$release_sha" --env-dir "$env_dir"
done
set -a
source "$env_dir/production.env"
set +a
grading_database_url=$(set -a; source "$env_dir/grading-worker.env"; set +a; print -r -- "$DATABASE_URL")
export grading_database_url
trap 'unset grading_database_url' EXIT

PYTHONPATH=backend ./.venv/bin/python - <<'PY'
import asyncio
import os
import re
from urllib.parse import urlparse
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

supabase = urlparse(os.environ["SUPABASE_URL"])
project_ref = (supabase.hostname or "").removesuffix(".supabase.co")
if (
    supabase.scheme != "https"
    or re.fullmatch(r"[a-z0-9]{10,40}", project_ref) is None
    or os.environ["SUPABASE_URL"] != f"https://{project_ref}.supabase.co"
):
    raise SystemExit("stage14_supabase_url_invalid")

urls = {
    "postgres": (os.environ["DATABASE_URL"], f"postgres.{project_ref}"),
    "paper_grading_worker": (
        os.environ["grading_database_url"], f"paper_grading_worker.{project_ref}"
    ),
    "paper_grading_export_worker": (
        os.environ["EXPORT_DATABASE_URL"], f"paper_grading_export_worker.{project_ref}"
    ),
}

async def main() -> None:
    for expected, (url, expected_username) in urls.items():
        parsed = make_url(url)
        if (
            parsed.drivername != "postgresql+asyncpg"
            or parsed.username != expected_username
            or not (parsed.host or "").endswith(".pooler.supabase.com")
            or parsed.port != 5432
            or parsed.database != "postgres"
            or set(parsed.query) != {"ssl"}
            or parsed.query.get("ssl") not in {"require", "verify-ca", "verify-full"}
        ):
            raise SystemExit("stage14_pooler_contract_failed")
        engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True)
        try:
            async with engine.connect() as connection:
                actual = await connection.scalar(text("select current_user"))
                if actual != expected:
                    raise SystemExit("stage14_database_role_failed")
        finally:
            await engine.dispose()

asyncio.run(main())
print("stage14_database_roles_verified=true")
PY
)
```

继续在终端 A执行零费用供应商密钥与网络策略探针。它只解密现有 Key并检查 base URL，不发送模型请求：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
cd "$current"
set -a
source "$runtime_root/shared/env/production.env"
set +a

PYTHONPATH=backend ./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from app.config import Settings
from app.domain.enums import ProviderType
from app.providers.connection import ProviderBaseUrlPolicy
from app.security.encryption import ApiKeyCipher, EncryptedApiKey

settings = Settings.load()
cipher = ApiKeyCipher.from_base64_master_key(
    settings.provider_master_key.get_secret_value()
)

async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(text(
                "select id, provider_type, base_url, encrypted_api_key, api_key_nonce "
                "from public.provider_configs where status = 'enabled' "
                "and encrypted_api_key is not null and api_key_nonce is not null"
            ))).mappings().all()
        if not rows:
            raise SystemExit("stage14_enabled_provider_missing")
        for row in rows:
            cipher.decrypt(
                EncryptedApiKey(
                    ciphertext=row["encrypted_api_key"], nonce=row["api_key_nonce"]
                ),
                provider_id=row["id"],
            )
            await ProviderBaseUrlPolicy().validate(
                ProviderType(row["provider_type"]), row["base_url"]
            )
    finally:
        await engine.dispose()

asyncio.run(main())
print("stage14_provider_key_and_network_policy_verified=true")
PY
)
```

### 3.7 将 Tailscale 交给 LaunchAgent 并启动全部服务

先在终端 B停止临时 daemon：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
helper="$runtime_root/current/infra/local/tailscale-login.sh"
"$helper" stop
"$helper" status --expect-stopped
print "stage14_tailscale_ready_for_launchd=true"
)
```

再在终端 A安装并验证 6 个 LaunchAgent：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
"$current/infra/local/install-launch-agents.sh"
for _ in {1..60}; do
  if "$current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    print "stage14_launchd_initial_runtime=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_launchd_initial_runtime=false"
exit 1
)
```

若失败，立即执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
"$current/infra/local/install-launch-agents.sh" --rollback-first-install
for label in api grading export keep-awake tailscale watchdog; do
  if launchctl print "gui/$UID/com.paper-grading.$label" >/dev/null 2>&1; then
    print -u2 "stage14_partial_launchd_rollback=false"
    exit 1
  fi
done
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "stage14_partial_launchd_rollback=false"
  exit 1
fi
tailscale_helper="$current/infra/local/tailscale-login.sh"
funnel_helper="$current/infra/local/stage14-funnel.sh"
"$tailscale_helper" start
"$tailscale_helper" status --expect-running
"$funnel_helper" restore
"$tailscale_helper" stop
"$tailscale_helper" status --expect-stopped
print "stage14_partial_launchd_rollback=true"
)
```

清理成功后，用户还必须完成以下恢复并逐项复核，然后停止验收：

1. Supabase Dashboard 按 3.2 保存的快照恢复旧 Site URL 和 Redirect URLs并重新读取确认；
2. Codex Sites 私有部署 2.4 记录的“节点 2 前版本”，轮询到 `succeeded` 并确认 owner-only；
3. 两个 UptimeRobot 监控保持暂停。

### 3.8 强制重启和重新登录恢复

执行位置：终端 A。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
source "$runtime_root/shared/env/production.env"
export REDIS_URL
verification_succeeded=false
stop_business_on_failure() {
  if [[ "$verification_succeeded" = true ]]; then
    return 0
  fi
  cleanup_ok=true
  for component in grading export api; do
    label="gui/$UID/com.paper-grading.$component"
    plist="$agents/com.paper-grading.$component.plist"
    if launchctl print "$label" >/dev/null 2>&1; then
      if ! launchctl bootout "gui/$UID" "$plist"; then
        cleanup_ok=false
      fi
    fi
  done
  if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    cleanup_ok=false
  fi
  if ! PYTHONPATH="$runtime_root/current/backend" \
       "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

nodes = Celery("stage14_stop_check", broker=os.environ["REDIS_URL"]).control.inspect(timeout=3).ping() or {}
if nodes:
    raise SystemExit("stage14_orphan_workers_still_running")
PY
  then
    cleanup_ok=false
  fi
  if [[ "$cleanup_ok" = true ]]; then
    print -u2 "stage14_failed_restart_business_stopped=true"
  else
    print -u2 "stage14_failed_restart_business_stopped=false"
  fi
}
trap stop_business_on_failure EXIT INT TERM
for label in api grading export tailscale; do
  launchctl kickstart -k "gui/$UID/com.paper-grading.$label"
done
for _ in {1..60}; do
  if "$runtime_root/current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    verification_succeeded=true
    trap - EXIT INT TERM
    print "stage14_launchd_forced_restart=true"
    exit 0
  fi
  sleep 2
done
exit 1
)
```

保存其他工作，注销并重新登录 macOS。重新登录后打开新的终端 A执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
source "$runtime_root/shared/env/production.env"
export REDIS_URL
verification_succeeded=false
stop_business_on_failure() {
  if [[ "$verification_succeeded" = true ]]; then
    return 0
  fi
  cleanup_ok=true
  for component in grading export api; do
    label="gui/$UID/com.paper-grading.$component"
    plist="$agents/com.paper-grading.$component.plist"
    if launchctl print "$label" >/dev/null 2>&1; then
      if ! launchctl bootout "gui/$UID" "$plist"; then
        cleanup_ok=false
      fi
    fi
  done
  if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    cleanup_ok=false
  fi
  if ! PYTHONPATH="$runtime_root/current/backend" \
       "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

nodes = Celery("stage14_stop_check", broker=os.environ["REDIS_URL"]).control.inspect(timeout=3).ping() or {}
if nodes:
    raise SystemExit("stage14_orphan_workers_still_running")
PY
  then
    cleanup_ok=false
  fi
  if [[ "$cleanup_ok" = true ]]; then
    print -u2 "stage14_failed_login_recovery_business_stopped=true"
  else
    print -u2 "stage14_failed_login_recovery_business_stopped=false"
  fi
}
trap stop_business_on_failure EXIT INT TERM
"$runtime_root/current/infra/local/verify-runtime.sh"
verification_succeeded=true
trap - EXIT INT TERM
print "stage14_login_recovery_verified=true"
)
```

## 节点 4：无写入生产冒烟

### 4.1 HTTPS、安全响应头和 CORS

执行位置：终端 A。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
source "$runtime_root/shared/env/production.env"
api_origin="$VITE_API_BASE_URL"
frontend_origin="$FRONTEND_ORIGIN"
tmp_dir=$(mktemp -d)
trap '/bin/rm -rf "$tmp_dir"' EXIT

case "$api_origin" in https://*.ts.net) ;; *) exit 1 ;; esac
http_status=$(curl --silent --show-error --connect-timeout 5 --max-time 10 \
  --max-redirs 0 --output /dev/null --write-out '%{http_code}' \
  "${api_origin/https:/http:}/health/live" 2>/dev/null || true)
case "$http_status" in
  000|301|302|307|308|400|403|404) ;;
  *) print -u2 "stage14_plain_http_served_application=true"; exit 1 ;;
esac
curl --fail --silent --show-error --output /dev/null \
  --dump-header "$tmp_dir/api.headers" "$api_origin/health/live"
curl --fail --silent --show-error "$api_origin/health/ready" >/dev/null

tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'x-content-type-options: nosniff'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'x-frame-options: DENY'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'referrer-policy: no-referrer'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi \
  'permissions-policy: camera=(), microphone=(), geolocation=()'

curl --fail --silent --show-error --output /dev/null \
  --dump-header "$tmp_dir/allowed.headers" \
  -H "Origin: $frontend_origin" \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "$api_origin/auth/me"
tr -d '\r' <"$tmp_dir/allowed.headers" | /usr/bin/grep -Fxi \
  "access-control-allow-origin: $frontend_origin"

blocked_status=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --dump-header "$tmp_dir/blocked.headers" \
  -H 'Origin: https://attacker.invalid' \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "$api_origin/auth/me")
test "$blocked_status" = "400"
if tr -d '\r' <"$tmp_dir/blocked.headers" | \
  /usr/bin/grep -qi '^access-control-allow-origin:'; then
  exit 1
fi
print "stage14_api_read_only_smoke=true"
)
```

预期只保留固定结果 `stage14_api_read_only_smoke=true`，不要把完整响应头发到聊天。

### 4.2 Chrome 页面检查

以 Sites owner 身份打开并刷新 `/login`、`/auth/callback`、`/assignments`、`/grading-jobs`、`/exports`。

再打开开发者工具 Console，检查：页面不空白、五个路径不 404、后端不再显示不可用、Console 错误和警告均为 0。把窗口切换为 `390 × 844`，确认无横向滚动条。

在 Chrome DevTools → Network 重新加载 `/login`，点开页面主文档响应，确认正式 Sites 页面本身也包含：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Permissions-Policy: camera=(), microphone=(), geolocation=()`。API 和 Sites 两侧任一缺失都视为节点 4 失败。

## 节点 5：一次真实单篇业务流

### 5.1 当前必须停止的代码门禁

执行位置：终端 A。该检查当前预期返回失败；它只用于防止误开始付费流程。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
if /usr/bin/grep -Fq 'not_implemented' infra/local/run-stage14-e2e.sh; then
  print -u2 "stage14_paid_flow_gate=false"
  exit 1
fi
print "stage14_paid_flow_gate=true"
)
```

只有以下三项都实现并通过测试后，才能继续：

1. `--resume` 和 `--postcondition` 不再返回 `not_implemented`；
2. `--start` 写入前会查询生产端，拒绝已存在的同名作业、批次、attempt 或导出；
3. Sites bypass 有不经过聊天、文件、剪贴板或命令参数的受控进程交接通道。

### 5.2 门禁修复后的人工准备

执行位置：Chrome、邮箱和供应商账户页面。

1. 用户明确授权一个真实单篇流程及费用上限。
2. 在供应商页面确认账户/子账户硬消费上限；无法确认就停止。
3. 管理员在正式网站只邀请一名全新教师 A；教师 A从邮箱打开一次性链接、设密并首次登录。
4. 准备一名既有教师 B，只用于隔离检查，不再创建账号。
5. 准备无敏感内容的 Assignment Prompt、Rubric 和一篇不超过 20MiB 的 PDF/DOCX。
6. 作业标题使用唯一 `Stage14-日期时间-短标识`，并只保存在本机。

修复后的 runner 必须在受控进程内收集并校验：正式 Sites URL、教师 A/B 邮箱与密码、教师 A显示名、模型标签、唯一作业标题、Assignment Prompt 路径、Rubric 路径、论文路径、总分和分数步长。密码与 Sites bypass 必须隐藏/内存输入，其余值也不得写入 Git或聊天。

### 5.3 门禁修复后的唯一启动命令

执行位置：全新终端 C。Sites bypass 由受控执行器注入，不能人工显示或粘贴。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
runner="$runtime_root/current/infra/local/run-stage14-e2e.sh"
test -x "$runner"
"$runner" --start
)
```

`--start` 只允许执行一次。若复核或导出失败，只能在全新终端 C执行下面的完整恢复块：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
runner="$runtime_root/current/infra/local/run-stage14-e2e.sh"
test -x "$runner"
"$runner" --resume
)
```

若业务已完成但浏览器断言失败，只能在全新终端 C执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
runner="$runtime_root/current/infra/local/run-stage14-e2e.sh"
test -x "$runner"
"$runner" --postcondition
)
```

禁止删除 marker、删除业务记录或再次执行 `--start`。当前两个恢复命令尚未实现，因此节点 5 仍停止在 5.1。

通过标准：1 个作业、1 个单篇批次；Rubric、评分、复核和 Excel 导出完成；教师 B 看不到教师 A 数据；手机复用同一结果；Console 错误/警告为 0。

## 节点 6：队列、告警、回滚与收口

### 6.1 Worker 和队列归零

执行位置：终端 A。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
source "$runtime_root/shared/env/production.env"
export REDIS_URL
"$current/infra/local/verify-runtime.sh"

PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
import os
import redis
from celery import Celery

app = Celery("stage14_close", broker=os.environ["REDIS_URL"])
inspect = app.control.inspect(timeout=10)
ping = inspect.ping() or {}
active = inspect.active() or {}
reserved = inspect.reserved() or {}
expected_prefixes = ("grading@", "maintenance@", "exports@")
expected_names = set()
for prefix in expected_prefixes:
    matches = {name for name in ping if name.startswith(prefix)}
    if len(matches) != 1:
        raise SystemExit("stage14_worker_identity_failed")
    expected_names.update(matches)
if set(ping) != expected_names:
    raise SystemExit("stage14_unexpected_worker_detected")
if set(active) != set(ping) or set(reserved) != set(ping):
    raise SystemExit("stage14_worker_inspect_incomplete")
if any(active.values()) or any(reserved.values()):
    raise SystemExit("stage14_workers_busy")
client = redis.Redis.from_url(os.environ["REDIS_URL"])
counts = {
    "grading": client.llen("paper_grading.grading"),
    "maintenance": client.llen("paper_grading.maintenance"),
    "exports": client.llen("paper_grading.exports"),
    "unacked": client.hlen("unacked"),
    "unacked_index": client.zcard("unacked_index"),
}
if any(counts.values()):
    raise SystemExit("stage14_broker_not_empty")
print("stage14_workers_and_broker_closed=true")
PY
)
```

执行位置：Supabase SQL Editor。

```sql
select
  (select count(*) = 0 from public.grading_jobs
   where status in ('queued', 'running')) as grading_jobs_idle,
  (select count(*) = 0 from public.grading_job_items
   where status in ('queued', 'running')) as grading_items_idle,
  (select count(*) = 0 from public.grading_attempts
   where status = 'running') as grading_attempts_idle,
  (select count(*) = 0 from public.exports
   where status in ('queued', 'running')) as exports_idle,
  (select count(*) = 2 and bool_and(enabled = false)
   from public.quota_resource_states) as quota_disabled,
  (select count(*) = 3 and bool_and(enabled = false)
   and bool_and(retention_days = 30)
   from public.retention_policies) as retention_disabled,
  (select count(*) = 1 and bool_and(
     creation_enabled = false and cleanup_enabled = false
     and coalesce(btrim(target_identifier), '') = '')
   from public.backup_policies) as backup_disabled,
  (select count(*) = 0 from public.backup_runs) as no_backup_runs,
  (select count(*) = 0 from public.backup_restore_runs) as no_restore_runs,
  (select count(*) = 0 from public.quota_reservations
   where status = 'reserved') as no_quota_reservations,
  (select count(*) = 0 from public.retention_objects
   where status = 'running') as no_retention_running;
```

十一列必须全部为 `true`。不要为了验收启用配额、清理、备份或恢复。

### 6.2 实际告警与恢复

先在 UptimeRobot 启用 HTTP 和 Heartbeat 两个监控，等待两者显示正常，并确认测试通知已送达。确认 6.1 全部归零后，在终端 D执行。停止导出 Worker 后，最多等待 5 分钟；这是 1 分钟 Heartbeat 加 2 分钟 grace 和告警处理余量。5 分钟仍未收到就输入 `FAIL`，脚本会恢复 Worker，本项判定失败。

```zsh
(
set -euo pipefail
plist="$HOME/Library/LaunchAgents/com.paper-grading.export.plist"
restore_export() {
  if ! launchctl print "gui/$UID/com.paper-grading.export" >/dev/null 2>&1; then
    launchctl bootstrap "gui/$UID" "$plist"
  fi
  launchctl kickstart -k "gui/$UID/com.paper-grading.export"
}
trap restore_export EXIT
launchctl bootout "gui/$UID" "$plist"
read -r "alert_result?收到 UptimeRobot 告警后输入 I_RECEIVED_ALERT；未收到输入 FAIL："
test "$alert_result" = "I_RECEIVED_ALERT"
)
```

无论成功、失败或按 `Control-C`，trap 都会尝试恢复导出 Worker。随后终端 D执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
plist="$HOME/Library/LaunchAgents/com.paper-grading.export.plist"
if ! launchctl print "gui/$UID/com.paper-grading.export" >/dev/null 2>&1; then
  launchctl bootstrap "gui/$UID" "$plist"
fi
launchctl kickstart -k "gui/$UID/com.paper-grading.export"
for _ in {1..60}; do
  if "$current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    print "stage14_export_worker_recovered=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_export_worker_recovered=false"
exit 1
)
```

在 UptimeRobot 等待并确认实际收到恢复通知。只看到监控配置不算通过。

### 6.3 回滚 Mac 和 Sites

先在 UptimeRobot 建立维护窗口，并再次确认 6.1 队列为 0。终端 D执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
read -r "candidate_sha?输入已部署候选的完整 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="7302f1e5a16fd3b113149098a94238bbfe20acdb" # pragma: allowlist secret
manager="$runtime_root/shared/bin/switch-release.sh"
env_dir="$runtime_root/shared/env"
source "$env_dir/production.env"
export REDIS_URL

for release_sha in "$candidate_sha" "$rollback_sha"; do
  "$runtime_root/releases/$release_sha/infra/local/validate-release.sh" \
    "$release_sha" --env-dir "$env_dir"
done

start_business() {
  start_ok=true
  for component in api grading export; do
    plist="$agents/com.paper-grading.$component.plist"
    if ! launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      if ! launchctl bootstrap "gui/$UID" "$plist"; then
        start_ok=false
      fi
    fi
    if ! launchctl kickstart -k "gui/$UID/com.paper-grading.$component"; then
      start_ok=false
    fi
  done
  [[ "$start_ok" = true ]]
}

assert_no_workers() {
  PYTHONPATH="$runtime_root/current/backend" \
    "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

nodes = Celery("stage14_switch_check", broker=os.environ["REDIS_URL"]).control.inspect(timeout=3).ping() or {}
if nodes:
    raise SystemExit("stage14_workers_still_running_before_switch")
PY
}

restore_candidate_on_failure() {
  original_status=$?
  trap - EXIT INT TERM
  set +e
  print -u2 "stage14_backend_rollback_failed_recovering_candidate=true"
  recovery_ok=true
  for component in grading export api; do
    plist="$agents/com.paper-grading.$component.plist"
    if launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      launchctl bootout "gui/$UID" "$plist"
      if (( $? != 0 )); then recovery_ok=false; fi
    fi
  done
  if assert_no_workers; then
    if "$manager" "$candidate_sha"; then
      start_business
      if (( $? != 0 )); then recovery_ok=false; fi
    else
      recovery_ok=false
    fi
  else
    recovery_ok=false
  fi
  recovered=false
  for _ in {1..60}; do
    current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current" 2>/dev/null)
    if [[ "$current_target" = "$runtime_root/releases/$candidate_sha" ]] && \
       "$runtime_root/current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
      recovered=true
      break
    fi
    sleep 2
  done
  if [[ "$recovery_ok" = true && "$recovered" = true ]]; then
    print -u2 "stage14_candidate_recovered_after_failed_rollback=true"
  else
    print -u2 "stage14_candidate_recovery_failed=true"
  fi
  exit "$original_status"
}
trap 'exit 130' INT TERM
trap restore_candidate_on_failure EXIT

for component in grading export api; do
  plist="$agents/com.paper-grading.$component.plist"
  if launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID" "$plist"
  fi
done
assert_no_workers
"$manager" "$rollback_sha"
start_business
for _ in {1..60}; do
  current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current")
  if [[ "$current_target" = "$runtime_root/releases/$rollback_sha" ]] && \
     "$runtime_root/current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    trap - EXIT INT TERM
    print "stage14_backend_rollback_verified=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_backend_rollback_verified=false"
exit 1
)
```

执行位置：Codex Sites。私有部署已经保存的回滚 Sites 版本，轮询到 `succeeded`；再次确认 owner-only。Chrome 检查五个路径和 API 健康。

Sites 回滚的部署调用、状态轮询、owner-only 复核、五路径检查或 API 健康检查中任一项失败，都立即执行 6.4 的 Mac 候选恢复块，并私有部署候选 Sites 版本；候选部署也必须完成状态轮询、owner-only、五路径和 API 健康复核。两端恢复为候选且全部验证通过前保持维护窗口。

执行位置：Supabase SQL Editor。

```sql
select version_num from public.alembic_version;
```

必须仍为 `20260728_0019`。回滚不执行数据库 downgrade，也不清 Redis。

### 6.4 恢复候选版本

终端 D执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
read -r "candidate_sha?输入已部署候选的完整 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="7302f1e5a16fd3b113149098a94238bbfe20acdb" # pragma: allowlist secret
manager="$runtime_root/shared/bin/switch-release.sh"
env_dir="$runtime_root/shared/env"
source "$env_dir/production.env"
export REDIS_URL

for release_sha in "$rollback_sha" "$candidate_sha"; do
  "$runtime_root/releases/$release_sha/infra/local/validate-release.sh" \
    "$release_sha" --env-dir "$env_dir"
done

start_business() {
  start_ok=true
  for component in api grading export; do
    plist="$agents/com.paper-grading.$component.plist"
    if ! launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      if ! launchctl bootstrap "gui/$UID" "$plist"; then
        start_ok=false
      fi
    fi
    if ! launchctl kickstart -k "gui/$UID/com.paper-grading.$component"; then
      start_ok=false
    fi
  done
  [[ "$start_ok" = true ]]
}

assert_no_workers() {
  PYTHONPATH="$runtime_root/current/backend" \
    "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

nodes = Celery("stage14_switch_check", broker=os.environ["REDIS_URL"]).control.inspect(timeout=3).ping() or {}
if nodes:
    raise SystemExit("stage14_workers_still_running_before_switch")
PY
}

restore_rollback_on_failure() {
  original_status=$?
  trap - EXIT INT TERM
  set +e
  print -u2 "stage14_backend_candidate_restore_failed_recovering_rollback=true"
  recovery_ok=true
  for component in grading export api; do
    plist="$agents/com.paper-grading.$component.plist"
    if launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      launchctl bootout "gui/$UID" "$plist"
      if (( $? != 0 )); then recovery_ok=false; fi
    fi
  done
  if assert_no_workers; then
    if "$manager" "$rollback_sha"; then
      start_business
      if (( $? != 0 )); then recovery_ok=false; fi
    else
      recovery_ok=false
    fi
  else
    recovery_ok=false
  fi
  recovered=false
  for _ in {1..60}; do
    current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current" 2>/dev/null)
    if [[ "$current_target" = "$runtime_root/releases/$rollback_sha" ]] && \
       "$runtime_root/current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
      recovered=true
      break
    fi
    sleep 2
  done
  if [[ "$recovery_ok" = true && "$recovered" = true ]]; then
    print -u2 "stage14_rollback_recovered_after_failed_candidate_restore=true"
  else
    print -u2 "stage14_rollback_recovery_failed=true"
  fi
  exit "$original_status"
}
trap 'exit 130' INT TERM
trap restore_rollback_on_failure EXIT

for component in grading export api; do
  plist="$agents/com.paper-grading.$component.plist"
  if launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID" "$plist"
  fi
done
assert_no_workers
"$manager" "$candidate_sha"
start_business
for _ in {1..60}; do
  current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current")
  if [[ "$current_target" = "$runtime_root/releases/$candidate_sha" ]] && \
     "$runtime_root/current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    trap - EXIT INT TERM
    print "stage14_backend_candidate_restored=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_backend_candidate_restored=false"
exit 1
)
```

执行位置：Codex Sites。私有部署候选 Sites 版本，轮询到 `succeeded`，再次确认 owner-only，并复核五个路径和 API 健康。

候选 Sites 的部署调用、状态轮询、owner-only、五路径或 API 健康复核中任一项失败，都立即把 Mac 按 6.3 的回滚块切回回滚 SHA，并私有部署回滚 Sites 版本；回滚 Sites 也必须完成相同复核。保持维护窗口，不创建第三个版本。

最后：

1. Chrome 再检查五个路径；
2. UptimeRobot 结束维护窗口，等待 HTTP 和 Heartbeat 都恢复正常；
3. 重跑 6.1，确认队列仍为 0；
4. Supabase Dashboard → Database → Network Restrictions 只读记录当前状态；若仍全网放行，写“用户接受的例外”，不能写“安全通过”；
5. 生产配额仍关闭时，记录“活跃容量告警未启用”。

## 最终通过标准

以下六项必须全部为 `true`：

```text
code_and_ci=true
private_deployment_and_runtime=true
readonly_production_smoke=true
single_paid_flow=true
alert_and_recovery=true
rollback_and_candidate_restore=true
```

任一项不是 `true`，阶段 14 都保持“进行中”。质量校准和生产上线最终验收仍是阶段 14 之后的独立事项。

## 最终安全回传模板

```text
候选 SHA：<40 位 SHA>
回滚 SHA：<40 位 SHA>
Sites 候选/回滚版本：<版本号>/<版本号>
数据库 revision：20260728_0019
code_and_ci：true/false
private_deployment_and_runtime：true/false
readonly_production_smoke：true/false
single_paid_flow：true/false；<通过数>/<失败数>
alert_and_recovery：true/false
rollback_and_candidate_restore：true/false
队列收口：true/false
配额/自动清理/备份：disabled
Database Network Restrictions：restricted/用户接受的全网放行例外
活跃容量告警：enabled/not enabled
```
