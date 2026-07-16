# 阶段 3 真实验收

阶段 3 只有在独立 Supabase 测试项目完成以下检查后才算完成。本文件中的迁移、邀请、停用和启用都会修改外部状态，执行前必须再次取得确认。

## 1. 前置配置

- Supabase Auth 的公开注册已关闭；`GET /auth/v1/settings` 必须返回 `disable_signup: true`。
- Auth Site URL 与 Redirect URLs 包含实际前端地址和 `/auth/callback`。
- 测试环境使用独立 PostgreSQL direct 地址；当前部署数据库不得参与破坏性验收。
- 正式环境使用自有 SMTP；Supabase 默认 SMTP 只用于开发检查。
- `SUPABASE_SECRET_KEY` 只注入后端；前端只使用 publishable key。

## 2. 应用迁移

```bash
MIGRATION_DATABASE_URL='postgresql+asyncpg://...?ssl=require' \
  .venv/bin/alembic -c backend/alembic.ini upgrade 20260714_0005
```

验收：

- Alembic 版本为 `20260714_0005`。
- 普通注册创建的 Auth 用户不会获得 profile。
- 只有插入即受邀或 `invited_at` 首次从空变为有值的管理员邀请会创建 `teacher / invited` profile。
- 触发函数没有授予 `PUBLIC`、`anon`、`authenticated` 或 `service_role` 直接执行权限。

## 3. 唯一管理员引导

启动前后端并确认 `http://127.0.0.1:5173` 可访问后再执行引导。Supabase 会在重定向前消耗一次性邮件令牌；前端未启动时点击链接，旧链接也可能失效。

```bash
cd backend
APP_ENV=development \
DATABASE_URL='postgresql+asyncpg://...?ssl=require' \
SUPABASE_URL='https://<project-ref>.supabase.co' \
SUPABASE_PUBLISHABLE_KEY='sb_publishable_...' \
SUPABASE_SECRET_KEY='sb_secret_...' \
AUTH_INVITE_REDIRECT_URL='http://127.0.0.1:5173/auth/callback' \
FRONTEND_ORIGIN='http://127.0.0.1:5173' \
../.venv/bin/python -m app.auth.bootstrap_admin \
  --email 'admin@example.edu' \
  --display-name '总管理员' \
  --confirm 'I_UNDERSTAND_THIS_INVITES_AND_PROMOTES_ONE_ADMIN'
```

该命令只允许一个总管理员；重复使用同一邮箱幂等返回，其他邮箱会被拒绝。

## 4. 浏览器与 API 行为

| 检查 | 通过条件 | 状态 |
|---|---|---|
| 管理员首次设密 | 邀请回调可设置密码并进入管理员页面 | 通过 |
| 教师邀请 | 管理员发送邀请后，教师显示为“待激活” | 通过 |
| 公开注册 | 未邀请邮箱无法注册 | 通过 |
| 教师权限 | 教师访问 `/admin/users` 返回 403 | 通过 |
| 过期链接 | 页面明确显示链接失效，不创建会话 | 通过 |
| 找回密码 | 已有账户可从邮件回调设置新密码 | 通过 |
| 停用旧会话 | 停用后，旧令牌访问 `/auth/me` 立即返回 403 | 通过 |
| 重新启用 | 管理员启用后，教师可重新登录 | 通过 |
| 密钥边界 | 浏览器请求、前端构建和 API 响应均不含 secret key | 按用户决定不再阻塞阶段 3 |

## 5. 当前记录

| 项目 | 当前状态 |
|---|---|
| 本地前后端实现 | 已完成 |
| 本地自动化与浏览器验收 | 已通过 |
| 测试项目 Alembic | `20260714_0005`，两个邀请同步触发器均已确认存在 |
| 测试项目 Auth | 管理员与教师真实登录流程已通过 |
| 公开注册 | `disable_signup=true`，且用户确认未受邀邮箱无法注册 |
| 唯一管理员 | `18zzzjay@gmail.com`，`admin / active` |
| 教师邀请 | 用户确认真实邀请、邮件回调和教师登录均已通过；早期 429 失败保留在 `progress.md` |
| 教师账户管理 | 权限限制、找回密码、停用旧会话和重新启用均已通过 |
| 误邀账号 | `zzz725280282@gmail.com` 已确认但无 profile，未经确认不修改 |
| 外部状态修改 | `0005`、公开注册关闭和唯一管理员引导均已完成 |
| 密钥边界 | 用户确认 secret key 问题视为已解决，不再阻塞阶段 3 |
| 阶段结论 | 真实功能验收通过 8，失败 0；阶段 3 已完成 |

## 6. 完成规则

只有以上项目全部通过，才能把 `task_plan.md` 的阶段 3 改为完成，并在 `progress.md` 记录真实测试数量和测试项目状态。正式 SMTP、生产域名和 Render 配置未完成时，仍不得写成生产可上线。
