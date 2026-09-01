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
| 本地预部署门禁 | 2026-08-31：`stage14_predeployment_gate=true` | 部署代码变化后重跑 |
| 阶段 14 聚焦后端测试 | 87 通过、0 失败 | 相关代码变化后重跑 |
| Sites 构建与路由测试 | 3 通过、0 失败；包含外部 `ASSETS` 始终 404 的回归 | 前端或 Sites 配置变化后重跑 |
| 历史候选 SHA CI | `71e377c251958fdd943a5f982bd9db4741a98db2`：8/8 通过，但不含最新部署脚本修复 | 不得作为最终候选 |
| 失败候选 SHA CI | `27c67ac`：前 7 项通过，第 8 项 Git SHA 高熵误判；已在本地修复 | 不得使用或 rerun |
| 上一绿色候选 SHA CI | `d99dd5f`：8/8 通过，但仍会预建空 Tailscale 状态 | 不得作为最终候选 |
| 上一完整绿色 SHA CI | `39b14ac156e3c0b77085757b6851bf73f79d063c`：精确 SHA、8/8 通过，但不含本轮 Funnel 和零费用硬门禁 | 不得作为最终候选 |
| Sites 兼容回滚 SHA CI | `3b0a3ed057978a764248c5e306e09fae5b947260`：8/8 通过且空 `ASSETS` 页面返回 200 | 不需要 |
| 当前候选 SHA CI | 以本文件所在 `main` HEAD 为准，必须由 1.3 精确核对 8/8 | 每次提交后都要重跑 |
| PostgreSQL、Auth、Storage、Redis、Worker、供应商、100 篇结构证据 | 已完成 | 禁止在生产重复做破坏性测试或 100 次模型调用 |
| 生产部署、零费用只读验收、告警、回滚 | 未执行 | 按下列节点执行 |

阶段 14 仍是“进行中”。本地与 CI 通过不代表生产验收完成。

## 不可违反的边界

1. 任何一步失败都停止；阶段 14 禁止任何模型调用、付费试用、购买、升级或按量计费操作。
2. 生产数据库只允许前向升级到 `20260728_0019`，禁止 downgrade。
3. Sites 全程保持 owner-only；API 和 Redis 只监听本机回环地址。
4. Mac 后端和 Sites 必须来自同一个候选 SHA；回滚时两端也必须使用同一个回滚 SHA。
5. 自动清理、备份、恢复演练和生产配额继续关闭；启用时另行授权。
6. 密码、Token、Key、数据库 URL、论文内容、业务 ID 和签名 URL 不得写入 Git、文档、日志或聊天。
7. `PROVIDER_CALLS_ENABLED` 必须始终精确为 `false`；不得执行供应商连接测试、Rubric 生成、评分或真实 E2E。

## 零费用口径与进入门禁

本文件能保证的是“阶段 14 新增费用为 0”：不新增订阅、不购买额度、不触发模型 API 计费，也不使用付费功能。现有 Mac、用电、网络和已经购买的 ChatGPT 套餐不属于新增费用。若“完全免费”还要求这些既有成本也必须为 0，则当前 Sites 架构不满足，必须在节点 2 前停止，不能宣称阶段 14 通过。

进入节点 2 前，用户必须在各服务网页逐项确认；任一项无法确认就停止：

| 部分 | 必须看到 | 免费边界 |
|---|---|---|
| GitHub Actions | 仓库仍为 Public；8 个 jobs 都使用标准 `ubuntu-latest` | 标准 GitHub-hosted runner 对 Public 仓库免费；禁止 larger runner、Codespaces 和付费安全产品 |
| Supabase | 目标组织为 **Free / $0**，无付费 add-on，数据库、Storage、流量均在免费额度内 | Free 为 $0/月；超额会受限而不是收费；不得升级 Pro |
| Tailscale | 当前 tailnet 为 **Personal / $0 Free forever**，个人非商业用途，无付费试用 | 使用个人公共域账号；Funnel 对所有方案可用 |
| UptimeRobot | 当前账户为 **Free / 0**，不要求信用卡 | 只建 2 个监控；固定 5 分钟；只用免费邮件通知；禁止 SMS、语音、自动充值和维护窗口 |
| Codex Sites | 现有项目的保存与私有部署界面不出现购买、升级、credits 或额外价格 | 官方公开资料没有给出 Sites 独立免费价格；只有账户界面明确显示本次部署新增费用为 0 才可继续 |
| 模型供应商 | 不调用 | 不运行连接测试、Rubric 生成、评分和 `run-stage14-e2e.sh` |
| 本机组件 | 只使用现有 Mac、Homebrew、Redis、Python、Node.js、Tailscale CLI | 不购买软件或云主机；既有设备、网络和用电不计入“新增费用” |

