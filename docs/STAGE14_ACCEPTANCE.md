# 阶段 14 验收工作流程：测试、安全与 Sites + 常开 Mac 部署

> 本文件是阶段 14 剩余验收的唯一执行顺序。Runbook 提供背景；若 Runbook 与本文的
> 顺序、命令或安全边界冲突，立即停止，以本文为准并先修正文档。

## 0. 当前结论和禁止线

阶段 14 状态仍为“进行中”。本文已按当前仓库、开发记录和真实验收记录重写；
2026-08-18 已补齐第 3.2 节的本地代码门禁，但这不等于生产部署完成。

### 0.1 当前可以做什么

现在先执行第 3.2 节“部署前代码门禁”，当前预期输出 `stage14_predeployment_gate=true`。
第 3.2、3.3 节通过后，才能执行第 4.1—4.3 节取得固定 Funnel origin，再在第 4.4 节准备
release。第 4.4 节通过以前，禁止生产迁移、Sites 发布、Supabase Auth 修改、生产环境文件
创建、`launchd` 安装、真实模型调用或回滚演练。

当前真实状态如下：

| 项目 | 当前事实 | 判定 |
|---|---|---|
| Git | `main` 与 `origin/main` 当前均为 `eb2f360`；本文和 `CONTEXT.md` 正在修改 | 该 SHA 只作既有基线，不是修复门禁后的最终发布 SHA |
| Sites | 项目存在、当前操作者是 owner、仅允许本人；保存版本数为 0、尚无正式部署 URL | owner-only 边界已确认，发布未完成 |
| 生产环境文件 | `.env.stage14-production`、`.env.stage14-grading-worker` 均不存在 | 尚未配置 |
| LaunchAgent | `com.paper-grading.*.plist` 当前为 0 个 | 尚未安装 |
| Tailscale | CLI 和 `0600` state 已存在；socket 残留，但 daemon 已退出 | 必须先修复 stale socket 和进程接管 |
| Redis | 当前仅观察到回环监听 | 仍须在正式流程中重新验证 `PONG`、保护模式和 `noeviction` |

### 0.2 当前部署前代码门禁

| 门禁 | 当前状态 | 未通过时的处理 |
|---|---|---|
| 原子双版本发布 | release/current/shared 脚本和 symlink 回归已完成；等待新 SHA CI | 停止，不用 `git checkout` 或当前工作树模拟回滚 |
| Tailscale 生命周期 | PID/socket/state 的 start/login/status/stop 已实现；真实接管未验收 | 停止，不让临时 daemon 与 `launchd` 争用 state/socket |
| `launchd` 真实恢复 | runner、installer、runtime 检查已改造；尚无真实登录后恢复证据 | 停止，不以“label 已加载”冒充 Worker 在线 |
| 运行脚本依赖 | 已移除普通 `rg` 依赖并通过本地门禁 | 任一新依赖缺失即停止 |
| Heartbeat 密钥边界 | 已改用 `curl --config`，URL 不进入 argv；尚未创建正式监控 | 正式配置前继续保持监控暂停 |
| 私有 Sites E2E | 已实现只对 Sites 同源请求注入 bypass，并禁用 trace/截图/视频 | 任何跨源泄漏证据都停止；禁止公开 Sites 规避 |
| E2E 总超时 | 已提升到 1,800 秒并通过配置加载门禁 | 后续缩短时必须重新验证各步骤 SLA |
| E2E 防重跑与恢复 | `--start` 已有 O_EXCL 标记；`--resume`/`--postcondition` 仍 fail closed | 付费流前必须补齐，防止重复批次和重复计费 |
| bypass 私密交接 | Sites rotation 与本机 Playwright 之间没有不经过聊天、文件或命令参数的安全注入通道 | 先实现受控内存交接；不能显示或复制 token |
| Storage 大小契约 | 论文 20MiB、导出/bucket 50MiB 与四种 MIME 的代码回归已通过 | 生产 bucket 不一致时另行授权修改 |

第 3 节给出了这些门禁的固定接口和检查命令。门禁修复必须形成新的提交，并让该提交的
GitHub CI 8 项全部通过；`eb2f360` 不能继续当最终发布 SHA。

### 0.3 已完成且禁止在生产重复执行的证据

| 范围 | 已完成结果 | 本次处理 |
|---|---|---|
| 本地普通门禁 | 后端 497 通过；前端普通门禁 73 通过，其中 Vitest 70、依赖审计 3；失败 0 | 新 SHA 仍须由 CI 重跑 |
| Sites 专项 | 2 通过、失败 0 | 最终发布 SHA 改变后由 CI 和第 4.4 节重跑 |
| 本地浏览器 | 2 通过、失败 0 | 不替代正式部署浏览器验收 |
| 发布基线 CI | `eb2f360`：8 通过、失败 0 | 仅作历史证据 |
| PostgreSQL 4.1 | 独立 Supabase PostgreSQL：8 通过、失败 0；迁移头 `20260728_0019` | 禁止在生产重跑权限破坏、downgrade 或测试写入 |
| Auth/JWT/Storage 4.2 | 3 通过、失败 0 | 禁止在生产重跑账户停用、恢复或临时 Storage 对象测试 |
| Redis/Celery/Worker 第 5 节 | 用户已确认完成 | 只验新的 Mac + `launchd` 部署边界 |
| 供应商冒烟第 6.1 节 | 用户已确认完成 | 本次仅做一个完整生产业务流，不重跑基础连接测试 |
| 阶段 13 配额 | 真实 PostgreSQL 4 通过、失败 0，验收后重新关闭 | 不重跑阈值写入探针 |
| 阶段 13保留与备份 | 保留 17 项、备份 8 项已验证；正式开关保持关闭 | 只读确认关闭，不执行删除、备份或恢复 |

### 0.4 100 篇批量的最终判定

第 6.2 节按组合证据完成，不再执行 100 次真实模型调用：

| 风险 | 已有证据 | 结论 |
|---|---|---|
| 真实输入规模 | DOCX 51、PDF 49、哈希重复 0；当前解析器 100 通过、失败 0 | 已覆盖输入与解析 |
| 漏卷、重复、串卷 | 阶段 10 验证 100 个不同 submission、位置 `0—99`、零 attempt 后取消 | 已覆盖批次映射 |
| 当前代码单次投递 | 当前自动化覆盖 100 篇按保存顺序唯一投递 | 已覆盖投递契约 |
| Worker、租约和队列 | 阶段 14 第 5 节已真实验收 | 已覆盖执行基础设施 |
| Excel 逐行映射 | 阶段 12 已验证 100 篇三个明细表映射 | 已覆盖导出 |
| 启用供应商连接 | 阶段 14 第 6.1 节已完成 | 已覆盖真实连接 |

证据见[阶段 10 验收](STAGE10_ACCEPTANCE.md)、[阶段 12 验收](STAGE12_ACCEPTANCE.md)、
`backend/tests/test_grading_job_service.py` 和 `backend/tests/test_export_xlsx.py`。

以后若要测 100 篇耗时、并发、失败率或费用，必须另行定义样本、SLA、费用硬上限和停止
条件；它不属于本次部署验收，也不能代替后续评分质量校准。

## 1. 执行位置、固定路径和操作顺序

### 1.1 执行位置

所有终端均为常开 Mac 上新开的独立 zsh 会话，互不共享变量。

| 名称 | 用途 | 默认工作目录 |
|---|---|---|
| 终端 A | Git/CI、release、Supabase 迁移、环境配置、Redis、`launchd`、健康和队列检查 | `/Users/a1-6/Documents/Paper Grading` |
| 终端 B | Tailscale 临时登录、Funnel、本机 daemon 到 `launchd` 的接管 | `/Users/a1-6/Documents/Paper Grading` |
| 终端 C | 只执行一次的生产浏览器验收 | `/Users/a1-6/Documents/Paper Grading` |
| 终端 D | 告警、回滚和失败恢复；不复用终端 C 的凭据 | `/Users/a1-6/Documents/Paper Grading` |
| Supabase SQL Editor | 目标生产项目的只读 SQL；角色密码不在 SQL Editor 设置 | 无本机目录 |
| Supabase Dashboard | Auth URL、公开注册、Storage、Database Network Restrictions 页面 | 目标生产项目 |
| Codex Sites 连接器 | 读取项目、取得 source credential、保存版本、私有部署、状态轮询和回滚 | 复用现有 Sites `project_id` |
| GitHub Actions | 两个精确 SHA 的 CI 结果 | 当前 GitHub 仓库 |
| UptimeRobot | HTTP 和 Heartbeat 监控 | 当前个人账户 |
| Chrome/邮箱 | Tailscale 登录、owner-only Sites、教师邀请和正式业务页面 | 用户本人操作 |

### 1.2 固定路径

第 3 节开发门禁完成后，部署代码必须统一使用以下稳定目录；不得再把可变数据放进 Git
release：

| 内容 | 固定位置 |
|---|---|
| 项目开发仓库 | `/Users/a1-6/Documents/Paper Grading` |
| 生产运行根 | `$HOME/Library/Application Support/Paper Grading` |
| 不可变版本 | `$HOME/Library/Application Support/Paper Grading/releases/<完整 SHA>` |
| 当前版本链接 | `$HOME/Library/Application Support/Paper Grading/current` |
| 共享密钥配置 | `$HOME/Library/Application Support/Paper Grading/shared/env` |
| 共享 Tailscale state/socket | `$HOME/Library/Application Support/Paper Grading/shared/tailscale` |
| 生产日志 | `$HOME/Library/Application Support/Paper Grading/shared/logs` |

环境目录和 Tailscale 目录必须为 `0700`，环境文件和 state 必须为 `0600`；日志目录必须为
`0700`、日志文件必须为 `0600`。所有 release 必须来自已推送、CI 全绿的精确 SHA；每个
release 有匹配的依赖或先验证锁文件完全相同。

### 1.3 总顺序

| 顺序 | 操作 | 写入边界 |
|---:|---|---|
| 0 | 第 3.1—3.3 节代码/CI 门禁 | 只读或写开发记录；不碰生产 |
| 1 | Tailscale 登录、Funnel、第 4.4 节双 release 和 owner-only Sites URL 引导 | 改本机 release、Tailscale/Sites；无业务写入 |
| 2 | Supabase 只读核对、必要时单独授权角色密码 | 默认只读；密码设置需单独授权 |
| 3 | Auth URL、暂停的 UptimeRobot、生产环境和只读配置探针 | 页面配置和本机密钥文件 |
| 4 | 无任务门禁和只前向迁移 | 唯一常规数据库结构写入 |
| 5 | Redis、`launchd` 接管、重启和重新登录恢复 | 本机服务状态 |
| 6 | HTTPS/CORS/owner-only Sites 无业务写入冒烟 | 只读请求 |
| 7 | 一个单篇完整付费业务流 | 真实 Auth、数据库、Storage 和模型费用 |
| 8 | Worker/队列/SQL/关闭项收口 | 只读 |
| 9 | 可逆告警、双版本回滚、恢复候选 | 服务和 Sites 版本切换；数据库不回退 |
| 10 | Review、记录和最终 CI | 文档/Git |

首次部署存在一个 URL 引导例外：后端环境需要 Sites origin，Sites 构建又需要 Funnel URL。
因此先让 Tailscale/Funnel 产生固定 API origin，再私有保存和部署 Sites 以取得固定前端
origin。此时 Sites 必须保持 owner-only、监控保持暂停、后端尚不提供业务。取得两个
origin 后，正式运行发布仍遵循“迁移 → Redis/Mac → Funnel → Sites 冒烟”的依赖关系。

## 2. 全局安全规则

1. 任一命令失败，立即停止后续步骤；不得把失败命令直接再跑一次。
2. 所有 zsh 代码块都在子 Shell `(...)` 中执行，避免 `set -euo pipefail` 污染共享终端。
3. 不启用 `set -x`。密码、Token、Key、数据库 URL、邮箱、论文路径、签名 URL和模型原始
   响应不得写入命令行参数、Git、文档、截图、日志或聊天。
4. 所有生产数据库迁移只允许 `upgrade 20260728_0019`；禁止 `downgrade`。
5. 禁止 `FLUSHALL`、`FLUSHDB`、删除队列、删除验收业务数据、清空 Storage 或修改生产
   migration history。
6. 禁止公开 Sites、开放路由器端口、把 API 改为监听 `0.0.0.0`，或用临时公网 IP 代替
   Funnel。
7. `tailscale status`、`funnel status`、Supabase URL、project ref 和网络地址只在本机看；
   安全回传不得粘贴原始输出。
8. Supabase 页面、Sites、UptimeRobot、真实邀请、模型调用、角色密码、生产迁移和回滚
   都是外部状态变化，必须在对应步骤取得明确授权。
9. 自动清理、备份创建、备份清理、恢复演练和生产配额继续关闭；任何启用都属于新的
   授权任务。
10. 一旦单篇 E2E 已生成 Rubric 或创建批次，禁止重跑整条 E2E；先恢复已有任务。

安全回传只允许：发布/回滚 SHA、Sites 版本号、迁移版本、固定布尔标记、HTTP 状态、
服务状态、聚合计数、告警/恢复是否收到、回滚结果和测试通过/失败数量。

## 3. 第 0 步：部署前代码、双版本和 CI 门禁

