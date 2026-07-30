# 失败部署回滚 Runbook

执行终端、前置条件、预期结果和安全回传必须按每一步记录；安全回传只包含 Git SHA、
Sites 版本、revision、状态码、进程状态和队列计数。

## 原则

- 先停止新任务，再回滚应用；生产数据库不 downgrade。
- 后端只回滚到确认兼容 `0019` 的 Git SHA。
- 前端只回滚到确认兼容当前 Funnel API 和 Supabase 配置的 Sites 保存版本。
- Redis 不清空；运行中任务由既有租约、幂等和失败收口处理。
- 若新迁移与旧代码不兼容，保持进程停止，新增前向修复迁移。

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
预期结果：工作树切到目标 SHA 后，依次恢复 API、评分/维护 Worker和导出 Worker；
Redis 保留原数据。

不得用 `git reset --hard` 或覆盖用户改动。验收时使用单独保存的、已验证构建目录切换
`current` 符号链接；如果尚未准备该目录，保持服务停止并先完成前向修复。

### 4. 回滚 Sites

执行位置：Codex Sites。
前置条件：目标 Sites 版本已经保存并验证，与回滚后端 SHA 和当前 Supabase 配置兼容。
预期结果：部署该保存版本后，登录、深层路径刷新和只读 API 健康检查通过。

### 5. 验证

```bash
cd "/Users/a1-6/Documents/Paper Grading"
./infra/local/verify-runtime.sh
test -n "${STAGE14_API_BASE_URL:?missing API URL}"
curl --fail --silent --show-error \
  "${STAGE14_API_BASE_URL%/}/health/live" >/dev/null
curl --fail --silent --show-error \
  "${STAGE14_API_BASE_URL%/}/health/ready" >/dev/null
```

### 6. 恢复发布候选

依次恢复发布候选后端目录和 Sites 版本，再次验证 live、ready、三个 Worker 心跳、队列、
数据库 revision 和 Sites 深层路径。数据库仍为 `0019`，Redis 未清空。

### 7. 数据库处置

如果问题来自迁移且旧代码不能安全运行，不执行 downgrade。服务保持停止，创建新的
前向修复迁移后重新走 CI。
