# 部署 Runbook

## 安全边界

- 本方案只用于用户个人、非商业使用；Tailscale Personal 不用于组织或商业部署。
- Supabase 继续承载数据库、Auth 和 Storage；Mac 只承载 API、Redis 和三个 Worker。
- Sites 只托管前端，不保存数据库密码、Supabase Secret Key 或供应商密钥。
- Redis 和 FastAPI 只监听 `127.0.0.1`；公网只能通过 Tailscale Funnel 访问 API。
- `.env.stage14-production` 与 `.env.stage14-grading-worker` 必须保持在仓库忽略范围，
  权限固定为 `0600`。
- 生产数据库只前向迁移，不执行 downgrade；Redis 不执行 `FLUSHALL` 或 `FLUSHDB`。
- 自动清理、备份创建和备份清理保持关闭。
- `launchd` 是进程事实源；Sites 保存版本是前端回滚事实源；Git SHA 是源代码事实源。

## 发布提交门禁

执行终端：本机项目根目录与 GitHub Actions。
前置条件：待发布改动已提交；工作树干净；该 SHA 的 CI 全部成功。
预期结果：本机 HEAD、GitHub CI、Sites 源版本和 Mac 运行代码使用同一 SHA。
安全回传：commit SHA 和 CI 结果；不回传环境变量。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
git diff --quiet
git diff --cached --quiet
test -z "$(git status --porcelain)"
STAGE14_RELEASE_SHA=$(git rev-parse HEAD)
test -n "$STAGE14_RELEASE_SHA"
```

## 固定顺序

### 1. 数据库迁移

执行终端：本机项目根目录。
前置条件：CI 全绿；API 和 Worker 已停止；`MIGRATION_DATABASE_URL` 是 Supabase
Direct 连接。
预期结果：只前向升级到 `20260728_0019`。
安全回传：最终 revision 和命令退出码。

```bash
cd "/Users/a1-6/Documents/Paper Grading/backend"
test -n "${MIGRATION_DATABASE_URL:?missing MIGRATION_DATABASE_URL}"
../.venv/bin/alembic upgrade 20260728_0019
../.venv/bin/alembic current
```

### 2. 本机 Redis

执行终端：本机。
前置条件：Homebrew Redis 已安装。
预期结果：Redis 登录后自动启动，只监听本机，内存淘汰策略为 `noeviction`。
安全回传：PONG、监听地址和策略；不回传队列内容。

```bash
brew services start redis
test "$(/opt/homebrew/bin/redis-cli ping)" = "PONG"
test "$(/opt/homebrew/bin/redis-cli CONFIG GET maxmemory-policy | tail -1)" = "noeviction"
lsof -nP -iTCP:6379 -sTCP:LISTEN
```

监听结果只能包含回环地址。不得为了验收开放 Redis 公网访问。

### 3. 生产环境文件

执行终端：本机，不在聊天中粘贴变量值。
前置条件：Sites 正式 URL 和 Funnel 正式 URL 已确定；专用 Worker 密码已在 Supabase
交互设置。
预期结果：

- `.env.stage14-production` 包含 API、导出 Worker、Supabase、Redis、正式前端和
  Funnel 配置；UptimeRobot Keyword monitor 只在其网页端保存；
- `.env.stage14-grading-worker` 只覆盖评分 Worker 的 `DATABASE_URL`；
- 两个文件权限均为 `0600`；
- 评分 Worker 使用 `paper_grading_worker.<project-ref>`；
- 导出 Worker 使用 `paper_grading_export_worker.<project-ref>`。

模板见 `infra/local/production.env.example`。密钥不得写入模板、Git、进程参数或日志。

### 4. 本机进程

执行终端：本机项目根目录。
前置条件：Redis、两个环境文件和 Tailscale 登录状态已经准备。
预期结果：API、评分/维护 Worker、导出 Worker、Tailscale、防休眠与 watchdog 均由
用户级 `launchd` 管理；重新登录后自动恢复。
安全回传：固定通过标记和进程状态。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/install-launch-agents.sh
./infra/local/verify-runtime.sh
```

用户级 LaunchAgent 只承诺“登录后自动恢复”，不宣称在 macOS 登录界面之前已经运行。

### 5. Tailscale Funnel

执行位置：本机终端与 Chrome。
前置条件：使用个人、非商业 Tailscale 账户；API 只监听 `127.0.0.1:8000`。
预期结果：Funnel 通过固定 `https://*.ts.net` 地址代理本机 API；HTTP 明文入口不可用；
重启 Tailscale LaunchAgent 后 URL 不变且健康检查恢复。
安全回传：Funnel 域名、HTTPS 状态和重启恢复结果；不回传登录链接或设备密钥。

首次授权完成后，持久运行由 `infra/local/run-tailscale.sh` 和
`com.paper-grading.tailscale` 管理。

### 6. Sites 前端

执行位置：Codex Sites。
前置条件：使用正式 Funnel URL 和同一 Supabase 项目完成生产构建；本地
`npm run test:sites` 通过；源代码已经提交。
预期结果：保存并部署一个仅本人可访问的 Sites 正式版本；Sites 版本与 Git SHA
可对应；深层路径刷新不返回 404；四个安全响应头存在。
安全回传：Sites 正式 URL、版本号、部署状态和测试通过/失败数量。

如果需要把 Sites 改为公开访问，必须先单独确认访问范围；公开不是个人落地的默认值。

### 7. Supabase Auth

执行位置：Supabase Dashboard。
前置条件：Sites 正式 URL 已确定。
预期结果：Site URL 和 Redirect URLs 包含正式 Sites 来源及
`https://<Sites 域名>/auth/callback`；旧本地回调可以保留用于开发。
安全回传：域名和配置是否完成，不回传账户或密钥。

### 8. 冒烟、告警与回滚

按顺序执行：

1. `smoke-test.md`；
2. `monitoring-and-incidents.md` 的告警与恢复测试；
3. `rollback.md` 的后端和 Sites 双版本回滚；
4. 恢复发布候选后再次执行只读健康检查。

## 停止条件

任一步失败立即停止后续部署。不得重试已经发送的付费模型请求，不清空 Redis，不回退
生产数据库，不使用临时公网 IP 或未认证的代理替代 Funnel。