### 3.1 必须先完成的开发接口

这部分由 Codex 在独立开发任务中实现并测试，不由用户在生产部署时临时拼接。

| 必须存在的接口 | 固定职责 |
|---|---|
| `infra/local/stage14-predeployment-gate.sh` | 只读检查本节全部代码门禁；成功只输出 `stage14_predeployment_gate=true` |
| `infra/local/prepare-release.sh <SHA>` | 从已推送 commit 安装匹配依赖并构建 Sites；seal 不可变 release；处理候选时把匹配 switcher 原子安装到 `shared/bin` 并校验 hash/owner/`0700` |
| `infra/local/validate-release.sh <SHA> [--env-dir <path>]` | 用该 release 自己的 venv 静态加载 common/grading 三类 Settings；核对 manifest SHA、API/Supabase origin 和 key hash，不输出公开 key |
| `infra/local/switch-release.sh <SHA> [--prepare-only]` | 只切到 `SEALED` release；`current` 必须是目标绝对路径的原子 symlink；进程冻结与恢复由调用步骤显式完成；脚本安装到稳定 `shared/bin` |
| `infra/local/update-production-env.sh` | 交互生成两份 staging env，离线验证、目录级原子替换；失败保留旧版，支持经明确授权安全更正输入 |
| `infra/local/run-stage14-e2e.sh` | 从受控进程环境接收 bypass，预检输入、原子 started 标记、外置输出目录并执行一次；当前 `--resume`/`--postcondition` 会 fail closed，付费流前仍须补齐并重新通过门禁 |
| `infra/local/stage14-funnel.sh enable\|status\|restore` | 写前用同一 socket 的 `serve get-config <file> --all` 保存可恢复的完整配置；只允许唯一 HTTPS 根路由到 `http://127.0.0.1:8000`；`restore` 用 `serve set-config <file> --all` 恢复，Funnel JSON 只作只读断言 |
| `infra/local/tailscale-login.sh start\|login\|status\|stop` | `start` 受管启动并等 socket，`login` 对同一 socket 前台触发 `tailscale up`，识别 stale PID/socket，`stop` TERM+wait；与 `launchd` 共享 state |
| `infra/local/install-launch-agents.sh [--rollback-first-install]` | plist 固定走 `current`；env/state/log 固定走 `shared`；权限固定；不绑定开发仓库；首次安装用事务式记录，任一步失败时撤销本轮 6 个新 label、确认 API/三个 Worker 全停，并提供幂等回滚入口 |
| `infra/local/verify-runtime.sh` | 验证 6 个 label、回环监听、Redis、API、Funnel、三个 Worker、各自唯一队列和零泄密输出 |
| `infra/local/watchdog.sh` | 不依赖普通 PATH 的 `rg`；Heartbeat URL 不出现在进程参数；只有 API、Redis、三个 Worker 全健康才发送 |

同时必须完成：

- `frontend/playwright.real.config.ts` 与 `e2e/real-full-flow.spec.ts` 只对
  `E2E_REAL_BASE_URL` 同源请求添加
  `OAI-Sites-Authorization: Bearer <token>`；Funnel、Supabase Auth/Storage 等跨源请求绝不
  携带该 Header；
- bypass 只从本次受控执行器内存读取，不进聊天、剪贴板、命令参数、文件、trace、截图、
  视频、日志或报告；没有 Connector 到本机 PTY 的安全交接机制时，第 11 节必须停止；
- E2E 在任何写入前用 `O_EXCL` 等价语义在 `shared/acceptance` 创建一次性 started 标记；
  标记目录 `0700`、文件 `0600` 且永不删除/复用；`--start` 还必须先只读查询生产端，精确
  标题已有 assignment/job/attempt/export 任一记录即拒绝，并提供 postcondition/resume；
- Playwright 的 output、report、trace、截图和视频目录必须在 `shared/acceptance` 的本轮临时目录，
  不能写入封存 release；Console 只保留脱敏后的类型/计数，不能把完整 message 写进失败输出；
- 签名 URL 请求、JSON 解析和断言失败只抛固定错误码，不把原异常、URL、query 或对象路径
  交给 Playwright reporter；
- 使用受审自定义 reporter，只输出固定测试名和 pass/fail 计数；runner 不落原始 stdout/
  stderr，并在内存拒绝/脱敏邮箱、标题和文件路径后才显示固定结果；
- E2E 总超时至少覆盖 180 + 120 + 600 + 300 秒、允许的最大签名 URL TTL 300 秒和合理
  余量；若继续沿用现有各步骤上限，总超时不得低于 1,800 秒；
- runtime 契约测试覆盖 API、grading、maintenance、exports、Tailscale 的退出恢复和登录后
  恢复；
- LaunchAgent 首次安装必须 fail closed：任一 plist/bootstrap/runtime 验证失败，installer 自己
  撤销本轮新增的 6 个 label，停止 API、grading/maintenance、export 和 Tailscale，确认
  8000 无监听且三个 Worker 均不响应；只删除本轮新建且固定路径/owner 正确的 plist，不碰
  安装前已有配置。`--rollback-first-install` 必须幂等，可供第 9.3 节再次确认清理；
- 日志权限、环境文件非符号链接、shared/release 分离、stale socket 和失败恢复都有自动化
  回归；Celery Beat schedule 明确写入 `shared/state`，Python 不写 `__pycache__` 到 release；
- `verify-runtime.sh` 在真实路径检查 shared/env/state/log 各层非 symlink、owner 正确、目录
  `0700`、env/state/log 普通文件 `0600`；plist 不含 secret/env 值，日志扫描只输出布尔；
- `tailscale-login.sh start` 使用受管后台进程和原子 pidfile，只保证 client ready、允许
  `NeedsLogin`；`status --expect-running` 只在本 socket 的 `BackendState=Running` 时成功；
- Storage 契约统一为：Supabase 私有 bucket 的 `file_size_limit` 为 50MiB，允许
  PDF/DOCX/JSON/XLSX；论文上传和解析入口仍在应用层拒绝大于 20MiB 的文件，导出写入接受
  1—50MiB、拒绝大于 50MiB。以上三个边界和 bucket 元数据必须有自动化回归；
- 队列等待、失败率可由第 12 节聚合 SQL 观察；生产容量告警当前因配额关闭而不活跃，
  必须在最终记录写明这一限制，不能表述为“生产容量告警已启用”。若严格要求
  [开发计划](DEVELOPMENT_PLAN.md)中的活跃容量告警，须另行授权真实容量并启用后再完成
  阶段 14，或由用户明确批准调整计划。

### 3.2 运行代码门禁

执行位置：终端 A；工作目录：项目根目录；变量来源：无；生产写入：无。

```zsh
(
set -eo pipefail
cd "/Users/a1-6/Documents/Paper Grading"

required_executables=(
  infra/local/stage14-predeployment-gate.sh
  infra/local/prepare-release.sh
  infra/local/validate-release.sh
  infra/local/switch-release.sh
  infra/local/update-production-env.sh
  infra/local/run-stage14-e2e.sh
  infra/local/stage14-funnel.sh
  infra/local/tailscale-login.sh
  infra/local/install-launch-agents.sh
  infra/local/verify-runtime.sh
  infra/local/watchdog.sh
)

for script_path in "${required_executables[@]}"; do
  if [[ ! -x "$script_path" ]]; then
    print -u2 "stage14_predeployment_gate=false"
    exit 1
  fi
done

./infra/local/stage14-predeployment-gate.sh
)
```

预期只输出 `stage14_predeployment_gate=true`。该标记表示本机脚本、依赖、Shell 语法、
Python 导入和前端类型门禁已通过，不代表生产部署或外部服务验收已完成。不得跳过或用
手工口头判断代替。真实付费 E2E 的恢复入口仍按第 11 节单独检查，未补齐时必须停止。

### 3.3 提交、选择两个 SHA 并验证 GitHub CI

前置条件：第 3.2 节已通过；本文和门禁代码已经提交并推送；工作树干净。两个 SHA 必须
不同、都兼容 `0019`、都采用 Sites + Mac 方案。旧 Render 方案 SHA 不得作为回滚候选。

执行位置：终端 A；工作目录：项目根目录；变量来源：用户本机输入两个完整 SHA；生产
写入：无，`git fetch` 只更新本机远端引用。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
test -z "$(git status --porcelain)"
test "$(git branch --show-current)" = "main"

git fetch origin main
candidate_sha=$(git rev-parse HEAD)
test "$candidate_sha" = "$(git rev-parse origin/main)"
read -r "rollback_sha?输入完整回滚 SHA："

print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
print -rn -- "$rollback_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test "$candidate_sha" != "$rollback_sha"
git cat-file -e "${candidate_sha}^{commit}"
git cat-file -e "${rollback_sha}^{commit}"
git merge-base --is-ancestor "$rollback_sha" origin/main

origin_url=$(git remote get-url origin)
repo=$(STAGE14_ORIGIN_URL="$origin_url" node - <<'NODE'
const origin = process.env.STAGE14_ORIGIN_URL;
const match = origin.match(/github\.com(?::|\/)([^/:\s]+\/[^/\s]+?)(?:\.git)?$/);
if (!match) process.exit(1);
process.stdout.write(match[1]);
NODE
)
tmp_dir=$(mktemp -d)
trap '/bin/rm -rf "$tmp_dir"' EXIT

for sha in "$candidate_sha" "$rollback_sha"; do
  /usr/bin/curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --max-time 30 \
    --retry 2 \
    --header "Accept: application/vnd.github+json" \
    --header "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${repo}/actions/workflows/ci.yml/runs?head_sha=${sha}&per_page=1" \
    >"$tmp_dir/run.json"

  run_id=$(STAGE14_EXPECTED_SHA="$sha" STAGE14_JSON="$tmp_dir/run.json" node - <<'NODE'
const fs = require("node:fs");
const payload = JSON.parse(fs.readFileSync(process.env.STAGE14_JSON, "utf8"));
const runs = payload.workflow_runs;
if (!Array.isArray(runs) || runs.length !== 1) process.exit(1);
const run = runs[0];
if (
  run.head_sha !== process.env.STAGE14_EXPECTED_SHA ||
  run.status !== "completed" ||
  run.conclusion !== "success" ||
  !Number.isSafeInteger(run.id)
) process.exit(1);
process.stdout.write(String(run.id));
NODE
  )

  /usr/bin/curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --max-time 30 \
    --retry 2 \
    --header "Accept: application/vnd.github+json" \
    --header "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${repo}/actions/runs/${run_id}/jobs?per_page=100" \
    >"$tmp_dir/jobs.json"
  STAGE14_JSON="$tmp_dir/jobs.json" node - <<'NODE'
const fs = require("node:fs");
const payload = JSON.parse(fs.readFileSync(process.env.STAGE14_JSON, "utf8"));
const jobs = payload.jobs;
if (
  payload.total_count !== 8 ||
  !Array.isArray(jobs) ||
  jobs.length !== 8 ||
  jobs.some((job) => job.conclusion !== "success")
) process.exit(1);
NODE
done

print "stage14_two_ci_green_shas=true"
)
```

预期固定标记为 `true`。当前 GitHub 仓库为公开仓库，因此这里通过官方只读 API 查询，
不要求 `gh` 登录，也不要回传原始 JSON。若仓库以后改为私有，必须先重写本节的鉴权边界，
不得把 Token 直接写入命令或文档。

## 4. 第 1 步：首次私有 URL 引导

### 4.1 启动可回收的临时 Tailscale daemon

前置授权：用户接受 Tailscale Terms/Privacy，指定登录方式，并允许关闭 FlClash 的“系统
代理”和“虚拟网卡”。从这里到第 15.3 节不得恢复会产生 fake-IP 的模式；不修改 Supabase
Database Network Restrictions。

页面操作：在 FlClash 关闭上述两项；密码、Passkey、验证码和账户选择始终由用户本人在
Chrome 完成。

执行位置：终端 B；工作目录：项目根目录；变量来源：无；生产写入：Tailscale 本机
state；终端 B 保持打开。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/tailscale-login.sh start
./infra/local/tailscale-login.sh login
)
```

`start` 只保证受管 daemon/client 可用；`login` 必须在同一 socket 前台调用 `tailscale up`。
如果输出登录链接，在 Chrome 完成登录，等待命令结束后再执行下一块。

执行位置：终端 B；工作目录：项目根目录；变量来源：无；生产写入：无。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/tailscale-login.sh status --expect-running
print "stage14_tailscale_logged_in=true"
)
```

不得回传登录链接、账户、设备名、IP 或 `status` 原始输出。

### 4.2 验证 Supabase 不再经过 fake-IP

执行位置：终端 A；工作目录：项目根目录；变量来源：本机输入目标 project ref；生产
写入：无。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
read -r "project_ref?输入目标 Supabase Project Ref："
test -n "$project_ref"
print -rn -- "$project_ref" | /usr/bin/grep -Eq '^[a-z0-9]{10,40}$'
export STAGE14_DB_HOST="db.${project_ref}.supabase.co"
trap 'unset STAGE14_DB_HOST' EXIT
./.venv/bin/python - <<'PY'
import ipaddress
import os
import signal
import socket

signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
signal.alarm(10)
rows = socket.getaddrinfo(
    os.environ["STAGE14_DB_HOST"],
    5432,
    family=socket.AF_UNSPEC,
    type=socket.SOCK_STREAM,
)
signal.alarm(0)
addresses = {ipaddress.ip_address(row[4][0]) for row in rows}
if not addresses or any(not address.is_global for address in addresses):
    raise SystemExit("stage14_real_dns_verified=false")
PY
print "stage14_real_dns_verified=true"
)
```

