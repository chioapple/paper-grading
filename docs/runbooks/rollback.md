# 失败部署回滚 Runbook

执行终端、前置条件、预期结果和安全回传必须按每一步记录；安全回传只包含 Git SHA、
Sites 版本、revision、状态码、进程状态和队列计数。

## 原则

- 先停止新任务，再回滚应用；生产数据库不 downgrade。
- 后端只回滚到确认兼容 `0019` 的 Git SHA。
- 前端只回滚到确认兼容当前 Funnel API 和 Supabase 配置的 Sites 保存版本。
- Redis 不清空；运行中任务由既有租约、幂等和失败收口处理。
- 若新迁移与旧代码不兼容，保持进程停止，新增前向修复迁移。
- 若回滚 SHA 早于 `PROVIDER_CALLS_ENABLED=false` 硬门禁，回滚期间只启动 API 和导出 Worker；
  评分/维护 Worker 必须保持停止，且只执行健康检查，不登录、不写入。

## 操作

### 1. 冻结

执行终端：本机。
预期结果：先停止评分/维护 Worker和导出 Worker，再停止 API；Sites 前端可以继续显示，
但 API 写入失败关闭。

```bash
launchctl bootout \
  "gui/$UID" \
  "$HOME/Library/LaunchAgents/com.paper-grading.grading.plist"
launchctl bootout \
  "gui/$UID" \
  "$HOME/Library/LaunchAgents/com.paper-grading.export.plist"
launchctl bootout \
  "gui/$UID" \
  "$HOME/Library/LaunchAgents/com.paper-grading.api.plist"
```

### 2. 记录现场

只记录失败进程、Git SHA、Sites 版本、迁移 revision、队列计数和稳定错误分类。日志必须
脱敏，不记录环境变量或任务内容。

### 3. 回滚 Mac 后端

前置条件：目标 SHA 已在 `0019`、当前生产环境文件和专用 Worker 角色下通过验证。
预期结果：原子切换封存 `current` 后，按目标 SHA 的安全边界启动进程；本阶段固定回滚 SHA
早于模型硬门禁，因此只启动 API 和导出 Worker，Redis 保留原数据。

不得用 `git reset --hard` 或覆盖用户改动。验收时使用单独保存的、已验证构建目录切换
`current` 符号链接；如果尚未准备该目录，保持服务停止并先完成前向修复。

### 4. 回滚 Sites

执行位置：Codex Sites。
前置条件：目标 Sites 版本已经保存并验证，与回滚后端 SHA 和当前 Supabase 配置兼容。
预期结果：部署该保存版本后，登录、深层路径刷新和只读 API 健康检查通过。

### 5. 验证

```bash
set -euo pipefail
runtime_root="$HOME/Library/Application Support/Paper Grading"
current="$runtime_root/current"
set -a
source "$runtime_root/shared/env/production.env"
set +a
test "${PROVIDER_CALLS_ENABLED:-}" = "false"
launchctl print "gui/$UID/com.paper-grading.api" >/dev/null
launchctl print "gui/$UID/com.paper-grading.export" >/dev/null
if launchctl print "gui/$UID/com.paper-grading.grading" >/dev/null 2>&1; then
  exit 1
fi
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null
curl --fail --silent --show-error \
  "${VITE_API_BASE_URL%/}/health/live" >/dev/null
curl --fail --silent --show-error \
  "${VITE_API_BASE_URL%/}/health/ready" >/dev/null
"$current/.venv/bin/celery" -b "$REDIS_URL" inspect ping --json --timeout 10
```

### 6. 恢复发布候选

依次恢复发布候选后端目录和 Sites 版本，再执行：

```bash
runtime_root="$HOME/Library/Application Support/Paper Grading"
"$runtime_root/current/infra/local/verify-runtime.sh"
```

再次验证 live、ready、三个 Worker 心跳、队列、数据库 revision 和 Sites 深层路径。数据库仍为
`0019`，Redis 未清空。

### 7. 数据库处置

如果问题来自迁移且旧代码不能安全运行，不执行 downgrade。服务保持停止，创建新的
前向修复迁移后重新走 CI。