当前依据：[GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[Supabase Free 与额度](https://supabase.com/pricing)、[Supabase Free 不收费规则](https://supabase.com/docs/guides/platform/cost-control)、[Tailscale Personal 定价](https://tailscale.com/pricing)、[Funnel 方案范围](https://tailscale.com/docs/features/tailscale-funnel)、[UptimeRobot Free 定价](https://uptimerobot.com/pricing/)、[UptimeRobot Free 监控类型](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan)、[UptimeRobot 维护窗口仅限付费](https://help.uptimerobot.com/en/articles/11360884-what-is-a-maintenance-window-and-how-to-use-it-in-uptimerobot)。定价可能变化，每次验收都必须重新看账户页面，不能只依赖本文。

## 验收节点

| 节点 | 执行人/位置 | 只做什么 | 通过标准 | 失败时 |
|---|---|---|---|---|
| 1. 代码与版本门禁 | Codex；项目根目录、GitHub Actions | 跑本地门禁，确认候选和回滚 SHA 的 CI | 本地门禁为 `true`；两个 SHA 各 8/8 通过；部署只读取封存 SHA，不读取当前工作树 | 不进入生产 |
| 2. 私有发布准备 | 用户授权后；Mac、Tailscale、Sites | 准备两个封存 release，启用 Funnel，保存候选/回滚两个 Sites 版本 | Funnel HTTPS 可用；Sites owner-only；两端版本都能追溯到对应 SHA | 恢复原 Funnel/Sites 状态，不迁移数据库 |
| 3. 目标环境与前向迁移 | 用户授权后；Supabase、Mac | 核对目标项目、空闲队列、专用角色和环境文件；只前向迁移；安装并启动运行环境 | revision=`20260728_0019`；环境文件 `0600`；API/Redis 仅回环；6 个 LaunchAgent 正常；API、三个 Worker、Tailscale 强退和重新登录后能恢复 | API/Worker 保持停止；不 downgrade、不清 Redis |
| 4. 无写入生产冒烟 | Codex 可协助；正式 Sites 与 Funnel URL | 检查 Sites 页面、HTTPS、健康接口、安全响应头和 CORS | 页面可访问且深层路径不 404；API 健康；CORS 只允许正式 Sites origin；无业务写入 | 不进入下一节点 |
| 5. 零费用只读业务检查 | 用户；正式网站、Supabase SQL Editor | 以既有账户登录，只浏览页面；核对模型调用硬开关和数据库计数未变化 | `PROVIDER_CALLS_ENABLED=false`；无新作业、批次、attempt、导出或供应商请求 | 保持硬开关关闭并停止 |
| 6. 告警、回滚与收口 | 用户授权后；UptimeRobot、Mac、Sites、Supabase | 实际触发一次免费邮件告警和恢复；暂停监控后同时回滚 Mac 与 Sites，再恢复候选；最后只读检查 | 告警和恢复均收到；两端回滚成功且已恢复候选；数据库仍为 `0019`；Redis 未清；队列为 0；关闭项仍关闭 | 暂停监控，恢复最后一组一致版本 |

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
| 阶段 14 聚焦后端测试 | 87 | 0 |
| 完整后端回归 | 513 | 0 |
| 前端单元测试 | 70 | 0 |
| Sites 构建与路由测试 | 2 | 0 |
| 桌面与手机浏览器测试 | 2 | 0 |
| 源码与 Sites 构建密钥扫描 | 2 | 0 |
| 历史候选 SHA GitHub CI | 8 | 0 |
| 回滚 SHA GitHub CI | 8 | 0 |

`39b14ac156e3c0b77085757b6851bf73f79d063c` 已精确取得 8/8 CI，但不含本轮 Tailscale 1.98 Funnel 修复和模型调用硬开关。必须把本轮全部改动提交，并以新 SHA 再取得 8/8，才能进入节点 2。

### 1.2 生成并推送新候选

先执行 `git status --short`，人工确认只包含本轮 Funnel、零费用硬门禁、测试、验收文档和项目记录文件。文件清单以本节提交块为准；若出现其他文件，停止，不要提交。

用户确认允许提交和推送后，先在终端 A执行提交块。提交成功后不要再次执行此块：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test "$(git branch --show-current)" = "main"
git add -- \
  .github/workflows/ci.yml \
  ARCHITECTURE.md \
  CONTEXT.md \
  README.md \
  backend/app/config.py \
  backend/app/providers/dependencies.py \
  backend/app/rubrics/dependencies.py \
  backend/app/rubrics/service.py \
  backend/app/workers/celery_app.py \
  backend/tests/test_assignment_api.py \
  backend/tests/test_assignment_service.py \
  backend/tests/test_celery_runtime.py \
  backend/tests/test_config.py \
  backend/tests/test_provider_api.py \
  backend/tests/test_stage14_delivery_contract.py \
  backend/tests/test_stage14_local_deployment_scripts.py \
  docs/STAGE14_ACCEPTANCE.md \
  findings.md \
  infra/local/production.env.example \
  infra/local/run-component.sh \
  infra/local/stage14-funnel.sh \
  infra/local/update-production-env.sh \
  infra/local/validate-release.sh \
  infra/local/verify-runtime.sh \
  infra/local/watchdog.sh \
  lessons.md \
  progress.md \
  task_plan.md
git diff --cached --check
git commit -m "fix: enforce zero-cost stage 14 acceptance"
candidate_sha=$(git rev-parse HEAD)
print "candidate_sha=$candidate_sha"
print "stage14_candidate_committed=true"
)
```

再执行下面的推送块。该块可安全重复执行；如果网络失败，只重试此块，不要重跑提交块：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test "$(git branch --show-current)" = "main"
candidate_sha=$(git rev-parse HEAD)
git -c http.version=HTTP/1.1 push origin HEAD:main
remote_sha=$(git -c http.version=HTTP/1.1 ls-remote origin refs/heads/main | /usr/bin/cut -f1)
test "$candidate_sha" = "$remote_sha"
print "candidate_sha=$candidate_sha"
print "stage14_candidate_pushed=true"
)
```

最终 `candidate_sha` 必须是包含上述全部文件的最新提交；不得继续使用 `39b14ac` 或更旧 SHA 进入节点 2。

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
| 终端 D | 告警、回滚、恢复候选 | 稳定 `current` release |
| Supabase SQL Editor | revision、队列和安全状态的只读 SQL | 目标生产项目 |
| Supabase Dashboard | Auth、Storage、Network Restrictions | 目标生产项目 |
| Codex Sites | 保存、私有部署、回滚前端版本 | 现有 Sites 项目 |
| UptimeRobot | HTTP/Heartbeat 监控 | 当前个人账户 |
| Chrome/邮箱 | Tailscale 登录、Sites 页面、邀请和真实业务 | 用户本人操作 |

所有终端命令都复制完整代码块执行。任一块没有打印预期标记或返回非 0，立即停止，不执行下一块。

## 节点 2：私有发布准备

本节点会修改本机 Tailscale/Funnel、创建本机 release，并在 Sites 保存私有版本；执行前需用户明确授权。

先在 Supabase、Tailscale、UptimeRobot 和 Sites 账户页面完成“零费用口径与进入门禁”。全部符合后，在终端 A执行确认块；它不会代替网页检查，只防止误操作：

```zsh
(
set -euo pipefail
read -r "zero_cost_auth?确认所有账户页面均显示本次阶段14新增费用为0后，输入 I_CONFIRM_STAGE14_ZERO_INCREMENTAL_COST："
test "$zero_cost_auth" = "I_CONFIRM_STAGE14_ZERO_INCREMENTAL_COST"
print "stage14_zero_incremental_cost_authorized=true"
)
```

### 2.1 登录 Tailscale

先关闭会制造 fake-IP 的 VPN 系统代理/虚拟网卡模式。密码、Passkey 和验证码只由用户在 Chrome 输入。

执行位置：终端 B。

先自动确认当前项目目录就是节点 1 取得 8/8 CI 的候选，且没有未提交改动。这里读取的是 40 位 Git commit SHA，不是以 `sha256:` 开头的构建摘要；无需手工输入：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test "$(git branch --show-current)" = "main"
candidate_sha=$(git rev-parse HEAD)
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test -z "$(git status --porcelain)"
remote_sha=$(git -c http.version=HTTP/1.1 ls-remote origin refs/heads/main | /usr/bin/cut -f1)
test "$candidate_sha" = "$remote_sha"
print "candidate_sha=$candidate_sha"
print "stage14_tailscale_candidate_checkout_verified=true"
)
```

先执行下面的只读状态分类块。有效的非空状态会打印 `stage14_tailscale_state_valid=true`，此时直接跳过隔离块；文件不存在会打印 `stage14_tailscale_new_login_required=true`，也直接进入登录块：

```zsh
(
set -euo pipefail
state_file="$HOME/Library/Application Support/Paper Grading/shared/tailscale/tailscaled.state"
if [[ ! -e "$state_file" && ! -L "$state_file" ]]; then
  print "stage14_tailscale_new_login_required=true"
  exit 0
fi
test -f "$state_file"
test ! -L "$state_file"
test "$(/usr/bin/stat -f '%u' "$state_file")" = "$(/usr/bin/id -u)"
state_size=$(/usr/bin/stat -f '%z' "$state_file")
if [[ "$state_size" = "0" ]]; then
  print "stage14_empty_tailscale_state_detected=true"
else
  test "$state_size" -gt 0
  test "$(/usr/bin/stat -f '%Lp' "$state_file")" = "600"
  print "stage14_tailscale_state_valid=true"
fi
)
```

只有分类结果是 `stage14_empty_tailscale_state_detected=true`，才执行下面的隔离块。它会先再次证明文件仍为空，再停止临时 daemon 并移动到同目录备份；绝不会先停止持有有效身份的 daemon：

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
runtime_root="$HOME/Library/Application Support/Paper Grading"
state_file="$runtime_root/shared/tailscale/tailscaled.state"
test -f "$state_file"
test ! -L "$state_file"
test "$(/usr/bin/stat -f '%u' "$state_file")" = "$(/usr/bin/id -u)"
test "$(/usr/bin/stat -f '%z' "$state_file")" = "0"
./infra/local/tailscale-login.sh stop
backup_file="$state_file.empty.$(/bin/date -u '+%Y%m%dT%H%M%SZ')"
test ! -e "$backup_file"
/bin/mv -- "$state_file" "$backup_file"
/bin/chmod 600 "$backup_file"
test ! -e "$state_file"
print "stage14_empty_tailscale_state_quarantined=true"
)
```

