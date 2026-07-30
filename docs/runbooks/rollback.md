# 失败部署回滚 Runbook

## 原则

- 先阻止新流量和新任务，再回滚应用；生产数据库不 downgrade。
- 只回滚到确认兼容 `0019` 的最后成功 API、Worker 和前端构建。
- Redis 不清空；运行中任务由现有租约、幂等和失败收口处理。
- 若新迁移与旧代码不兼容，保持服务停止，新增前向修复迁移。
- 只有预发布时已在 `0019`、专用 Worker 数据库角色和精简环境变量下验证并记录的 `STAGE14_ROLLBACK_SHA` 才能作为回滚目标；没有该证据时保持服务 Suspend，直接进入前向修复。

## 操作

### 1. 冻结

执行终端：Render Dashboard。
前置条件：已确认部署失败。
预期结果：先在 Render Suspend 评分/维护 Worker 和导出 Worker，再 Suspend API；静态前端可以继续显示，但所有 API 写入均失败关闭。
安全回传：停止的服务名和时间，不回传任务内容。

### 2. 记录现场

执行终端：Render Dashboard 与 Supabase SQL Editor。
前置条件：服务已冻结。
预期结果：记录失败服务、构建 ID、迁移 revision、队列长度和安全错误分类。
安全回传：构建 ID、revision、计数和错误分类；日志必须脱敏。

### 3. 回滚应用

执行终端：Render Dashboard。
前置条件：已选择预发布证据中记录的 `STAGE14_ROLLBACK_SHA`；它已在 `0019` 和当前最小环境变量下通过 API ready、Worker 数据库探针与心跳。若不存在，停止本节并保持服务 Suspend。
预期结果：全部选择同一个已确认兼容 `0019` 的 commit SHA；依次 Resume/恢复 API、评分/维护 Worker、导出 Worker、前端；Redis 保留原数据。
安全回传：各服务回滚后的构建 ID和状态。

### 4. 验证

执行终端：本机项目根目录。
前置条件：回滚构建已启动。
预期结果：健康检查、心跳、队列和只读冒烟通过；写入测试仅在用户授权后执行。
安全回传：通过/失败数量和状态码。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
test -n "${STAGE14_API_BASE_URL:?missing STAGE14_API_BASE_URL}"
curl --fail --silent --show-error "${STAGE14_API_BASE_URL%/}/health/live" >/dev/null
curl --fail --silent --show-error "${STAGE14_API_BASE_URL%/}/health/ready" >/dev/null
```

### 5. 恢复发布候选

执行终端：Render Dashboard、本机项目根目录和 Supabase SQL Editor。
前置条件：第 4 步回滚验证通过；`STAGE14_RELEASE_SHA` 仍是本轮已通过 CI 的发布候选。
预期结果：对 API、评分/维护 Worker、导出 Worker和前端依次选择 “Deploy a specific commit”，部署同一个 `STAGE14_RELEASE_SHA`；恢复后 live/ready、三个 Worker 心跳和只读冒烟通过，数据库仍为 `0019`，Redis 未清空。
安全回传：发布 SHA、构建 ID、状态码、心跳、revision 和 Redis 计数；不回传环境变量。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
test -n "${STAGE14_RELEASE_SHA:?missing release SHA}"
test -n "${STAGE14_API_BASE_URL:?missing API URL}"
curl --fail --silent --show-error "${STAGE14_API_BASE_URL%/}/health/live" >/dev/null
curl --fail --silent --show-error "${STAGE14_API_BASE_URL%/}/health/ready" >/dev/null
```

### 6. 数据库处置

执行终端：Supabase SQL Editor。
前置条件：确认问题来自迁移且旧代码不能安全运行。
预期结果：不执行 downgrade；服务保持停止，创建新的前向修复迁移后重新走 CI。
安全回传：当前 revision 和是否需要前向修复，不回传查询结果中的业务数据。
