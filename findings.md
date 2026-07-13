# 决定、发现与风险

## 已确认决定

- 产品是教师使用的云端网站，教师不需要本地部署。
- 首版只有一个总管理员，由管理员邀请和停用教师账户。
- 不开放公开注册。
- 单批最多 100 篇 DOCX 或可提取文字的 PDF。
- 教师网页支持中英文切换，学生反馈默认使用英文。
- AI 结果必须经教师确认后才能成为最终成绩。
- 管理员统一配置模型 API Key。
- 支持 DeepSeek、Kimi、智谱 GLM、OpenAI、Anthropic、Gemini 和经过测试的 OpenAI-compatible API。
- 数据库优先采用 Supabase PostgreSQL，论文文件采用 Cloudflare R2。
- 同一批次不自动切换模型。
- 后端只接受 `postgresql+asyncpg`，不使用 SQLite 代替 PostgreSQL。
- `/health/live` 只证明进程存活；`/health/ready` 必须实际检查数据库。
- Render 阶段 1 只声明前端 Static Site 与 API Web Service；Redis 和 Worker 留到阶段 10。
- Render 免费 Web Service 不支持 pre-deploy command；每次手动部署 API 前必须在受控环境显式执行数据库迁移，迁移失败就停止部署。
- Alembic 是唯一迁移事实源，不维护第二套 `supabase/migrations`，避免结构漂移。
- Render 运行时使用 Supavisor session pooler 5432；迁移使用独立 direct 地址，迁移配置不注入 API，也不回退到应用连接地址。
- 教师业务表使用 `owner_id` 与上级对象组成复合外键，从数据库层阻止跨教师、跨作业串联。
- 阶段 2 所有审计链外键均使用 `ON DELETE RESTRICT`；自动清理仍留到阶段 13。
- `profiles.id` 在阶段 2 直接引用 Supabase `auth.users.id`；阶段 3 只实现邀请、登录和账户管理流程。
- 审计日志禁止更新和删除；模型评分只允许从 `running` 完成一次；教师复核确认后禁止修改或删除。
- 模型评分上限由数据库对照批次 Rubric 校验，教师复核上限必须等于对应模型评分上限。
- JSONB 容器类型由数据库约束，不能依赖 Python 类型提示。
- 阶段 2 先为全部 `public` 业务表启用 RLS 且不建策略，使普通 API 角色默认拒绝；阶段 4 再增加策略并强制执行。
- 生产应用只接受启用 SSL 的 Supavisor session pooler 5432；远程迁移只接受启用 SSL 的 Supabase direct 地址。
- 真实数据库验收只读取独立 `TEST_MIGRATION_DATABASE_URL`，并校验 project ref、固定确认值及部署库差异；会回退并重建阶段 2 表。
- HTTP 携带的 JWT 不会自动进入 SQLAlchemy 连接；阶段 4 必须在每个事务显式设置受限角色和 JWT claims。
- 首版账户只停用、不硬删除，因此 `profiles → auth.users` 使用 `ON DELETE RESTRICT`。

## 第一性原理结论

- 本项目核心不是开放式自治智能体，而是可审计的批量评分流水线。
- 模型只负责分项判断、理由、证据和建议；最终总分由后端计算。
- “兼容 OpenAI API”不代表所有供应商参数、模型列表和结构化输出能力相同，因此保留独立适配器。
- 免费云资源只能在额度内保持零成本，不能承诺无限用户和无限历史数据永久免费。
- 论文正文不能直接存入关系数据库，否则免费容量很快耗尽。
- 迁移历史必须只有一个事实源；双份 SQL/Alembic 结构无法长期可靠同步。

## 当前风险

- Supabase Free 可能因低活跃暂停，不适合承诺教学级可用性。
- Render 免费 Web 会休眠，Background Worker 需要付费实例。
- Supabase 默认 SMTP 不适合正式邀请教师，需要自有 SMTP。
- 不同模型评分稳定性必须使用真实 Rubric 和教师样本校准。
- 自动删除涉及真实论文文件，启用前需要再次取得用户确认。
- 当前环境没有 PostgreSQL、Docker、Supabase CLI 或数据库连接，离线升级和回退通过不能替代真实 Supabase 验收。

## 当前阻塞

- 阶段 1 没有未解决阻塞。
- 阶段 2 本地实现已落地，但真实 PostgreSQL/Supabase 验收被独立测试库地址、project ref、破坏性操作确认及两个 Auth 测试用户阻塞。
- 尚未提供正式产品域名、Supabase、R2、Render、SMTP 和模型供应商账户。
- 尚未提供用于质量校准的真实题目、Rubric 和教师评分样本。