若执行了隔离块，只有打印 `stage14_empty_tailscale_state_quarantined=true` 才继续。备份文件保留到阶段 14 完成，不要删除。

随后执行登录块：

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

必须使用包含本轮修复的新候选。旧脚本会因 Tailscale 1.98 的参数解析返回 `must specify either --service=... or --all`；该失败发生在配置写入前，随后看到 `No serve config` 只是说明 Funnel 尚未启用，不需要手工 `reset`。

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
candidate_sha=$(git rev-parse HEAD)
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test -z "$(git status --porcelain)"
remote_sha=$(git -c http.version=HTTP/1.1 ls-remote origin refs/heads/main | /usr/bin/cut -f1)
test "$candidate_sha" = "$remote_sha"
rollback_sha="3b0a3ed057978a764248c5e306e09fae5b947260" # pragma: allowlist secret
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

acceptance_dir="$runtime_root/shared/acceptance"
candidate_file="$acceptance_dir/candidate-sha"
test -d "$acceptance_dir"
test ! -L "$acceptance_dir"
if [[ -e "$candidate_file" || -L "$candidate_file" ]]; then
  test -f "$candidate_file"
  test ! -L "$candidate_file"
  test "$(/usr/bin/stat -f '%u' "$candidate_file")" = "$(/usr/bin/id -u)"