只回传固定布尔标记，不回传 project ref、主机名或地址。

### 4.3 启用 Funnel 并本机记录固定 API origin

Tailscale 官方 Funnel 只用于把本机目标暴露为 Tailscale 管理的 HTTPS 入口；本项目只
允许代理 `127.0.0.1:8000`，不开放路由器端口。

执行前用户须明确授权创建本次公网 Funnel。helper 必须先用同一 socket 执行
`tailscale serve get-config <snapshot> --all`，把可恢复的完整配置保存为本机 `0600` 文件；
若已有任何路由，默认停止并要求用户确认是否替换。`funnel status --json` 只用于写后只读
断言，不是恢复格式。`restore` 必须用同一 socket 执行
`tailscale serve set-config <snapshot> --all`；禁止盲目 `funnel reset` 删除旧配置。Auth 已改时
还要按第 6.1 节快照恢复。

执行位置：终端 B；工作目录：项目根目录；变量来源：固定 shared socket；生产写入：
Tailscale Funnel 配置。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/stage14-funnel.sh enable
./infra/local/stage14-funnel.sh status
print "stage14_funnel_enabled=true"
)
```

`status` 只有在 JSON 中恰好存在一个 HTTPS 根路由、target 精确为
`http://127.0.0.1:8000` 且无其他 TCP/path 时才成功。把固定 `https://*.ts.net` origin 存入
密码管理器或本机验收记录；不要回传原始 JSON。命令语法以
[Tailscale Funnel 官方 CLI 文档](https://tailscale.com/docs/reference/tailscale-cli/funnel)为准。

第 4.3 节成功后、正式 `launchd` 在第 9.2 节接管前，如果第 4—9 节任一步中止，必须立即
执行下面的临时引导恢复块。正式接管后不得再运行本块，改用受管 runtime 的停止/恢复流程。

执行位置：终端 B；工作目录：项目根目录；变量来源：第 4.3 节 helper 保存的快照；生产
写入：恢复执行前 Funnel 配置并停止临时 Tailscale daemon。

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

### 4.4 准备并验证两个封存 release

`prepare-release.sh` 先在私有临时区校验源和构建；随后在精确最终路径 `releases/<SHA>` 创建
尚未封存目录，在该绝对路径创建 venv/安装锁定依赖，并用 `.venv/bin/python -m ...` 做探针。
全部成功后只原子创建 `SEALED` 标记；switcher 只接受 `SEALED`。失败只清理由本轮创建且无
`SEALED` 的目录，绝不覆盖已有封存 release。两个 release 必须分别构建，不能复制 `dist`。

执行位置：终端 A；工作目录：项目根目录；变量来源：两个 SHA、Funnel origin、Supabase
URL 和 publishable key；生产写入：无，只创建本机稳定 release。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
runtime_root="$HOME/Library/Application Support/Paper Grading"
read -r "candidate_sha?输入完整发布候选 SHA："
read -r "rollback_sha?输入完整回滚 SHA："
read -r "VITE_API_BASE_URL?输入 Funnel HTTPS origin："
read -r "VITE_SUPABASE_URL?输入 Supabase 项目 URL："
read -rs "VITE_SUPABASE_PUBLISHABLE_KEY?输入 Supabase publishable key："; print
export VITE_API_BASE_URL VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY
trap 'unset VITE_SUPABASE_PUBLISHABLE_KEY' EXIT
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
print -rn -- "$rollback_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test "$candidate_sha" != "$rollback_sha"

for sha in "$rollback_sha" "$candidate_sha"; do
  ./infra/local/prepare-release.sh "$sha"
  ./infra/local/validate-release.sh "$sha"
  release="$runtime_root/releases/$sha"
  test -f "$release/frontend/dist/server/index.js"
  test -f "$release/frontend/.openai/hosting.json"
done
manager="$runtime_root/shared/bin/switch-release.sh"
test -x "$manager"
"$manager" "$candidate_sha" --prepare-only
test "$(/usr/bin/stat -f '%Y' "$runtime_root/current")" = \
  "$runtime_root/releases/$candidate_sha"
print "stage14_two_local_releases_prepared=true"
)
```

预期两个 release 都保持只读/不可变。此处先验证构建输入和产物自洽；第 7.3 节还会把两个
封存 manifest 与最终 common env 做精确比对。Sites 专项测试必须各为 2 通过、失败 0。

### 4.5 用 Codex Sites 连接器保存两个版本并私有部署候选

执行位置：Codex Sites 连接器；不是终端，也不是 Supabase SQL Editor。操作者：Codex；
变量来源：`frontend/.openai/hosting.json` 中已有 `project_id`、第 3.3 节两个 SHA、第 4.4 节
对应构建目录。生产写入：Sites source repo、保存版本和 owner-only 部署。

严格按以下顺序执行：

1. 读取现有 Sites 项目，核对 `project_id` 一致、当前调用者是 owner、访问模式仍只允许
   本人；不得新建第二个 Sites 项目。
2. 为 Sites source repo 取得临时写入 credential；不得把 credential 写入 remote URL、
   Git config、日志、文件或聊天。
3. 先读取 source 分支当前 HEAD；只有 HEAD 仍等于刚观察值时，才用精确
   `--force-with-lease=<branch>:<observed-head>` 暂时指到回滚 SHA。lease 不匹配立即停止；
   credential 只放单条 Git HTTP header。archive 和 `commit_sha` 必须来自当前同一提交。
4. 对回滚 SHA 的 `frontend` release 目录调用当前 `sites:sites-hosting` skill 自带的 package
   helper；确认 archive 包含 `dist/server/index.js` 和 `dist/.openai/hosting.json`；立即保存为
   回滚 Sites 版本。
5. 再把同一 source 分支 fast-forward 到候选 SHA；对候选 SHA 的 `frontend` release 目录
   打包并立即保存，记录候选 Sites 版本号。
6. 再次读取项目，确认 allowed user 只有本人、allowed group 为 0、外部访客为 0。
7. 只调用 private deployment 接口部署候选 Sites 版本；禁止调用公开部署。
8. 轮询 deployment status，直到明确 `succeeded` 或 `failed`；超时或失败就停止。
9. 本机记录 `候选 SHA ↔ 候选 version_id/显示版本号`、`回滚 SHA ↔ 回滚 version_id/显示
   版本号`；`version_id` 仅本机供回滚调用，不回传 source credential、内部 URL 或 token。
10. 部署成功后，Codex 用连接器返回的精确正式 URL 调用 `open_in_codex` 做一次打开验证。

步骤 3 写入前须在本机记录 `observed-head`，每次成功写入后更新 `last-written-sha`。从首次
改写分支到两个版本均保存成功之间，任一步失败都先重新读取 remote HEAD；只有它仍等于
本流程的 `last-written-sha` 时，才允许用
`--force-with-lease=<branch>:<last-written-sha>` 恢复 `observed-head`。lease 不匹配或恢复
失败时立即停止并报告，禁止继续写分支或部署任何版本。

通过标准：两个不同保存版本存在；候选部署成功；Sites 仍 owner-only；获得固定前端
HTTPS origin。

### 4.6 Chrome 验证 owner-only Sites 和深层路径

执行位置：Chrome；不是终端，也不是 SQL Editor；变量来源：Sites 正式 origin；生产
写入：无。

使用 Sites owner 身份直接打开并刷新：

- `/login`
- `/auth/callback`
- `/assignments`
- `/grading-jobs`
- `/exports`

预期：Sites 外层身份验证存在，五个地址均不返回 404；未登录 owner 的独立无痕窗口不能
直接进入应用。此时后端尚未启动，页面显示 API 不可用可以接受，但不得出现公开访问。

## 5. 第 2 步：目标 Supabase 只读门禁和专用角色

### 5.1 在 SQL Editor 确认目标 revision、空闲状态和角色

执行位置：目标生产 Supabase 的 SQL Editor；不是本机终端；变量来源：无；生产写入：无。

```sql
select version_num
from public.alembic_version;

select 'grading_jobs' as workload,
       count(*) filter (where status = 'queued')::bigint as queued,
       count(*) filter (where status = 'running')::bigint as running
from public.grading_jobs
union all
select 'grading_job_items',
       count(*) filter (where status = 'queued')::bigint,
       count(*) filter (where status = 'running')::bigint
from public.grading_job_items
union all
select 'grading_attempts', 0::bigint,
       count(*) filter (where status = 'running')::bigint
from public.grading_attempts
union all
select 'exports',
       count(*) filter (where status = 'queued')::bigint,
       count(*) filter (where status = 'running')::bigint
from public.exports;

select rolname,
       rolcanlogin,
       rolinherit,
       rolbypassrls,
       rolsuper,
       rolcreaterole,
       rolcreatedb,
       rolreplication,
       rolpassword is not null as password_configured
from pg_catalog.pg_roles
where rolname in ('paper_grading_worker', 'paper_grading_export_worker')
order by rolname;
```

通过标准：

- revision 查询必须恰好 1 行，且值只能是 `20260726_0018` 或 `20260728_0019`；其他结果
  立即停止；
- 四项 workload 的 queued/running 全为 0；
- 两个角色各一行；`rolinherit/rolbypassrls/rolsuper/rolcreaterole/rolcreatedb/rolreplication` 均为
  `false`；
- revision 为 `0018` 时，`paper_grading_worker.rolcanlogin=false`、
  `paper_grading_export_worker.rolcanlogin=true` 是预期状态；不要在迁移前手改评分角色；
- revision 为 `0019` 时，两个角色 `rolcanlogin=true`；
- 需要实际登录的角色必须 `password_configured=true`。迁移 `0019` 不设置密码，不能把
  “角色存在”误判为“可以登录”。

### 5.2 只读确认 Storage 仍没有浏览器对象策略

执行位置：目标生产 Supabase 的 SQL Editor；不是本机终端；变量来源：无；生产写入：无。

```sql
select policyname, roles, cmd, qual, with_check
from pg_catalog.pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
order by policyname;

select count(*) = 1 and bool_and(c.relrowsecurity) as storage_objects_rls_enabled
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'storage'
  and c.relname = 'objects';
```

第一条预期 0 行，第二条预期 `true`。若存在策略或 RLS 关闭，停止；不要自行删除或修改。

### 5.3 仅在角色密码缺失或已遗失时设置密码

若第 5.1 节两个角色都已配置密码，且后续第 7.3 节连接探针通过，禁止无意义轮换。
revision 仍为 `0018` 时，允许在本节经单独授权先为 `paper_grading_worker` 设置密码；角色
继续保持 NOLOGIN，设置密码不会提前开放登录。实际评分角色连接探针仍必须等 `0019`
迁移后才执行。

只有出现 `password_configured=false` 或已无法取得现有密码时，先由用户明确授权一次角色
密码写入。不要在 SQL Editor 粘贴 `ALTER ROLE ... PASSWORD '...'`，避免明文进入查询历史。
当前 Mac 没有 `psql`，使用项目虚拟环境的交互脚本；密码只通过 `getpass` 输入。
Direct URL 必须手工规范为
`postgresql+asyncpg://postgres:<URL编码密码>@db.<project-ref>.supabase.co:5432/postgres?ssl=require`；
Dashboard 若给 `postgresql://`，只改 driver 前缀，密码先做 URL 百分号编码，仍用隐藏输入。

执行位置：终端 A；工作目录：候选 release 的 `backend`；变量来源：本机输入 project ref、白名单角色，
脚本内隐藏输入 Direct admin URL 和新密码；生产写入：修改一个数据库角色密码，必须已有
用户明确授权。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current/backend"
read -r "STAGE14_PROJECT_REF?输入目标 Supabase Project Ref："
read -r "STAGE14_PASSWORD_ROLE?输入要设置的角色名："
read -r "STAGE14_PASSWORD_AUTH?输入 I_AUTHORIZE_ONE_ROLE_PASSWORD_CHANGE："
test "$STAGE14_PASSWORD_AUTH" = "I_AUTHORIZE_ONE_ROLE_PASSWORD_CHANGE" # pragma: allowlist secret
print -rn -- "$STAGE14_PROJECT_REF" | /usr/bin/grep -Eq '^[a-z0-9]{10,40}$'
case "$STAGE14_PASSWORD_ROLE" in
  paper_grading_worker|paper_grading_export_worker) ;;
  *) exit 1 ;;
esac
export STAGE14_PROJECT_REF STAGE14_PASSWORD_ROLE
trap 'unset STAGE14_PROJECT_REF STAGE14_PASSWORD_ROLE STAGE14_PASSWORD_AUTH' EXIT

PYTHONPATH=. ../.venv/bin/python - <<'PY'
import asyncio
import getpass
import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import MigrationSettings

