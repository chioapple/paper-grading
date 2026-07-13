# CONTEXT

- 当前正在做什么：阶段 2“Supabase 数据库”进行中；本地模型、约束、索引、默认拒绝的 RLS、连接池和 Alembic 迁移已落地。
- 上次停在哪：后端普通自动化测试通过 27、失败 0，前端回归测试通过 5、失败 0；3 个破坏性真实 Supabase 测试默认排除，显式选择时缺配置会失败。
- 关键决定：Alembic 是唯一迁移事实源；生产应用使用启用 SSL 的 Supavisor session pooler 5432；部署迁移使用独立 `MIGRATION_DATABASE_URL` direct 地址；真实破坏性验收另用 `TEST_MIGRATION_DATABASE_URL`；跨教师关系由复合外键阻止；`profiles.id` 必须来自 `auth.users`。
- 当前下一步：取得独立测试项目的 URL、project ref、两个 Auth 用户和用户确认后，执行升级、回退、重建、系统目录、RLS 拒绝及非法写入验收。
- 重要边界：所有改动仅限 `/Users/a1-6/Documents/Paper Grading`；真实数据库操作和自动删除真实文件前必须再次确认。