fi
candidate_temp="$candidate_file.$$"
trap '/bin/rm -f -- "$candidate_temp"' EXIT INT TERM
print -r -- "$candidate_sha" >"$candidate_temp"
/bin/chmod 600 "$candidate_temp"
/bin/mv -f "$candidate_temp" "$candidate_file"
trap - EXIT INT TERM
test "$(/usr/bin/stat -f '%z' "$candidate_file")" = "41"
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
4. 回滚版本只能从本机封存目录 `~/Library/Application Support/Paper Grading/releases/3b0a3ed057978a764248c5e306e09fae5b947260/frontend` 构建；候选版本只能从 `~/Library/Application Support/Paper Grading/releases/<候选完整 SHA>/frontend` 构建。禁止读取项目当前工作树。
5. 从回滚封存目录保存一个 Sites 版本，再从候选封存目录保存一个不同版本。
6. 私有部署候选版本，轮询到 `succeeded`；禁止公开部署。
7. 本机记录“SHA ↔ Sites 版本号”及“节点 2 前版本号”；不记录 source credential 或 bypass token。

以上任一步失败，都私有重新部署“节点 2 前版本”，轮询到 `succeeded` 并复核 owner-only；恢复完成前不进入节点 3。

### 2.5 Chrome 页面检查

以 Sites owner 身份打开并刷新：`/login`、`/auth/callback`、`/assignments`、`/grading-jobs`、`/exports`。