role = os.environ["STAGE14_PASSWORD_ROLE"]
project_ref = os.environ["STAGE14_PROJECT_REF"]
admin_url = getpass.getpass("Supabase Direct admin URL: ")
os.environ["MIGRATION_DATABASE_URL"] = admin_url
settings = MigrationSettings()
url = make_url(settings.migration_database_url)
if (
    url.host != f"db.{project_ref}.supabase.co"
    or url.port not in (None, 5432)
    or url.username != "postgres"
    or url.database != "postgres"
    or set(url.query) != {"ssl"}
    or url.query.get("ssl") not in {"require", "verify-ca", "verify-full"}
):
    raise SystemExit("stage14_role_password_target_mismatch")

password = getpass.getpass("New dedicated role password: ")
confirmation = getpass.getpass("Repeat password: ")
if password != confirmation or len(password) < 24:
    raise SystemExit("stage14_role_password_rejected")
if not (
    any(c.islower() for c in password)
    and any(c.isupper() for c in password)
    and any(c.isdigit() for c in password)
    and any(not c.isalnum() for c in password)
):
    raise SystemExit("stage14_role_password_rejected")

async def main() -> None:
    engine = create_async_engine(
        settings.migration_database_url,
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        try:
            async with engine.begin() as connection:
                quoted = await connection.scalar(
                    text("select pg_catalog.quote_literal(:password)"),
                    {"password": password},
                )
                if not isinstance(quoted, str):
                    raise RuntimeError
                await connection.exec_driver_sql(
                    f'alter role "{role}" password {quoted}'
                )
        except (SQLAlchemyError, RuntimeError):
            raise SystemExit("stage14_role_password_change_failed") from None
    finally:
        await engine.dispose()

asyncio.run(main())
print("stage14_one_role_password_changed=true")
PY
)
```

对另一个失败角色单独重新取得授权并执行。两个角色必须使用不同强密码，不与 API/admin
密码复用。执行后立即把密码存入密码管理器，并在第 7 节写入对应 `0600` 环境文件；不得
把密码或连接地址回传。

## 6. 第 3 步：Supabase Auth 和暂停的 UptimeRobot

### 6.1 配置 Auth URL

执行位置：目标生产 Supabase Dashboard → Authentication → URL Configuration；不是终端
或 SQL Editor；变量来源：第 4.5 节 Sites 正式 origin；生产写入：Auth 配置，保存前必须
由用户明确确认。

1. 修改前先在本机验收记录保存旧 Site URL 和完整 Redirect URLs（不回传）；再把 `Site URL`
   精确填写为 Sites 正式 origin，不带尾斜杠和额外路径。
2. 保存前读取完整 Redirect URLs；最终集合必须精确等于当前
   `<Sites origin>/auth/callback`。旧 localhost、旧 Sites origin 或 wildcard 存在时先停止，
   单独取得删除授权；业务若确需额外项也必须逐条授权并记录理由。
3. 不使用 `*`、`**` 或其他 wildcard；保存后重新读取 Site URL 和最终集合验证精确值。
4. 确认公开注册继续关闭。
5. 不修改 JWT secret、Token 生命周期、邮件服务或其他 Auth 开关。
6. 保存后本机记录 `site_url_exact=true`、`callback_exact=true`、`public_signup_disabled=true`。

正式业务流通过前若任一步骤中止，必须先取得用户授权，再按本机快照恢复旧 Site URL 和
Redirect 集合并读回验证；不得把 Auth 永久留在半部署前端。

Supabase 官方建议生产使用精确 redirect；规则见
[Redirect URLs 文档](https://supabase.com/docs/guides/auth/redirect-urls)和
[Auth 通用配置](https://supabase.com/docs/guides/auth/general-configuration)。

### 6.2 创建但先暂停两个 UptimeRobot 监控

执行位置：UptimeRobot 页面；不是终端或 SQL Editor；变量来源：Funnel origin；生产写入：
创建监控，保存前必须由用户确认。

| 监控 | 配置 | 初始状态 |
|---|---|---|
| HTTP(S) | `<Funnel origin>/health/ready`，只接受 HTTPS 成功状态 | 暂停 |
| Heartbeat/Cron | 新建专用 heartbeat；本机 watchdog 每 60 秒尝试发送 | 暂停 |

免费计划当前允许的常规检查间隔为 5 分钟，并包含 heartbeat/cron。Heartbeat 页面选择账户
当前允许的最短期望间隔并设置合理 grace；不要把本机“每 60 秒发送”误写成 UI 一定支持
“60 秒告警”。告警等待上限以页面实际 interval + grace 为准。参考
[UptimeRobot 快速配置](https://help.uptimerobot.com/en/articles/11358364-how-to-create-your-first-monitor-on-uptimerobot-quick-setup-guide)和
[Free 计划说明](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan)。

Heartbeat URL 是写入凭据，只放进第 7 节本机 `0600` 环境文件，不回传、不截图。

## 7. 第 4 步：建立生产环境并执行只读配置探针

### 7.1 一次性写入两个环境文件

前置条件：已取得 Funnel/Sites/Supabase URL、三个 Session Pooler URL、Supabase keys、
Storage bucket、与目标数据库现有供应商密文匹配的 `PROVIDER_MASTER_KEY` 和 Heartbeat URL。
已有加密供应商配置时禁止重新生成 master key。

三个数据库 URL 都必须采用：
`postgresql+asyncpg://<URL编码后的用户和密码>@<session-pooler>:5432/postgres?ssl=require`。
API 用户为 `postgres.<project-ref>`；评分和导出分别为
`paper_grading_worker.<project-ref>`、`paper_grading_export_worker.<project-ref>`。

脚本生成的 `production.env` 键必须精确包括：`APP_ENV=production`、`DATABASE_URL`、
`EXPORT_DATABASE_URL`、`REDIS_URL=redis://127.0.0.1:6379/0`、`SUPABASE_URL`、
`SUPABASE_PUBLISHABLE_KEY`、`SUPABASE_SECRET_KEY`、`SUPABASE_STORAGE_BUCKET`、
`SUPABASE_STORAGE_SIGNED_URL_TTL_SECONDS=60`、`SUPABASE_STORAGE_TIMEOUT_SECONDS=60.0`、
`PROVIDER_MASTER_KEY`、`AUTH_INVITE_REDIRECT_URL`、`FRONTEND_ORIGIN`、
`VITE_API_BASE_URL`、`VITE_SUPABASE_URL`、`VITE_SUPABASE_PUBLISHABLE_KEY`、
`UPTIMEROBOT_HEARTBEAT_URL`。`grading-worker.env` 只含评分角色 `DATABASE_URL`；runner 先加载
common，再用它覆盖 API URL。数据库 URL、secret key、master key、heartbeat 和密码均隐藏
输入；所有键拒绝空值、换行、占位符和未知额外键。

执行位置：终端 A；工作目录：候选 `current`；变量来源：由受审脚本逐项交互输入；生产写入：
目录级原子创建两个本机密钥文件。脚本必须逐层先拒绝 symlink/错误 owner 再建目录，不得
先用 `mkdir -p` 穿过未知 symlink。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
"$runtime_root/current/infra/local/update-production-env.sh" --create
print "stage14_environment_files_created=true"
)
```

脚本内部必须固定 `APP_ENV=production`、Redis 回环 URL、Storage TTL/timeout，并生成本文列出的
其余变量；密码和 Key 用隐藏输入。若输入有误，停止并重新取得用户授权后执行同一脚本的
`--replace`：先完整验证 staging 两文件，再原子换目录；失败必须保留上一套可用文件，不得
手工编辑、删除半套文件或覆盖单个文件。

### 7.2 文件权限、归属和 Git 边界

执行位置：终端 A；工作目录：项目根目录；变量来源：固定 shared 路径；生产写入：无。

```zsh
(
set -euo pipefail
cd "/Users/a1-6/Documents/Paper Grading"
env_dir="$HOME/Library/Application Support/Paper Grading/shared/env"
runtime_root="$HOME/Library/Application Support/Paper Grading"
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

test ! -e .env.stage14-production
test ! -L .env.stage14-production
test ! -e .env.stage14-grading-worker
test ! -L .env.stage14-grading-worker
git check-ignore -q .env.stage14-production
git check-ignore -q .env.stage14-grading-worker
print "stage14_environment_file_permissions=true"
)
```

生产密钥已移出仓库；项目根目录不得再创建指向 shared env 的符号链接。

### 7.3 始终核对同一项目；评分角色在 `0019` 后连接

本节在 `0018` 和 `0019` 都必须执行：始终校验两个 manifest、三个 URL 合同，并实际连接
API/export。API 连接读取唯一 revision；只有 `0019` 才连接 grading，`0018` 输出 deferred，
迁移后必须重跑并连接成功。未通过本节不得执行第 7.4 节或迁移。

执行位置：终端 A；工作目录：项目根目录；变量来源：两个 shared env 文件和两个已批准
SHA；生产写入：无，只校验封存 manifest、建立短连接并执行 `select current_user`。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current"
env_dir="$runtime_root/shared/env"
read -r "candidate_sha?输入完整发布候选 SHA："
read -r "rollback_sha?输入完整回滚 SHA："
for sha in "$candidate_sha" "$rollback_sha"; do
  print -rn -- "$sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
  "$runtime_root/releases/$sha/infra/local/validate-release.sh" \
    "$sha" --env-dir "$env_dir"
done
set -a
source "$env_dir/production.env"
set +a
export STAGE14_GRADING_DATABASE_URL
STAGE14_GRADING_DATABASE_URL=$(
  set -a
  source "$env_dir/grading-worker.env"
  set +a
  print -r -- "$DATABASE_URL"
)
trap 'unset STAGE14_GRADING_DATABASE_URL' EXIT

PYTHONPATH=backend ./.venv/bin/python - <<'PY'
import asyncio
import os
import re
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import ExportWorkerSettings, Settings, WorkerSettings

api = Settings.load()
export = ExportWorkerSettings.load()
worker_environment = dict(os.environ)
worker_environment["DATABASE_URL"] = os.environ["STAGE14_GRADING_DATABASE_URL"]
original_database_url = os.environ["DATABASE_URL"]
os.environ["DATABASE_URL"] = worker_environment["DATABASE_URL"]
try:
    worker = WorkerSettings.load()
finally:
    os.environ["DATABASE_URL"] = original_database_url

if api.app_env.value != "production":
    raise SystemExit("stage14_app_env_invalid")
if api.allow_official_provider_fake_ip or worker.allow_official_provider_fake_ip:
    raise SystemExit("stage14_fake_ip_exception_forbidden")
if os.environ["SUPABASE_URL"] != os.environ["VITE_SUPABASE_URL"]:
    raise SystemExit("stage14_supabase_url_mismatch")
if os.environ["SUPABASE_PUBLISHABLE_KEY"] != os.environ["VITE_SUPABASE_PUBLISHABLE_KEY"]:
    raise SystemExit("stage14_publishable_key_mismatch")
if api.auth_invite_redirect_url != f"{api.frontend_origin}/auth/callback":
    raise SystemExit("stage14_auth_callback_mismatch")
api_origin = urlparse(os.environ["VITE_API_BASE_URL"])
if (
    api_origin.scheme != "https"
    or api_origin.port is not None
    or api_origin.username is not None
    or api_origin.password is not None
    or not (api_origin.hostname or "").endswith(".ts.net")
    or api_origin.path not in ("", "/")
    or api_origin.query
    or api_origin.fragment
    or os.environ["VITE_API_BASE_URL"].endswith("/")
):
    raise SystemExit("stage14_api_origin_invalid")

supabase_parsed = urlparse(api.supabase_url)
supabase_host = supabase_parsed.hostname or ""
if (
    supabase_parsed.scheme != "https"
    or supabase_parsed.port is not None
    or not supabase_host.endswith(".supabase.co")
):
    raise SystemExit("stage14_supabase_project_url_invalid")
project_ref = supabase_host.removesuffix(".supabase.co")
if (
    re.fullmatch(r"[a-z0-9]{10,40}", project_ref) is None
    or api.supabase_url != f"https://{project_ref}.supabase.co"
):
    raise SystemExit("stage14_supabase_project_ref_invalid")

urls = {
    "api": (api.database_url, f"postgres.{project_ref}"),
    "grading": (worker.database_url, f"paper_grading_worker.{project_ref}"),
    "export": (export.database_url, f"paper_grading_export_worker.{project_ref}"),
}
for _, (value, expected_username) in urls.items():
    parsed = make_url(value)
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

async def current_user(url: str) -> str:
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 10})
    try:
        async with asyncio.timeout(20):
            async with engine.connect() as connection:
                value = await connection.scalar(text("select current_user"))
                if not isinstance(value, str):
                    raise SystemExit("stage14_current_user_invalid")
                return value
    finally:
        await engine.dispose()

async def current_revision(url: str) -> str:
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 10})
    try:
        async with asyncio.timeout(20):
            async with engine.connect() as connection:
                values = (
                    await connection.execute(text("select version_num from public.alembic_version"))
                ).scalars().all()
                if len(values) != 1 or values[0] not in {
                    "20260726_0018",
                    "20260728_0019",
                }:
                    raise SystemExit("stage14_revision_invalid")
                return values[0]
    finally:
        await engine.dispose()

async def main() -> None:
    if await current_user(api.database_url) != "postgres":
        raise SystemExit("stage14_api_role_failed")
    if await current_user(export.database_url) != "paper_grading_export_worker":
        raise SystemExit("stage14_export_role_failed")
    revision = await current_revision(api.database_url)
    if revision == "20260728_0019":
        if await current_user(worker.database_url) != "paper_grading_worker":
            raise SystemExit("stage14_grading_role_failed")
        print("stage14_grading_role_verified=true")
    else:
        print("stage14_grading_role_deferred=true")

asyncio.run(main())
print("stage14_settings_and_roles_verified=true")
PY
)
```

