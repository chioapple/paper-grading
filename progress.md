# 开发进度

## 2026-07-13

- 已确认多用户英文作文批改网站总体方案。
- 已确定支持 DeepSeek、Kimi、智谱 GLM、OpenAI、Anthropic、Gemini 和兼容 API。
- 已将详细开发步骤同步到当前项目。
- 已完成 React/Vite/TypeScript App Shell，包含路由、双语、响应式布局和真实本地交互。
- 已完成 FastAPI 配置校验、存活/就绪健康检查、PostgreSQL 异步探针和 Alembic 迁移基线。
- 已完成 `.env.example`、`.gitignore` 和仅包含前端/API 的 Render Blueprint；未创建云端资源。
- 自动化测试：通过 15，失败 0（前端 5、后端 10）。
- 工程验收：通过 12，失败 0；包含构建、类型、格式、迁移空跑、密钥、依赖、运行态和浏览器检查。
- 阶段 2 已完成 11 张业务表的 SQLAlchemy 模型、状态词汇、复合外键、约束和索引。
- 已新增有上限的应用连接池，并将应用 `DATABASE_URL` 与迁移 `MIGRATION_DATABASE_URL` 分离。
- 已新增 Alembic `20260713_0002` 迁移；Alembic 保持唯一迁移事实源。
- Bug Review 后补齐 `profiles → auth.users` 外键、JSONB 结构约束、自动更新时间、历史记录防改写和 Rubric 分数上限校验。
- 已为 11 张 `public` 业务表启用无策略 RLS，普通 API 角色默认拒绝；具体隔离策略留到阶段 4。
- 已强制远程连接使用 SSL，生产应用固定 Supavisor session pooler 5432，迁移固定 Supabase direct 地址。
- 真实验收强制使用独立 `TEST_MIGRATION_DATABASE_URL`、匹配的 project ref 和固定确认值，并拒绝当前部署迁移项目。
- 真实验收覆盖升级、回退、重建、系统目录、RLS 普通角色拒绝和非法写入；显式选择时缺配置会失败。
- 阶段 2 后端普通自动化测试：通过 27，失败 0；破坏性真实数据库测试默认排除 3。
- 前端回归测试：通过 5，失败 0；Lint、类型检查和生产构建通过。
- 真实 Supabase PostgreSQL 验收尚未执行，阶段 2 保持进行中。

下一步：取得独立 Supabase 测试项目、测试库地址、project ref 和两个 Auth 测试用户后，经用户确认执行真实迁移和约束验收。