通过标准：五个路径都不返回 404；无痕窗口不能直接进入应用；Sites 保持 owner-only。此时 API 尚未启动，页面暂时显示后端不可用可以接受。

任一路径返回 404 时，不要反复重新部署同一个 Sites 版本，也不要进入节点 3。该候选立即作废；先修复源码，生成新的完整 Git SHA 并取得精确 CI 8/8，再从 2.3 重新准备 release、保存新 Sites 版本并重做 2.4—2.5。部署状态 `succeeded` 只表示平台完成部署，不能代替页面验收。

## 节点 3：目标环境、迁移与自动恢复

本节点包含生产配置和可能的单次前向迁移，必须在用户明确授权后执行。

### 3.1 Supabase 只读预检

执行位置：目标生产 Supabase Dashboard 和 SQL Editor。

先打开组织 Billing/Usage，必须同时满足：Plan=`Free`、当前费用=`$0`、没有 add-on/Marketplace/付费试用、项目未超过 500MB 数据库、1GB Storage、5GB egress 等当前免费额度。任何字段不是 0 元或无法确认，立即停止。免费项目可能因一周不活跃被暂停，这是可用性限制，不是收费理由。

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

1. 再次确认账户显示 `Free`、费用为 0、监控数不超过 50；不要开始 Solo/Team 试用。
2. 创建 HTTP(S) monitor：`<Funnel origin>/health/ready`，检查间隔固定为免费方案的 5 分钟，先保持暂停。
3. 创建 Heartbeat/Cron monitor：期望间隔设为 5 分钟，grace period 设为 2 分钟，先保持暂停。本机 watchdog 每 60 秒发送一次，仍在该免费窗口内。
4. 两个 monitor 都只选择免费邮件通知联系人；先用测试通知确认联系人可达。禁止 SMS、语音、自动充值和付费集成。
5. Heartbeat URL只存入密码管理器，下一步由脚本隐藏输入，不要发送到聊天。

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

脚本会固定写入 `PROVIDER_CALLS_ENABLED=false`。它不提供把该值改为 `true` 的提示；阶段 14 期间也禁止手工修改。

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
source "$env_dir/production.env"
test "${PROVIDER_CALLS_ENABLED:-}" = "false"
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
candidate_file="$runtime_root/shared/acceptance/candidate-sha"
test -f "$candidate_file"
test ! -L "$candidate_file"
test "$(/usr/bin/stat -f '%u' "$candidate_file")" = "$(/usr/bin/id -u)"
test "$(/usr/bin/stat -f '%Lp' "$candidate_file")" = "600"
test "$(/usr/bin/stat -f '%z' "$candidate_file")" = "41"
IFS= read -r candidate_sha <"$candidate_file"
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="3b0a3ed057978a764248c5e306e09fae5b947260" # pragma: allowlist secret
validator="$current/infra/local/validate-release.sh"
for release_sha in "$candidate_sha" "$rollback_sha"; do
  "$validator" "$release_sha" --env-dir "$env_dir"
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