这里必须使用 SQLAlchemy async engine；不要把项目要求的 `postgresql+asyncpg://` URL 直接
传给 `asyncpg.connect()`。

### 7.4 验证供应商密文和零费用网络策略

执行位置：终端 A；工作目录：候选 `current`；变量来源：common env；生产写入和模型费用：
无。它解密现有 Key，并让每个启用供应商的 base URL 经过生产同款 DNS/SSRF/fake-IP 策略；
成功只输出固定标记，不输出供应商、模型、地址、密文、Key 或数量。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
cd "$current"
env_dir="$runtime_root/shared/env"
set -a
source "$env_dir/production.env"
set +a

PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
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
            rows = (
                await connection.execute(
                    text(
                        "select id, provider_type, base_url, encrypted_api_key, api_key_nonce "
                        "from public.provider_configs "
                        "where status = 'enabled' "
                        "and encrypted_api_key is not null "
                        "and api_key_nonce is not null"
                    )
                )
            ).mappings().all()
        if not rows:
            raise SystemExit("stage14_enabled_provider_missing")
        for row in rows:
            cipher.decrypt(
                EncryptedApiKey(
                    ciphertext=row["encrypted_api_key"],
                    nonce=row["api_key_nonce"],
                ),
                provider_id=row["id"],
            )
            await ProviderBaseUrlPolicy().validate(
                ProviderType(row["provider_type"]),
                row["base_url"],
            )
    finally:
        await engine.dispose()

asyncio.run(main())
print("stage14_provider_key_and_network_policy_verified=true")
PY
)
```

### 7.5 只读验证公开注册关闭和 Storage bucket 契约

执行位置：终端 A；工作目录：候选 `current`；变量来源：common env；生产写入：无，只调用
Supabase Auth settings 和 bucket metadata API。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
cd "$current"
env_dir="$runtime_root/shared/env"
set -a
source "$env_dir/production.env"
set +a

PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
import asyncio

import httpx

from app.auth.supabase import SupabaseAuthGateway
from app.config import Settings
from app.export.xlsx import XLSX_MEDIA_TYPE
from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE
from app.storage.supabase import SupabaseObjectStorage

settings = Settings.load()

async def main() -> None:
    async with (
        httpx.AsyncClient(timeout=10, trust_env=False) as auth_client,
        httpx.AsyncClient(timeout=60, trust_env=False) as storage_client,
    ):
        auth = SupabaseAuthGateway(
            base_url=settings.supabase_url,
            publishable_key=settings.supabase_publishable_key,
            secret_key=settings.supabase_secret_key.get_secret_value(),
            invite_redirect_url=settings.auth_invite_redirect_url,
            client=auth_client,
        )
        await auth.require_public_signup_disabled()
        storage = SupabaseObjectStorage.from_settings(settings, storage_client)
        await storage.require_private_bucket(
            expected_file_size_limit_bytes=50 * 1024 * 1024,
            expected_allowed_mime_types={
                PDF_MEDIA_TYPE,
                DOCX_MEDIA_TYPE,
                "application/json",
                XLSX_MEDIA_TYPE,
            },
        )

asyncio.run(main())
print("stage14_auth_and_storage_read_only_verified=true")
PY
)
```

失败时停止；不得自动打开公开注册、创建 bucket、改大小/MIME 或创建 Storage Policy。若
目标桶仍是阶段 7 的 20MiB 且只有 PDF/DOCX/JSON，必须在 Dashboard 另行取得用户授权后把
bucket 上限改为 50MiB 并增加 XLSX MIME，再重跑本只读探针；否则应用允许的合法 XLSX
导出可能被 Storage 拒绝。论文上传仍由应用层保持 20MiB 上限，不能因 bucket 放宽而放宽。

需要统一契约时的执行位置：Supabase Dashboard → Storage → 目标 bucket → Edit bucket；
不是 SQL Editor。修改前记录私有状态、20MiB 和现有三项，用户明确授权后只把文件上限改为
50MiB，并增加
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`；bucket 必须继续私有，
其余值不变。保存后立即重跑第 5.2 和 7.5 节。不要创建测试对象。

## 8. 第 5 步：无任务门禁和只前向迁移

### 8.1 只读验证已有 Redis/broker 没有遗留任务

执行位置：终端 A；工作目录：候选 release；变量来源：common env 中仅导出 `REDIS_URL`；
生产写入：无。根据已完成的 Redis/Worker 验收，本机 Redis 应已运行；若没有 `PONG`，本次
流程立即停止并另行恢复该既有组件，不能在迁移前临时启动一个未知 broker。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current"
redis_plist="$HOME/Library/LaunchAgents/homebrew.mxcl.redis.plist"
test -f "$redis_plist"
test ! -L "$redis_plist"
/bin/launchctl print "gui/$UID/homebrew.mxcl.redis" >/dev/null
test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
test "$(/opt/homebrew/bin/redis-cli --raw CONFIG GET protected-mode | /usr/bin/tail -n 1)" = "yes"
test "$(/opt/homebrew/bin/redis-cli --raw CONFIG GET maxmemory-policy | /usr/bin/tail -n 1)" = "noeviction"

listeners=$(
  lsof -nP -iTCP:6379 -sTCP:LISTEN -Fn |
    /usr/bin/grep '^n' |
    /usr/bin/cut -c2-
)
test -n "$listeners"
while IFS= read -r listener; do
  case "$listener" in
    127.0.0.1:6379|'[::1]:6379') ;;
    *) print -u2 "stage14_redis_loopback_only=false"; exit 1 ;;
  esac
done <<<"$listeners"

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
print("stage14_redis_and_broker_idle=true")
PY
)
```

若计数非 0，停止并恢复已有任务；禁止删除 Redis 键。

### 8.2 在 SQL Editor 再次确认 queued/running 全为 0

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。

```sql
select
  (select count(*) = 0 from public.grading_jobs
   where status in ('queued', 'running')) as grading_jobs_idle,
  (select count(*) = 0 from public.grading_job_items
   where status in ('queued', 'running')) as grading_items_idle,
  (select count(*) = 0 from public.grading_attempts
   where status = 'running') as grading_attempts_idle,
  (select count(*) = 0 from public.exports
   where status in ('queued', 'running')) as exports_idle;
```

四列必须全部为 `true`。不满足时停止，不迁移。

### 8.3 冻结迁移期间的新写入

在所有仍运行的旧手动 API、评分 Worker、维护 Worker 和导出 Worker 终端中分别按
`Control-C`，等待进程退出。此时尚未安装正式 LaunchAgent；若发现已有相关 LaunchAgent，
也必须先停止并查清来源。

执行位置：终端 A；工作目录：候选 release；变量来源：common env 的 Redis URL；生产写入：
停止旧本机进程，不修改数据库或队列。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current"
source "$runtime_root/shared/env/production.env"
export REDIS_URL

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "stage14_api_write_freeze=false"
  exit 1
fi
for label in api grading export; do
  if launchctl print "gui/$UID/com.paper-grading.$label" >/dev/null 2>&1; then
    print -u2 "stage14_unexpected_launch_agent_running=true"
    exit 1
  fi
done

PYTHONPATH="$runtime_root/current/backend" "$runtime_root/current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

app = Celery("stage14_migration_freeze", broker=os.environ["REDIS_URL"])
if app.control.inspect(timeout=3).ping():
    raise SystemExit("stage14_worker_write_freeze_failed")
print("stage14_local_writes_frozen=true")
PY
)
```

然后立刻重新执行第 8.1 节 broker 计数和第 8.2 节 SQL idle 查询。两者仍为 0 后才迁移；
迁移完成前不得启动 API 或 Worker。

### 8.4 执行或跳过 `0019`

先看第 5.1 节 revision：

- 已是 `20260728_0019`：不要重跑，直接进入第 8.5 节；
- 是 `20260726_0018`：执行本节一次；
- 其他值：停止。

执行前由用户明确确认：“目标 project ref 已核对、业务任务为 0、授权生产数据库只前向
升级到 `20260728_0019`”。

隐藏输入的 Direct URL 格式同第 5.3 节：必须是 `postgresql+asyncpg://postgres:...`、目标
database 为 `postgres` 且只有 `ssl=require`（或更严格验证模式）query；不要原样使用
Dashboard 的 `postgresql://` 前缀。

执行位置：终端 A；工作目录：候选 release 的 `backend`；变量来源：final common env 派生
project ref、隐藏输入 Direct URL 和固定确认语；生产写入：Alembic 单次前向迁移。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
cd "$runtime_root/current/backend"
source "$runtime_root/shared/env/production.env"
read -rs "MIGRATION_DATABASE_URL?输入目标 Supabase Direct URL："
print
read -r "STAGE14_MIGRATION_AUTH?输入 I_AUTHORIZE_FORWARD_MIGRATION_TO_0019："
test "$STAGE14_MIGRATION_AUTH" = "I_AUTHORIZE_FORWARD_MIGRATION_TO_0019"
export MIGRATION_DATABASE_URL SUPABASE_URL
trap 'unset STAGE14_PROJECT_REF MIGRATION_DATABASE_URL STAGE14_MIGRATION_AUTH' EXIT

PYTHONPATH=. ../.venv/bin/python - <<'PY'
import asyncio
import os
import re
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from app.config import MigrationSettings

settings = MigrationSettings()
url = make_url(settings.migration_database_url)
supabase = urlparse(os.environ["SUPABASE_URL"])
if supabase.scheme != "https" or not (supabase.hostname or "").endswith(".supabase.co"):
    raise SystemExit("stage14_migration_supabase_url_invalid")
project_ref = (supabase.hostname or "").removesuffix(".supabase.co")
if (
    re.fullmatch(r"[a-z0-9]{10,40}", project_ref) is None
    or os.environ["SUPABASE_URL"] != f"https://{project_ref}.supabase.co"
):
    raise SystemExit("stage14_migration_supabase_url_invalid")
expected = f"db.{project_ref}.supabase.co"
if (
    url.host != expected
    or url.port not in (None, 5432)
    or url.username != "postgres"
    or url.database != "postgres"
    or set(url.query) != {"ssl"}
    or url.query.get("ssl") not in {"require", "verify-ca", "verify-full"}
):
    raise SystemExit("stage14_migration_target_mismatch")
async def main() -> None:
    engine = create_async_engine(
        settings.migration_database_url,
        poolclass=NullPool,
        hide_parameters=True,
    )
    config = Config("alembic.ini")
    try:
        async with engine.connect() as connection:
            before = (
                await connection.execute(text("select version_num from public.alembic_version"))
            ).scalars().all()
            await connection.commit()
            if before != ["20260726_0018"]:
                raise SystemExit("stage14_migration_source_revision_invalid")

            def upgrade(sync_connection):
                config.attributes["connection"] = sync_connection
                try:
                    command.upgrade(config, "20260728_0019")
                finally:
                    config.attributes.pop("connection", None)

            await connection.run_sync(upgrade)
            after = (
                await connection.execute(text("select version_num from public.alembic_version"))
            ).scalars().all()
            await connection.commit()
            if after != ["20260728_0019"]:
                raise SystemExit("stage14_migration_result_revision_invalid")
    finally:
        await engine.dispose()

asyncio.run(main())
print("stage14_forward_migration_executed=true")
PY
)
```

禁止执行 `alembic current` 建立第二次 Direct 连接；迁移结果统一由 SQL Editor 验证。

### 8.5 在 SQL Editor 验证迁移头

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。

```sql
select version_num
from public.alembic_version;

select
  has_schema_privilege(
    'paper_grading_worker',
    'paper_grading_private',
    'USAGE'
  ) as grading_private_schema_usage,
  has_function_privilege(
    'paper_grading_worker',
    'paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)',
    'EXECUTE'
  ) as grading_reserve_storage_execute,
  has_function_privilege(
    'paper_grading_worker',
    'paper_grading_private.finalize_storage_growth(uuid,text)',
    'EXECUTE'
  ) as grading_finalize_storage_execute,
  not has_function_privilege(
    'anon',
    'paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)',
    'EXECUTE'
  ) and not has_function_privilege(
    'authenticated',
    'paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)',
    'EXECUTE'
  ) and not has_function_privilege(
    'service_role',
    'paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)',
    'EXECUTE'
  ) as reserve_not_executable_by_browser_roles,
  not has_function_privilege(
    'anon',
    'paper_grading_private.finalize_storage_growth(uuid,text)',
    'EXECUTE'
  ) and not has_function_privilege(
    'authenticated',
    'paper_grading_private.finalize_storage_growth(uuid,text)',
    'EXECUTE'
  ) and not has_function_privilege(
    'service_role',
    'paper_grading_private.finalize_storage_growth(uuid,text)',
    'EXECUTE'
  ) as finalize_not_executable_by_browser_roles,
  pg_has_role('postgres', 'paper_grading_worker', 'MEMBER')
    as postgres_is_grading_member,
  pg_has_role('postgres', 'paper_grading_export_worker', 'MEMBER')
    as postgres_is_export_member,
  not exists (
    select 1
    from pg_catalog.pg_auth_members m
    join pg_catalog.pg_roles member_role on member_role.oid = m.member
    where member_role.rolname in (
      'paper_grading_worker',
      'paper_grading_export_worker'
    )
  ) as workers_have_no_role_memberships;
