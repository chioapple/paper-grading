# 阶段 4 Supabase 验收

本流程只用于独立 Supabase 测试项目。不要对生产项目执行。所有命令由用户在项目根目录运行，Codex 不连接或修改 Supabase。

## 第一轮：迁移与 PostgreSQL 隔离

前提：测试项目当前迁移必须是 `20260714_0005`；`.env.stage2-test` 中的两个 Auth UUID 必须真实存在且没有 profile。两个用户必须通过 Supabase Dashboard 的直接创建用户操作建立，不能使用“发送邀请”，否则阶段 3 触发器会先创建 profile。

```bash
set -a
source .env.stage2-test
set +a
MIGRATION_DATABASE_URL="$TEST_MIGRATION_DATABASE_URL" .venv/bin/alembic -c backend/alembic.ini current
```

确认输出为 `20260714_0005` 后执行迁移：

```bash
MIGRATION_DATABASE_URL="$TEST_MIGRATION_DATABASE_URL" .venv/bin/alembic -c backend/alembic.ini upgrade 20260715_0006
```

然后清除可能存在的部署迁移变量，只运行阶段 4 测试文件：

```bash
unset MIGRATION_DATABASE_URL
.venv/bin/pytest -m postgres backend/tests/security/test_stage_four_postgres.py
```

该测试会：

- 只读检查 11 张表的强制 RLS、20 条策略、专用角色和最小权限；
- 为 `.env.stage2-test` 中两个 Auth 用户临时创建 active teacher profile 和各一条 assignment；
- 验证跨教师读取、更新、伪造 owner、删除、自提权、停用状态和连接池身份清理；
- 测试结束时删除上述临时 assignment 和 profile，不删除 Auth 用户。

执行后先停止并把以下结果发给 Codex：

- `alembic current` 的输出；
- 迁移命令是否成功；
- pytest 的通过/失败数量和完整失败信息（如有）。

### 已迁移但 Auth 用户前置条件不满足

如果迁移已经成功到 `20260715_0006`，但测试提示 Auth 用户不存在，不要回退或重复迁移：

1. 在独立 Supabase 测试项目直接创建两个测试用户，不发送邀请。
2. 复制两个用户的真实 UUID，替换 `.env.stage2-test` 中的 `TEST_TEACHER_AUTH_USER_ID` 和 `TEST_OTHER_AUTH_USER_ID`。
3. 只重新运行阶段 4 测试文件。测试会临时创建并清理 profile 和 assignment，不删除 Auth 用户。

### 失败中断后的测试数据清理

如果旧版测试在创建 profile 后因连接池超时中断，可能遗留两个测试 profile 和 assignment。重新运行前，先在 Supabase SQL Editor 中显式删除这两个测试用户的业务数据和 profile；不得删除 Auth 用户。具体 UUID 必须使用 `.env.stage2-test` 中当前两个测试值。

## 第二轮：Data API、停用旧 Token 与邀请回归

第一轮已确认通过 2、失败 0。第二轮只使用独立 Supabase 测试项目，并验证：

1. active teacher 的真实 JWT 通过 publishable key 直接请求 11 张业务表时全部被拒绝；
2. 保存教师旧 Token，管理员停用教师后，旧 Token 请求 FastAPI `/auth/me` 返回 403，Data API 仍拒绝；
3. 测试结束必须重新启用该教师；
4. 管理员邀请一个全新测试邮箱，接口返回 `teacher / invited`，证明 `FORCE RLS` 后邀请 profile 触发器仍工作；
5. 读取 Supabase Database 下的 Security Advisor 和 Performance Advisor，回传全部 warning/error；
6. 不删除邀请测试用户或其他外部数据，清理由用户另行确认。

当前结果：

- active teacher 直连 11 张业务表：全部 HTTP 403、PostgreSQL 代码 42501；
- 停用教师：204；旧 Token 请求 FastAPI：403；旧 Token 请求 Data API：403/42501；
- 重新启用教师：204；
- 邀请回归：201，并返回 `teacher / invited` profile 与邀请时间；
- Security Advisor：错误 0、警告 1、建议 2；唯一警告为 Auth 的泄露密码保护未启用，不属于阶段 4 的 RLS 或数据库权限缺陷；
- Performance Advisor：错误 0、警告 0、建议 12。

## 验收结论

阶段 4 已完成。真实迁移、最小权限、跨教师隔离、连接池身份清理、Data API 拒绝、停用旧 Token、邀请回归和 Advisors 均已通过。