## 节点 5：零费用只读业务检查

阶段 14 不再运行真实单篇业务流。原因很直接：Rubric 生成和评分都会调用外部模型，无法保证费用为 0。`run-stage14-e2e.sh --start|--resume|--postcondition` 三个命令全部禁止执行；真实模型质量校准移到阶段 14 之后，另行授权和计费。

### 5.1 验证模型调用硬开关

执行位置：终端 A。

该开关同时覆盖三条可能产生模型费用的入口：供应商连接测试不构造测试客户端，Rubric 自动
结构化在读取数据库前拒绝，评分任务和周期分发在访问数据库或网络前拒绝。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
env_dir="$runtime_root/shared/env"
candidate_file="$runtime_root/shared/acceptance/candidate-sha"
test -f "$candidate_file"
test ! -L "$candidate_file"
test "$(/usr/bin/stat -f '%z' "$candidate_file")" = "41"
IFS= read -r candidate_sha <"$candidate_file"
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test "$(/usr/bin/stat -f '%Y' "$runtime_root/current")" = \
  "$runtime_root/releases/$candidate_sha"

set -a
source "$env_dir/production.env"
set +a
test "${PROVIDER_CALLS_ENABLED:-}" = "false"
PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
from app.config import Settings

if Settings.load().provider_calls_enabled:
    raise SystemExit("stage14_api_provider_calls_enabled")
PY

set -a
source "$env_dir/grading-worker.env"
set +a
PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
from app.config import WorkerSettings

if WorkerSettings.load().provider_calls_enabled:
    raise SystemExit("stage14_worker_provider_calls_enabled")
PY

"$current/infra/local/verify-runtime.sh"
print "stage14_zero_cost_runtime_guard=true"
)
```

### 5.2 保存只读基线并浏览页面

执行位置：Supabase SQL Editor。运行下面的只读查询，把一行结果保存在本机验收记录；不要发到聊天：

```sql
select
  (select count(*) from public.assignments) as assignments_count,
  (select count(*) from public.grading_jobs) as grading_jobs_count,
  (select count(*) from public.grading_job_items) as grading_items_count,
  (select count(*) from public.grading_attempts) as grading_attempts_count,
  (select count(*) from public.exports) as exports_count,
  (select max(provider_call_started_at) from public.grading_attempts)
    as last_provider_call_started_at;