```

第一条预期唯一一行为 `20260728_0019`，第二条 8 列必须全部为 `true`。同时回看第 5.1 节，
两个 Worker 的 `rolreplication` 必须为 `false`。失败时保持 API/Worker 停止，不 downgrade、
不重复执行，先检查迁移错误。首次从 `0018` 升级时，确认 revision 后回到第 5.3 节处理
可能缺失的评分角色密码，再依次执行第 7.3、7.4、7.5 节；全部通过后才进入第 9 节。

## 9. 第 6 步：`launchd` 接管和自动恢复

### 9.1 只读确认候选 `current`

执行位置：终端 A；工作目录：稳定运行根；变量来源：候选 SHA；生产写入：无。第 4.4 节
已经用稳定 manager 做过首次 `--prepare-only`，这里不得再次从开发仓库切换。

```zsh
(
set -euo pipefail
read -r "candidate_sha?输入完整发布候选 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
runtime_root="$HOME/Library/Application Support/Paper Grading"
expected="$runtime_root/releases/$candidate_sha"
test -d "$expected"
test "$(/usr/bin/stat -f '%Y' "$runtime_root/current")" = "$expected"
"$expected/infra/local/validate-release.sh" "$candidate_sha" \
  --env-dir "$runtime_root/shared/env"
print "stage14_candidate_current_selected=true"
)
```

失败时回到第 4.4 节查 release/manager；不要临时用开发仓库脚本补切。

### 9.2 显式停止临时 Tailscale daemon

执行位置：终端 B；工作目录：项目根目录；变量来源：无；生产写入：停止临时 daemon，
保留 state 和 Funnel 配置。

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

只有 PID 已退出、旧 socket 已确认无进程占用时才能继续。

### 9.3 安装 LaunchAgent 并验证全部运行态

执行位置：终端 A；工作目录：稳定 `current`；变量来源：固定运行根；生产写入：安装并启动
6 个用户级 LaunchAgent。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
test -L "$current"
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

若上块返回失败，不得继续第 9.4 节。installer 命令自身失败时应已自动回滚；无论是
installer 失败还是后续 verify 超时，仍须执行下块进行幂等清理，再取得用户授权，按第
6.1 节保存前快照恢复 Auth。Funnel 必须用同一 `shared` state 临时启动受管 helper 后恢复；
不得复用第 4.3 节已经退出的旧进程。

执行位置：终端 A；工作目录：稳定 `current`；变量来源：installer 事务记录和第 4.3 节
Funnel 快照；生产写入：撤销本轮半安装服务并恢复执行前 Funnel 配置。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
installer="$current/infra/local/install-launch-agents.sh"
test -x "$installer"
"$installer" --rollback-first-install

for label in api grading export keep-awake tailscale watchdog; do
  if /bin/launchctl print "gui/$UID/com.paper-grading.$label" >/dev/null 2>&1; then
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

若本块失败，保持 Sites owner-only、两个 UptimeRobot 监控暂停、业务入口关闭，停止验收并
人工排查；不得继续真实业务。Auth 只有在用户明确授权恢复后才能按快照写回。

### 9.4 强制重启 API、评分/维护、导出和 Tailscale

执行位置：终端 A；工作目录：无要求；变量来源：当前 UID；生产写入：可逆本机进程重启。

```zsh
(
set -euo pipefail
for label in api grading export tailscale; do
  launchctl kickstart -k "gui/$UID/com.paper-grading.$label"
done

runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
for _ in {1..60}; do
  if "$current/infra/local/verify-runtime.sh" >/dev/null 2>&1; then
    print "stage14_launchd_forced_restart=true"
    exit 0
  fi
  sleep 2
done
print -u2 "stage14_launchd_forced_restart=false"
exit 1
)
```

### 9.5 注销并重新登录 macOS 后验证

先保存其他工作，再由用户注销并重新登录一次 macOS。不要用重启单个终端代替登录后
恢复。重新登录后打开新的终端 A。

执行位置：重新登录后的新终端 A；工作目录：稳定运行根；变量来源：无；生产写入：无。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
"$current/infra/local/verify-runtime.sh"
print "stage14_login_recovery_verified=true"
)
```

通过标准：6 个 label 都在线；API 和 Redis 只监听回环；Funnel 正常；`grading@`、
`maintenance@`、`exports@` 都响应且只消费各自队列。

## 10. 第 7 步：部署后无业务写入冒烟

### 10.1 API HTTPS、安全响应头和 CORS

执行位置：终端 A；工作目录：稳定运行根；变量来源：common env；生产写入：无。

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
http_status=$(
  curl --silent --show-error --connect-timeout 5 --max-time 10 \
    --max-redirs 0 --output /dev/null --write-out '%{http_code}' \
    "${api_origin/https:/http:}/health/live" 2>/dev/null || true
)
case "$http_status" in
  000|301|302|307|308|400|403|404) ;;
  *) print -u2 "stage14_plain_http_served_application=true"; exit 1 ;;
esac

curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --output /dev/null \
  --dump-header "$tmp_dir/api.headers" \
  "${api_origin%/}/health/live"
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
  "${api_origin%/}/health/ready" >/dev/null

tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'x-content-type-options: nosniff'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'x-frame-options: DENY'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi 'referrer-policy: no-referrer'
tr -d '\r' <"$tmp_dir/api.headers" | /usr/bin/grep -Fxi \
  'permissions-policy: camera=(), microphone=(), geolocation=()'

curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --output /dev/null \
  --dump-header "$tmp_dir/allowed-cors.headers" \
  -H "Origin: $frontend_origin" \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "${api_origin%/}/auth/me"
tr -d '\r' <"$tmp_dir/allowed-cors.headers" | /usr/bin/grep -Fxi \
  "access-control-allow-origin: $frontend_origin"

blocked_status=$(curl --silent --show-error --connect-timeout 5 --max-time 20 --output /dev/null \
  --write-out '%{http_code}' \
  --dump-header "$tmp_dir/blocked-cors.headers" \
  -H 'Origin: https://attacker.invalid' \
  -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "${api_origin%/}/auth/me")
test "$blocked_status" = "400"
if tr -d '\r' <"$tmp_dir/blocked-cors.headers" |
  /usr/bin/grep -qi '^access-control-allow-origin:'; then
  exit 1
fi
print "stage14_api_read_only_smoke=true"
)
```

### 10.2 owner-only Sites 页面

执行位置：Chrome；不是终端或 SQL Editor；变量来源：Sites 正式 origin；生产写入：无。

以 owner 身份重新打开并刷新第 4.6 节列出的 5 个路径。此时预期：

- `/login` 可正常显示；
- 未登录应用时受 Sites 外层身份保护；
- API live/ready 已恢复，页面不再显示后端不可用；
- 五个路径均不返回 404；
- 浏览器 Console 错误、警告为 0。

## 11. 第 8 步：只执行一次的单篇完整付费业务流

### 11.1 写入和费用授权

执行前必须一次性确认：

- 用户授权邀请 1 名全新教师并执行 1 条完整生产业务流；
- 正常流程至少包括 1 次 Rubric 生成和 1 次单篇评分请求；契约纠正或安全重试可能造成
  更多供应商请求，不能写成“只调用模型一次”；
- 应用的 `monthly_budget` 不是供应商侧硬上限；供应商侧独立账户/子账户的可用余额或硬消费
  上限必须只读验证不超过人民币 10.00 元。无法验证就停止；若要放宽 10 元，必须在本节
  明确写出新上限并取得单独授权，不能用一般“同意模型费用”代替；
- 只使用无敏感内容的题目、Rubric 和单篇 DOCX/PDF；
- 验收数据会保留：教师账户、作业、Rubric 版本、论文及提取对象、批次、attempt/原始
  响应、教师确认、export 快照和 XLSX；自动清理关闭，验收后不 DELETE；
- 作业标题使用本轮唯一 `Stage14-<日期时间>-<短标识>` 前缀，并在本机记录相关 ID，
  不回传 ID；
- 每个唯一标题/marker 最多执行一次 `--start`，全阶段默认只执行一次。只有 runner 用远端
  只读证据确认 `aborted_prewrite` 且用户重新授权，才可用全新标题/marker 再开始；旧 marker
  永不删除。

### 11.2 邀请并激活一名新教师

执行位置：Chrome 正式 Sites + 教师邮箱；不是终端或 SQL Editor；变量来源：新教师邮箱；
生产写入：Auth/业务 profile，必须已有第 11.1 节授权。

1. 管理员在正式页面只邀请教师 A 一次。
2. 教师 A 必须在“已登录 Sites owner 外层身份”的浏览器会话中打开真实邀请链接，再由
   用户本人设置应用内密码；Sites owner 是外层准入，教师 A/B 是 Supabase 应用身份。
3. 首次登录成功并访问 `/auth/me`。
4. 准备另一名既有教师 B，用于跨教师隔离；不得为 B 再创建生产账号。
5. 邀请失败时先在管理员页面检查账户状态，不重复发送邀请。

### 11.3 轮换 Sites bypass 并只给本次进程使用

Sites bypass 没有可依赖的 TTL；它会持续有效，直到下一次 rotation。

执行位置：Codex Sites 连接器；不是终端或 SQL Editor；生产写入：轮换 bypass token。

1. 用户明确说：“授权为本次 Stage14 E2E 轮换 Sites bypass token”。
2. Codex 调用 Sites bypass rotation；不得读取或复用已有 token。
3. 新 token 只能由第 3 节已验收的受控执行器以内存方式交给 E2E runner；若当前产品没有
   这种 Connector → 本机 PTY 安全通道，本节立即停止，禁止显示、复制或隐藏手输 token。
4. 第 11.4 节无论成功、失败或中断，下一步都必须回到本节再次由用户授权 rotation，
   使测试 token 立即失效；第二次返回的新 token 直接丢弃。

### 11.4 运行一次真实浏览器流程

前置条件：第 3 节已验证代码只对 Sites origin 注入 bypass，且总超时已修复。

执行位置：全新终端 C + 受控 Sites 执行器；工作目录：稳定 `current` release；变量来源：
runner 交互收集非 secret，密码由 PTY 隐藏输入，bypass 只经受控内存注入；生产写入：真实
Auth/数据库/Storage/模型调用。每个唯一标题/marker 最多 `--start` 一次；仅适用第 11.1 节
明确写出的 `aborted_prewrite` 例外。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
runner="$runtime_root/current/infra/local/run-stage14-e2e.sh"
test -x "$runner"
"$runner" --start
)
```

runner 必须先断言 base URL 精确等于 final `FRONTEND_ORIGIN`，无 userinfo/path/query/fragment；
再零写入预检 UTF-8 instructions/rubric 非空且各不超过 100KB、论文绝对路径/≤20MB，并用
`stage_upload` + `parse_document(ParseLimits())` 解析。随后在 `shared/acceptance` 以原子排他
方式写入不含 secret 的 started 状态，把 Playwright output 放在本轮 `0700` 临时目录；禁止
写 sealed release。教师 B 必须先证明页面加载成功，再通过 API 403/404 和 UI 两层验证隔离。

命令结束后，先执行第 11.3 节第二次 rotation 使测试 token 失效，再看结果。

当前脚本实际通过标准是：

- 1 个 Playwright 测试、1 个作业、1 个单篇批次；
- Rubric 生成、论文上传/解析、评分、复核、确认和最终导出完成；
- 教师 B 看不到教师 A 的作业、批次和导出；
- XLSX 从该 job 的导出入口取得，文件名为 `.xlsx`、大于 1,000 字节并具有 OOXML ZIP
  `PK` 头；当前脚本不等于“已经用 Excel 打开并逐表解析”；
- 同一个签名 URL 在 TTL + 5 秒后返回 4xx；
- `390 × 844` 复用同一批次检查 `/grading-jobs`、该 export 页面、下载按钮和无横向溢出；
  当前脚本不声称手机端重新复核或重新下载；
- Console error/warning 和 page error 均为 0。

### 11.5 失败恢复规则

| 失败点 | 处理 | 禁止 |
|---|---|---|
| started 后、任何业务写入前失败 | runner 只读证明唯一标题不存在且无 Rubric/job/model request，把 marker 标为 `aborted_prewrite`；换全新标题并重新授权 | 删除旧 marker 后原样重跑 |
| Rubric 请求已发出 | 在正式 UI 查找已创建作业和 Rubric 状态 | 重跑完整 E2E、再次收费 |
| 批次已创建 | 按唯一标题进入已有 job，等待/恢复已有 item/attempt | 创建第二批次 |
| 复核或导出失败 | 只执行 runner `--resume`，从已有 job 继续 | 删除记录、重新评分 |
| 浏览器断言失败但业务已完成 | 只执行 runner `--postcondition`，验证唯一已有流 | 再跑 `--start` |
| bypass 可能泄露 | 立即再次授权 rotation | 只 `unset` 就假定服务端失效 |

## 12. 第 9 步：Worker、队列、SQL 指标和关闭项收口