```

执行位置：Chrome。使用一个已经存在的账户登录，只浏览 `/assignments`、`/grading-jobs`、`/exports` 和已有详情页。不得点击或提交以下操作：邀请账户、创建/修改作业、生成 Rubric、上传文件、创建批改任务、供应商连接测试、生成导出。页面不空白、无 404、Console 错误和警告为 0 即可。

### 5.3 证明浏览没有产生写入或模型调用

回到 Supabase SQL Editor，原样重跑 5.2 的查询。六列必须与基线完全一致。然后终端 A执行人工确认块：

```zsh
(
set -euo pipefail
read -r "readonly_auth?确认5.2前后六列完全一致后，输入 I_CONFIRM_STAGE14_READONLY_NO_PROVIDER_CALL："
test "$readonly_auth" = "I_CONFIRM_STAGE14_READONLY_NO_PROVIDER_CALL"
print "stage14_zero_cost_readonly_business_check=true"
)
```

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

先在 UptimeRobot 启用 HTTP 和 Heartbeat 两个监控，等待两者显示正常，并确认免费邮件测试通知已送达。确认 6.1 全部归零后，在终端 D执行。停止导出 Worker 后，脚本最多等待 12 分钟；这是 5 分钟 Heartbeat、2 分钟 grace、免费方案检测和邮件投递余量。超时会自动恢复 Worker并判定失败。

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
if ! read -t 720 -r "alert_result?收到 UptimeRobot 免费邮件告警后输入 I_RECEIVED_ALERT："; then
  print -u2 "stage14_uptimerobot_alert_timeout=true"
  exit 1
fi
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

UptimeRobot 免费方案不能建立维护窗口。先手工暂停 HTTP 和 Heartbeat 两个监控，确认页面均显示暂停，再次确认 6.1 队列为 0，然后终端 D执行：

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
candidate_file="$runtime_root/shared/acceptance/candidate-sha"
test -f "$candidate_file"
test ! -L "$candidate_file"
test "$(/usr/bin/stat -f '%u' "$candidate_file")" = "$(/usr/bin/id -u)"
test "$(/usr/bin/stat -f '%Lp' "$candidate_file")" = "600"
test "$(/usr/bin/stat -f '%z' "$candidate_file")" = "41"
IFS= read -r candidate_sha <"$candidate_file"
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="3b0a3ed057978a764248c5e306e09fae5b947260" # pragma: allowlist secret
manager="$runtime_root/shared/bin/switch-release.sh"
env_dir="$runtime_root/shared/env"
source "$env_dir/production.env"
export REDIS_URL
validator="$runtime_root/releases/$candidate_sha/infra/local/validate-release.sh"

for release_sha in "$candidate_sha" "$rollback_sha"; do
  "$validator" "$release_sha" --env-dir "$env_dir"
done

start_components() {
  start_ok=true
  for component in "$@"; do
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
      start_components api grading export
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
start_components api export
verify_readonly_rollback() {
  current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current")
  [[ "$current_target" = "$runtime_root/releases/$rollback_sha" ]] || return 1
  launchctl print "gui/$UID/com.paper-grading.api" >/dev/null 2>&1 || return 1
  launchctl print "gui/$UID/com.paper-grading.export" >/dev/null 2>&1 || return 1
  if launchctl print "gui/$UID/com.paper-grading.grading" >/dev/null 2>&1; then
    return 1
  fi
  curl --fail --silent --show-error http://127.0.0.1:8000/health/live >/dev/null || return 1
  curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null || return 1
  worker_status="$("$runtime_root/current/.venv/bin/celery" \
    -b "$REDIS_URL" inspect ping --json --timeout 10)" || return 1
  print -rn -- "$worker_status" | "$runtime_root/current/.venv/bin/python" -c '
import json
import sys

names = list(json.load(sys.stdin))
if len(names) != 1 or not names[0].startswith("exports@"):
    raise SystemExit("stage14_rollback_worker_set_invalid")
' || return 1
  PYTHONPATH="$runtime_root/current/backend" \
    "$runtime_root/current/.venv/bin/python" - <<'PY'
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
    raise SystemExit("stage14_rollback_broker_not_empty")
PY
}
for _ in {1..60}; do
  if verify_readonly_rollback; then
    trap - EXIT INT TERM
    print "stage14_backend_readonly_rollback_verified=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_backend_readonly_rollback_verified=false"
exit 1
)
```

回滚 SHA 早于本轮模型硬开关，因此回滚期间评分/维护 Worker 必须保持停止，只启动 API 和导出 Worker做只读健康验证。不得进入供应商配置页或触发任何写操作。

执行位置：Codex Sites。私有部署已经保存的回滚 Sites 版本，轮询到 `succeeded`；再次确认 owner-only。Chrome 只检查五个路径能加载和 API 健康，不登录、不写入。

Sites 回滚的部署调用、状态轮询、owner-only 复核、五路径检查或 API 健康检查中任一项失败，都立即执行 6.4 的 Mac 候选恢复块，并私有部署候选 Sites 版本；候选部署也必须完成状态轮询、owner-only、五路径和 API 健康复核。两端恢复为候选且全部验证通过前保持两个监控暂停。

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
candidate_file="$runtime_root/shared/acceptance/candidate-sha"
test -f "$candidate_file"
test ! -L "$candidate_file"
test "$(/usr/bin/stat -f '%u' "$candidate_file")" = "$(/usr/bin/id -u)"
test "$(/usr/bin/stat -f '%Lp' "$candidate_file")" = "600"
test "$(/usr/bin/stat -f '%z' "$candidate_file")" = "41"
IFS= read -r candidate_sha <"$candidate_file"
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
rollback_sha="3b0a3ed057978a764248c5e306e09fae5b947260" # pragma: allowlist secret
manager="$runtime_root/shared/bin/switch-release.sh"
env_dir="$runtime_root/shared/env"
source "$env_dir/production.env"
export REDIS_URL
validator="$runtime_root/releases/$candidate_sha/infra/local/validate-release.sh"

for release_sha in "$rollback_sha" "$candidate_sha"; do
  "$validator" "$release_sha" --env-dir "$env_dir"
done

start_components() {
  start_ok=true
  for component in "$@"; do
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

verify_readonly_rollback() {
  current_target=$(/usr/bin/stat -f '%Y' "$runtime_root/current" 2>/dev/null) || return 1
  [[ "$current_target" = "$runtime_root/releases/$rollback_sha" ]] || return 1
  launchctl print "gui/$UID/com.paper-grading.api" >/dev/null 2>&1 || return 1
  launchctl print "gui/$UID/com.paper-grading.export" >/dev/null 2>&1 || return 1
  if launchctl print "gui/$UID/com.paper-grading.grading" >/dev/null 2>&1; then
    return 1
  fi
  curl --fail --silent --show-error http://127.0.0.1:8000/health/live >/dev/null || return 1
  curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null || return 1
  worker_status="$("$runtime_root/current/.venv/bin/celery" \
    -b "$REDIS_URL" inspect ping --json --timeout 10)" || return 1
  print -rn -- "$worker_status" | "$runtime_root/current/.venv/bin/python" -c '
import json
import sys

names = list(json.load(sys.stdin))
if len(names) != 1 or not names[0].startswith("exports@"):
    raise SystemExit("stage14_rollback_worker_set_invalid")
' || return 1
  for queue in paper_grading.grading paper_grading.maintenance paper_grading.exports; do
    [[ "$(/opt/homebrew/bin/redis-cli -u "$REDIS_URL" LLEN "$queue")" = "0" ]] || return 1
  done
  [[ "$(/opt/homebrew/bin/redis-cli -u "$REDIS_URL" HLEN unacked)" = "0" ]] || return 1
  [[ "$(/opt/homebrew/bin/redis-cli -u "$REDIS_URL" ZCARD unacked_index)" = "0" ]] || return 1
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
      start_components api export
      if (( $? != 0 )); then recovery_ok=false; fi
    else
      recovery_ok=false
    fi
  else
    recovery_ok=false
  fi
  recovered=false
  for _ in {1..60}; do
    if verify_readonly_rollback; then
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
start_components api grading export
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

候选 Sites 的部署调用、状态轮询、owner-only、五路径或 API 健康复核中任一项失败，都立即把 Mac 按 6.3 的回滚块切回回滚 SHA，并私有部署回滚 Sites 版本；回滚 Sites 也必须完成相同复核。保持两个监控暂停，不创建第三个版本。

最后：

1. Chrome 再检查五个路径；
2. UptimeRobot 手工恢复 HTTP 和 Heartbeat 两个监控；服务已恢复时，暂停后再恢复会触发新检查。等待两者都正常；
3. 重跑 6.1，确认队列仍为 0；
4. Supabase Dashboard → Database → Network Restrictions 只读记录当前状态；若仍全网放行，写“用户接受的例外”，不能写“安全通过”；
5. 生产配额仍关闭时，记录“活跃容量告警未启用”。

## 最终通过标准

以下六项必须全部为 `true`：

```text
code_and_ci=true
private_deployment_and_runtime=true
readonly_production_smoke=true
zero_cost_readonly_business_check=true
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
zero_cost_readonly_business_check：true/false
alert_and_recovery：true/false
rollback_and_candidate_restore：true/false
队列收口：true/false
配额/自动清理/备份：disabled
模型调用：disabled；新增费用：0
Database Network Restrictions：restricted/用户接受的全网放行例外
活跃容量告警：enabled/not enabled
```