### 12.1 不泄露任务参数的 Worker/队列断言

执行位置：终端 A；工作目录：稳定运行根；变量来源：common env；生产写入：无。代码只在
内存检查 `active/reserved`，失败也不打印任务参数或对象 ID。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
source "$runtime_root/shared/env/production.env"
export REDIS_URL

PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
import os
import time

import redis
from celery import Celery

expected_queues = {
    "grading": {"paper_grading.grading"},
    "maintenance": {"paper_grading.maintenance"},
    "exports": {"paper_grading.exports"},
}

app = Celery("stage14_inspect", broker=os.environ["REDIS_URL"])
client = redis.Redis.from_url(os.environ["REDIS_URL"])

def classify(nodes: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for prefix in expected_queues:
        matches = [name for name in nodes if name.startswith(f"{prefix}@")]
        if not matches:
            raise ValueError
        if len(matches) > 1:
            raise SystemExit("stage14_worker_identity_failed")
        result[prefix] = matches[0]
    if set(result.values()) != set(nodes):
        raise SystemExit("stage14_unexpected_worker_detected")
    return result

for _ in range(60):
    inspect = app.control.inspect(timeout=10)
    ping = inspect.ping() or {}
    try:
        names = classify(ping)
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        queues = inspect.active_queues() or {}
        expected_nodes = set(names.values())
        for payload in (active, reserved, queues):
            if set(payload) - expected_nodes:
                raise SystemExit("stage14_unexpected_worker_detected")
            if set(payload) != expected_nodes:
                raise ValueError
        if any(active[node] for node in expected_nodes):
            raise ValueError
        if any(reserved[node] for node in expected_nodes):
            raise ValueError
        for prefix, node in names.items():
            actual = {item.get("name") for item in queues[node]}
            if actual != expected_queues[prefix]:
                raise ValueError
        broker_counts = [
            client.llen("paper_grading.grading"),
            client.llen("paper_grading.maintenance"),
            client.llen("paper_grading.exports"),
            client.hlen("unacked"),
            client.zcard("unacked_index"),
        ]
        if any(broker_counts):
            raise ValueError
    except ValueError:
        time.sleep(5)
        continue
    print("stage14_workers_and_broker_closed=true")
    break
else:
    raise SystemExit("stage14_workers_and_broker_not_closed")
PY
)
```

这里故意只使用 broker，不导入 `app.workers.celery_app`；common env 的 API 数据库角色不能
用来加载评分 Worker Settings。

### 12.2 SQL 队列等待和失败率快照

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。只输出
聚合值，不输出教师、作业、文件、任务或 attempt ID。

```sql
select 'grading_job_items' as workload,
       count(*) filter (where status = 'queued')::bigint as queued,
       count(*) filter (where status = 'running')::bigint as running,
       coalesce(
         max(greatest(extract(epoch from (now() - available_at)), 0))
           filter (where status = 'queued' and available_at <= now()),
         0
       )::bigint as max_queue_wait_seconds
from public.grading_job_items
union all
select 'grading_jobs',
       count(*) filter (where status = 'queued')::bigint,
       count(*) filter (where status = 'running')::bigint,
       coalesce(
         max(extract(epoch from (now() - created_at)))
           filter (where status = 'queued'),
         0
       )::bigint
from public.grading_jobs
union all
select 'exports',
       count(*) filter (where status = 'queued')::bigint,
       count(*) filter (where status = 'running')::bigint,
       coalesce(
         max(extract(epoch from (now() - created_at)))
           filter (where status = 'queued'),
         0
       )::bigint
from public.exports;

with recent as (
  select 'grading_job_items'::text as workload,
         status,
         error_code,
         finished_at
  from public.grading_job_items
  where finished_at >= now() - interval '15 minutes'
    and status in ('completed', 'needs_review', 'failed')
  union all
  select 'exports', status, error_code, finished_at
  from public.exports
  where finished_at >= now() - interval '15 minutes'
    and status in ('completed', 'failed')
)
select workload,
       count(*)::bigint as terminal_count,
       count(*) filter (
         where status = 'failed'
            or (status = 'needs_review' and error_code is not null)
       )::bigint as failed_count,
       case when count(*) >= 10 then
         round(
           count(*) filter (
             where status = 'failed'
                or (status = 'needs_review' and error_code is not null)
           )::numeric / count(*),
           4
         )
       else null end as failure_rate_when_sample_is_sufficient
from recent
group by workload
order by workload;
```

第一组三行 queued/running/max wait 都必须为 0。维护任务没有独立数据库 job 表，本文件只能
用第 12.1 节的即时 Redis/active/reserved 为 0 证明当前收口，不能宣称维护队列历史等待
可见。第二组记录业务终态聚合；样本少于 10 时失败率
保持 `NULL`，不得用单篇样本宣称稳定失败率。

### 12.3 配额、保留、备份和恢复继续关闭

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。

```sql
select
  (select count(*) = 2 and bool_and(enabled = false)
   from public.quota_resource_states) as quota_disabled,
  (select count(*) = 3 and bool_and(enabled = false and retention_days = 30)
   from public.retention_policies) as retention_disabled,
  (select count(*) = 1 and bool_and(
      creation_enabled = false
      and cleanup_enabled = false
      and coalesce(btrim(target_identifier), '') = '')
   from public.backup_policies) as backup_disabled,
  (select count(*) = 0 from public.backup_runs) as no_backup_runs,
  (select count(*) = 0 from public.backup_restore_runs) as no_restore_runs,
  (select count(*) = 0 from public.quota_reservations
   where status = 'reserved') as no_quota_reservations,
  (select count(*) = 0 from public.retention_objects
   where status = 'running') as no_retention_running;

select resource,
       enabled,
       capacity_bytes is not null as capacity_configured,
       last_used_bytes is not null as usage_sample_present,
       last_checked_at is not null as check_time_present,
       last_error_code is not null as last_check_has_error
from public.quota_resource_states
order by resource;

select resource, state, count(*)::bigint as alert_count_last_24h
from public.quota_alerts
where created_at >= now() - interval '24 hours'
group by resource, state
order by resource, state;
```

第一组 7 列必须全部为 `true`。第二、三组只记录容量可见性的事实：当前生产配额关闭时，
不得写“容量告警已启用”；若用户要求活跃生产容量告警，停止阶段收口并另行授权真实容量
配置。

### 12.4 生命周期表 RLS/FORCE RLS

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。

```sql
with expected(relname) as (
  values
    ('quota_resource_states'),
    ('quota_reservations'),
    ('quota_alerts'),
    ('retention_policies'),
    ('retention_objects'),
    ('backup_policies'),
    ('backup_runs'),
    ('backup_restore_runs')
)
select count(*) = 8
       and bool_and(c.relrowsecurity)
       and bool_and(c.relforcerowsecurity) as lifecycle_rls_and_force_rls
from expected e
join pg_catalog.pg_class c on c.relname = e.relname
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public';
```

预期 `true`。这只是目标生产目录确认，不替代已经通过的 4.1 PostgreSQL 合同测试。

### 12.5 本机确认没有清理/备份 LaunchAgent

执行位置：终端 A；工作目录：无要求；变量来源：当前 UID；生产写入：无。

```zsh
(
set -euo pipefail
if launchctl print "gui/$UID" 2>/dev/null |
  /usr/bin/grep -Ei 'paper-grading.*(backup|retention|cleanup)' >/dev/null; then
  print -u2 "stage14_backup_cleanup_launch_agents_absent=false"
  exit 1
fi
setopt null_glob
unexpected_plists=(
  "$HOME"/Library/LaunchAgents/com.paper-grading.*backup*.plist(N)
  "$HOME"/Library/LaunchAgents/com.paper-grading.*retention*.plist(N)
  "$HOME"/Library/LaunchAgents/com.paper-grading.*cleanup*.plist(N)
)
if (( ${#unexpected_plists[@]} != 0 )); then
  print -u2 "stage14_backup_cleanup_plists_absent=false"
  exit 1
fi
print "stage14_backup_cleanup_launch_agents_absent=true"
)
```

### 12.6 只读记录 Database Network Restrictions 例外

执行位置：Supabase Dashboard → Database → Network Restrictions；不是终端或 SQL Editor；
变量来源：目标项目；生产写入：无。

只读记录：project ref、复核时间、当前仍为全网放行、用户接受该例外。结论必须写“已接受
例外”，不能写“安全配置通过”。不得在本次验收修改 allow list。

## 13. 第 10 步：UptimeRobot 可逆告警与恢复

### 13.1 先启用并确认正常

执行位置：UptimeRobot 页面；不是终端或 SQL Editor；变量来源：第 6.2 节创建的两个监控；生产
写入：启用监控。

1. 启用 HTTP `/health/ready` 和 Heartbeat。
2. 等待两项都显示正常。
3. 记录正常时间和页面实际 interval + grace；不记录 Heartbeat URL。

### 13.2 停导出 Worker；无论结果如何都自动恢复

前置条件：第 12.1、12.2 节全部为 0。用户确认开始一次计划内告警演练。

执行位置：终端 D；工作目录：稳定运行根；变量来源：无；生产写入：临时停止导出 Worker。
该子 Shell 的 EXIT trap 会在成功、失败或 Control-C 时尝试恢复导出 Worker；下一节还会
显式补做恢复并验证，不能只相信 trap。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
plist="$HOME/Library/LaunchAgents/com.paper-grading.export.plist"
restore_export() {
  if ! launchctl print "gui/$UID/com.paper-grading.export" >/dev/null 2>&1; then
    launchctl bootstrap "gui/$UID" "$plist"
  fi
  launchctl kickstart -k "gui/$UID/com.paper-grading.export"
  return 0
}
trap restore_export EXIT

launchctl bootout "gui/$UID" "$plist"
read -r "alert_result?在 UptimeRobot 页面等待实际 interval + grace；收到告警后输入 I_RECEIVED_ALERT，否则输入 FAIL："
test "$alert_result" = "I_RECEIVED_ALERT"
)
```

即使未收到告警，trap 也先恢复 Worker，再把本项标记失败；不得让导出 Worker 保持停止。

### 13.3 验证恢复通知和运行态

执行位置：终端 D；工作目录：稳定运行根；变量来源：无；生产写入：无。

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
exit 1
)
```

再在 UptimeRobot 等待 Heartbeat 恢复并确认实际收到一次恢复通知。通过标准：实际告警 1、
恢复通知 1、三个 Worker 在线、队列仍为 0。

## 14. 第 11 步：Mac 后端与 Sites 双版本回滚

### 14.1 进入维护窗口

执行位置：UptimeRobot 页面；不是终端或 SQL Editor；生产写入：暂停两个监控或建立计划
维护窗口。先确认第 12.1、12.2 节仍为 0，避免计划回滚产生第二轮误告警。

记录候选 SHA、回滚 SHA、候选 Sites 版本、回滚 Sites 版本；不要记录任何密钥。

### 14.2 原子切换 Mac 到回滚 SHA

执行位置：终端 D；工作目录：稳定运行根；变量来源：完整回滚 SHA；生产写入：停止业务
进程、切换 `current`、恢复 API/Worker；Redis 和 Tailscale state 保持原样。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
read -r "rollback_sha?输入完整回滚 SHA："
print -rn -- "$rollback_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
manager="$runtime_root/shared/bin/switch-release.sh"
test -x "$manager"
"$manager" "$rollback_sha"

"$runtime_root/current/infra/local/verify-runtime.sh"
print "stage14_backend_rollback_verified=true"
)
```

`switch-release.sh` 失败时保持写入进程停止并返回非 0；禁止在开发仓库执行 `git checkout`，
禁止清 Redis。

### 14.3 私有部署回滚 Sites 版本

执行位置：Codex Sites 连接器；不是终端或 SQL Editor；变量来源：第 4.5 节回滚 Sites
版本；生产写入：Sites private deployment。

1. 读取项目并再次确认 owner-only。
2. 私有部署已保存的回滚版本。
3. 轮询到明确 `succeeded` 后调用 `open_in_codex`；失败时先恢复候选 Sites，再用稳定 manager
   恢复候选 Mac 并验证，两端一致后才以失败退出。
4. Chrome 验证第 4.6 节列出的 5 个路径和 API live/ready。

部署状态、`open_in_codex`、owner-only、5 个路径或 API ready 任一未通过，都按第 3 项失败
恢复分支处理；两端一致且维护窗口仍保持后才退出。

### 14.4 SQL Editor 确认数据库没有回退

执行位置：目标生产 Supabase SQL Editor；不是终端；变量来源：无；生产写入：无。

```sql
select version_num
from public.alembic_version;
```

查询必须唯一一行且仍为 `20260728_0019`。同时重新执行第 12.1、12.2 节，确认 Worker、queued、running、
unacked 仍为 0。回滚演练不执行数据库 downgrade。

## 15. 第 12 步：恢复发布候选并重新启用监控

### 15.1 恢复 Mac 候选

执行位置：终端 D；工作目录：稳定运行根；变量来源：候选 SHA；生产写入：原子切回候选。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
read -r "candidate_sha?输入完整发布候选 SHA："
print -rn -- "$candidate_sha" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
manager="$runtime_root/shared/bin/switch-release.sh"
test -x "$manager"
"$manager" "$candidate_sha"

"$runtime_root/current/infra/local/verify-runtime.sh"
print "stage14_backend_candidate_restored=true"
)
```

### 15.2 恢复候选 Sites

执行位置：Codex Sites 连接器；不是终端或 SQL Editor；变量来源：候选 Sites 版本；生产
写入：Sites private deployment。

私有部署候选版本并轮询 `succeeded`，调用 `open_in_codex`，再次确认 owner-only。Chrome
复核第 4.6 节列出的 5 个路径和 API ready。若候选 Sites 恢复失败，把 Mac 切回回滚 SHA，
保持两端回滚一致和维护窗口，再停止排障。不得新建第三个版本代替恢复。
部署状态、打开、owner-only、路径或 API 任一失败都视为候选恢复失败，执行同一回滚分支。

### 15.3 恢复监控

执行位置：UptimeRobot 页面；不是终端或 SQL Editor；生产写入：结束维护窗口/恢复监控。

等待 HTTP 和 Heartbeat 都回到正常。随后重新执行第 12.1、12.2、12.3 和 14.4 节 SQL，
确认候选恢复、`0019` 未变、队列为 0、关闭项未变。

### 15.4 最终网络模式

不得恢复会让任一 Supabase 或启用供应商域名落入 `198.18.0.0/15` 的代理/虚拟网卡模式。
每次恢复系统代理、切换网络或修改 split-DNS 后，先进入 UptimeRobot 维护窗口；第 4.2 或
7.4 节任一失败时，立即停止 API、grading 和 export LaunchAgent，确认 8000 无监听且
grading/maintenance/export Worker 均不在线。仓库没有“API 只读模式”，不得把仍运行的 API
称为只读，也不得继续 Rubric 或评分请求。

网络修复后先在无业务进程状态重跑第 4.2 和 7.4 节；两项通过后只启动 API，执行第 10.1
节 HTTPS/CORS 冒烟。10.1 通过后才恢复 grading/export，执行 `verify-runtime.sh`，再解除
维护窗口并记录 `stage14_final_network_verified=true`。

网络探针失败时先执行以下停机块。

执行位置：终端 D；工作目录：稳定 `current`；变量来源：固定 LaunchAgent label 和 common
env 中仅导出的 `REDIS_URL`；生产写入：停止 API、评分/维护和导出进程，保留 Redis、Sites、
数据库和 Tailscale state。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
current="$runtime_root/current"
for component in api grading export; do
  plist="$agents/com.paper-grading.$component.plist"
  test -f "$plist"
  test ! -L "$plist"
  if /bin/launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
    /bin/launchctl bootout "gui/$UID" "$plist"
  fi
done
for component in api grading export; do
  if /bin/launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
    print -u2 "stage14_network_failure_shutdown=false"
    exit 1
  fi
done
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "stage14_network_failure_shutdown=false"
  exit 1
fi
source "$runtime_root/shared/env/production.env"
export REDIS_URL
PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

app = Celery("stage14_network_shutdown", broker=os.environ["REDIS_URL"])
nodes = app.control.inspect(timeout=3).ping() or {}
if any(
    name.startswith(("grading@", "maintenance@", "exports@"))
    for name in nodes
):
    raise SystemExit("stage14_network_failure_workers_still_online")
print("stage14_network_failure_workers_offline=true")
PY
print "stage14_network_failure_shutdown=true"
)
```

第 4.2 和 7.4 节恢复通过后，只启动 API：

执行位置：终端 D；工作目录：无要求；变量来源：固定 API plist；生产写入：只恢复 API。

```zsh
(
set -euo pipefail
plist="$HOME/Library/LaunchAgents/com.paper-grading.api.plist"
test -f "$plist"
test ! -L "$plist"
/bin/launchctl bootstrap "gui/$UID" "$plist"
/bin/launchctl kickstart -k "gui/$UID/com.paper-grading.api"
print "stage14_network_recovery_api_only=true"
)
```

API 启动后立即执行第 10.1 节；其中任一请求或断言失败，都必须重新执行本节前面的
`stage14_network_failure_shutdown` 停机块，并看到两个 offline/ shutdown 固定标记后停止。
不得让失败的 API 冒烟留下 API 在线。

执行第 10.1 节并通过后，才恢复评分/维护和导出：

执行位置：终端 D；工作目录：稳定 `current`；变量来源：固定 Worker plist；生产写入：恢复
评分/维护和导出 Worker。

```zsh
(
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
agents="$HOME/Library/LaunchAgents"
current="$runtime_root/current"

cleanup_business() {
  for component in api grading export; do
    plist="$agents/com.paper-grading.$component.plist"
    if /bin/launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      /bin/launchctl bootout "gui/$UID" "$plist" >/dev/null 2>&1 || true
    fi
  done
  return 0
}

if ! (
  set -euo pipefail
  for component in grading export; do
    plist="$agents/com.paper-grading.$component.plist"
    test -f "$plist"
    test ! -L "$plist"
    /bin/launchctl bootstrap "gui/$UID" "$plist"
    /bin/launchctl kickstart -k "gui/$UID/com.paper-grading.$component"
  done
  "$current/infra/local/verify-runtime.sh"
); then
  cleanup_business
  for component in api grading export; do
    if /bin/launchctl print "gui/$UID/com.paper-grading.$component" >/dev/null 2>&1; then
      print -u2 "stage14_network_recovery_cleanup=false"
      exit 1
    fi
  done
  if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    print -u2 "stage14_network_recovery_cleanup=false"
    exit 1
  fi
  source "$runtime_root/shared/env/production.env"
  export REDIS_URL
  PYTHONPATH="$current/backend" "$current/.venv/bin/python" - <<'PY'
import os
from celery import Celery

app = Celery("stage14_network_recovery_cleanup", broker=os.environ["REDIS_URL"])
nodes = app.control.inspect(timeout=3).ping() or {}
if any(
    name.startswith(("grading@", "maintenance@", "exports@"))
    for name in nodes
):
    raise SystemExit("stage14_network_recovery_workers_still_online")
print("stage14_network_recovery_workers_offline=true")
PY
  print -u2 "stage14_network_recovery_cleanup=true"
  exit 1
fi
print "stage14_final_network_verified=true"
)
```

任一恢复块失败都保持维护窗口，不得继续模型业务。

## 16. 失败停止矩阵

| 失败 | 立即动作 | 保持不变 |
|---|---|---|
| 第 3.1—3.3 节代码/CI 门禁失败 | 停止全部生产步骤，另立开发任务 | Supabase、Sites、Auth、环境、模型费用 |
| Tailscale/Funnel 失败 | 第 9.2 节接管前执行第 4.3 节临时恢复块；接管后走受管 runtime 恢复 | 不 reset 未知旧配置，不启动第二 daemon |
| Sites 保存/部署失败 | 保存阶段按第 4.5 节 lease 恢复 source branch；部署阶段保持 owner-only 并恢复已知 version_id；业务前中止还恢复 Auth 快照 | 不公开、不新建项目、不覆盖并发 source 更新 |
| Supabase 目标不一致 | 立即停止，关闭 Direct URL 子 Shell | 不迁移、不改角色 |
| 专用角色探针失败 | 检查 URL/密码；密码变更需新授权 | 不用 API/admin 角色替代 Worker |
| 配置探针失败 | 取得授权，用 `update-production-env.sh --replace` 原子恢复/更正后重验 | 不手编或只替换半套 env |
| 迁移失败 | 保持 API/Worker 停止，保存脱敏错误 | 不 downgrade、不重复执行 |
| 首次 runtime 安装/验证失败 | 运行第 9.3 节幂等回滚块，确认 6 个本轮 label、8000 和三个 Worker 均停；恢复受管 Funnel，并经授权恢复 Auth 快照 | Sites 保持 owner-only、监控暂停，不留下半部署服务 |
| 重新登录恢复失败 | 进入维护窗口，停止 API/三个 Worker，确认 8000 无监听后排查 | 不开始或继续业务流，不称 API 为只读 |
| 付费 E2E 部分失败 | 旋转 bypass、按唯一标题恢复已有 job | 不重跑、不删除、不创建第二批次 |
| 告警未收到 | EXIT trap 先恢复导出，再标记失败 | 不让 Worker 长期停机 |
| 回滚/恢复失败 | 用稳定 manager 和已保存 version_id 恢复同一组双端版本 | 不留下前后端版本分叉，不清 Redis/回退数据库 |
| 网络模式改变后探针失败 | 进入维护窗口，停 API/grading/export 并确认离线；修复后先跑 4.2/7.4，再只启 API 跑 10.1，最后恢复 Worker | 不继续付费流，不假设 API 只读，不开启 fake-IP 例外 |
| 任一 secret 泄露 | 停止，轮换对应 secret 后重做受影响最小范围 | 不在聊天继续传播 |

## 17. 最终通过标准

| 范围 | 必须满足 |
|---|---|
| 代码门禁 | 第 3 节全部实现并自动通过；两个不同 SHA 均已推送且 CI 8 通过、失败 0 |
| 版本一致 | Mac 和 Sites 候选来自同一候选 SHA；回滚两端来自同一回滚 SHA |
| 数据库 | 目标项目为 `20260728_0019`，从未 downgrade；迁移前后 queued/running 为 0 |
| Sites | 两个保存版本；候选私有部署成功；全程 owner-only；第 4.6 节的 5 个路径不 404 |
| HTTPS/CORS | API 只经 Funnel HTTPS；HTTP 不提供应用；CORS 只允许 Sites origin |
| 本机边界 | Redis/API 只监听回环；env 非 symlink、owner 正确、`0600`；日志权限固定 |
| 自动恢复 | 6 个 LaunchAgent 正常；API、grading/maintenance、export、Tailscale 强制退出和重新登录后恢复 |
| Worker/队列 | 三个 Worker 心跳和唯一队列正确；active/reserved/queued/running/unacked 均为 0 |
| Auth/Storage | 公开注册关闭；callback 集合精确；bucket 私有、50MiB、PDF/DOCX/JSON/XLSX 四种 MIME；论文入口仍限 20MiB；`storage.objects` RLS 开启且 policy 为 0 |
| 真实业务 | 只创建 1 个单篇批次；Rubric、评分、复核和导出完成；不重跑完整付费流程 |
| 浏览器覆盖 | 首次 full-flow 为 1 通过、0 失败；或首次失败后受审 resume/postcondition 通过，并证明唯一作业/批次/模型流；覆盖双教师隔离和已列手机范围 |
| 下载 | 同 job 取得的 XLSX 大于 1,000 字节且有 `PK` 头；签名 URL 过期后 4xx |
| 监控 | HTTP/Heartbeat 正常；实际收到一次计划告警和一次恢复通知；回滚期间使用维护窗口 |
| 回滚 | Mac 和 Sites 都切到回滚版本并恢复候选；数据库仍为 `0019`；Redis 未清空 |
| 关闭项 | 配额、自动清理、备份创建/清理继续关闭；没有 backup/restore run；无对应 LaunchAgent |
| 网络例外 | Network Restrictions 全网放行只记录为“用户接受的例外”，不写成安全通过 |
| 容量口径 | 若生产配额继续关闭，明确写“活跃容量告警未启用”；若阶段 14 必须要求活跃告警，则先单独授权配置或批准调整计划 |

任一行未满足，阶段 14 不得标记完成。

## 18. Bug Review、第一性原理复查和项目记录

执行位置：Codex + 终端 A + GitHub Actions；生产写入：无新增业务写入。

1. Review 本轮所有脚本、配置、Sites 版本、SQL 和文档，修复真实问题。
2. 第一性原理复查：是否存在更少状态、更少凭据、更少进程、更明确失败边界的实现；不得
   用跳过验证或扩大权限换取“通过”。
3. 重新执行第 3.2 节门禁、受影响的最小自动化和 `git diff --check`。
4. 在本文记录实际日期、候选/回滚 SHA、两个 Sites 版本、迁移头、固定布尔标记、通过/
   失败数量、告警/恢复和回滚结果；不得记录 secret 或业务 ID。
5. 同步 `task_plan.md`、`progress.md`、`findings.md`、`CONTEXT.md`。
6. 提交验收记录，等待该记录提交的 GitHub CI 8 项全部通过。
7. 分开记录“实际部署候选 SHA”和“最终验收记录 SHA”；纯文档提交不能冒充已部署版本。

最终安全回传模板：

- 候选 SHA：`<40位 SHA>`
- 回滚 SHA：`<40位 SHA>`
- Sites 候选/回滚版本：`<版本号>/<版本号>`
- 迁移：`20260728_0019`
- CI：`8 passed, 0 failed`
- runtime：`true/false`
- Worker/队列收口：`true/false`
- 单篇 E2E：`1 passed, 0 failed` 或明确失败
- 告警/恢复：`received/not received`
- 双版本回滚并恢复：`true/false`
- 配额/清理/备份：`disabled`
- Network Restrictions：`用户接受的例外`
- 活跃容量告警：`enabled` 或 `not enabled`，不得模糊

不得回传环境变量、邮箱、Token、Key、数据库/Heartbeat URL、project ref、IP、论文、
模型原始响应、对象路径、业务 ID 或签名 URL。

质量校准和生产上线最终验收是阶段 14 之后的独立事项。质量校准必须使用真实题目、
Rubric 和教师基准分，不能用本阶段单篇部署冒烟或 100 篇结构证据代替。
