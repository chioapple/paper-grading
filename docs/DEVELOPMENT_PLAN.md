# 英文作文批改网站开发计划

## 1. 目标与范围

本项目建设一个面向教师的云端英文作文批改网站。总管理员创建教师账户并配置模型 API；教师创建作业、确认题目与评分标准、批量上传 DOCX/PDF、选择模型、复核 AI 建议并导出 Excel。

首版支持 DeepSeek、Kimi、智谱 GLM、OpenAI、Anthropic、Gemini，以及经过兼容测试的 OpenAI-compatible API。AI 只提供评分建议，最终成绩必须由教师确认。

首版不包含扫描件 OCR、查重、AI 写作检测、事实核验、学生门户和自动发布成绩。

## 2. 目标目录

```text
Paper Grading/
├── frontend/                  # React 教师网站
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI 接口
│   │   ├── auth/             # 登录验证与权限
│   │   ├── domain/           # Rubric、评分、任务数据结构
│   │   ├── providers/        # 模型 API 适配器
│   │   ├── parsing/          # DOCX/PDF 解析
│   │   ├── storage/          # Supabase Storage 文件操作
│   │   ├── workers/          # Celery 批量任务
│   │   └── export/           # Excel 导出
│   └── tests/
├── backend/migrations/       # Alembic 数据表、约束和 RLS 迁移
├── infra/                    # Render 与 Supabase Storage 配置
├── e2e/                      # 浏览器全流程测试
├── docs/
├── CONTEXT.md
├── README.md
├── ARCHITECTURE.md
├── task_plan.md
├── progress.md
└── findings.md
```

## 3. 执行原则

1. 按阶段执行，前一阶段验收失败时不进入下一阶段。
2. RLS 隔离通过前，不接入真实教师和论文。
3. 同一批次固定供应商、模型、参数、Rubric 和提示词版本。
4. 模型失败时不自动切换供应商，不使用正则或猜测补分。
5. AI 原结果、教师修改和重评记录都追加保存，不覆盖。
6. API Key、论文正文和模型完整响应不进入普通日志。
7. 自动删除真实文件前必须再次取得用户确认。
8. 每阶段完成后执行测试、Bug Review、第一性原理复查，并更新项目记录。

## 4. 详细开发步骤

### 阶段 1：项目与环境初始化

**Files**

- `frontend/`
- `backend/`
- `.env.example`
- `.gitignore`
- `infra/render.yaml`

**Action**

- 初始化 React、Vite、TypeScript、React Router 和 TanStack Query。
- 初始化 FastAPI、Pydantic、Alembic 和 pytest。
- 配置前后端代码检查、类型检查、测试和构建命令。
- 划分开发、测试和生产环境变量。
- 缺少必需配置时直接终止启动，不使用默认密钥或隐式配置。

**Verify**

- 前端可以构建并显示基础 App Shell。
- 后端 `/health/live` 与 `/health/ready` 返回正确状态。
- 数据库迁移可以空跑。
- 仓库扫描不存在真实密钥。

**Done**

- 前后端可启动，开发命令和目录结构固定。

### 阶段 2：Supabase 数据库

**Files**

- `backend/migrations/versions/*.py`
- `backend/app/domain/`
- `backend/app/db.py`

**Action**

- 建立 `profiles`、`provider_configs`、`assignments`、`rubric_versions`、`submissions`、`grading_jobs`、`grading_job_items`、`grading_attempts`、`teacher_reviews`、`audit_logs` 和 `exports`。
- `profiles.id` 直接引用 Supabase `auth.users.id`，不允许孤立账户资料。
- 统一使用 UUID 主键，教师数据包含 `owner_id`。
- 为角色、状态、分数范围和唯一性增加约束。
- 为所有外键、`owner_id` 和常用筛选字段建立索引。
- API/Worker 使用连接池；迁移任务使用直连。
- Alembic 是唯一迁移事实源，不再维护第二套 Supabase SQL 迁移。
- 审计日志、已完成模型评分和已确认教师复核由数据库阻止改写或删除。
- 阶段 2 立即为全部 `public` 业务表启用 RLS 且不建策略，使普通 API 角色默认拒绝；阶段 4 再增加隔离策略。
- 真实破坏性验收只允许使用独立 `TEST_MIGRATION_DATABASE_URL`，同时校验 project ref、固定确认值并拒绝复用部署迁移库。

**Verify**

- 全新数据库可以一次完成迁移。
- 迁移重复执行不会破坏数据。
- 非法角色、越界分数、孤立外键和重复版本写入失败。
- 已完成评分、已确认复核和审计日志的修改或删除失败。
- PostgreSQL 系统目录中的表、约束、索引、触发器和 RLS 状态符合模型。
- `pg_policies` 为空，切换到 `authenticated` 角色后不能读取或写入业务表。

**Done**

- 数据模型、约束和迁移流程可稳定复现。

### 阶段 3：登录、邀请与账户管理

**Files**

- `frontend/src/features/auth/`
- `frontend/src/routes/auth/`
- `frontend/src/routes/admin/users/`
- `backend/app/api/admin_users.py`
- `backend/app/auth/`

**Action**

- 关闭公开注册。
- 实现登录、退出、邀请回调、首次设密码和找回密码。
- 实现管理员邀请、停用、启用和查看教师账户。
- `service_role` 只允许后端管理员接口使用。
- 正式环境配置自有 SMTP。

**Verify**

- 未邀请邮箱不能注册。
- 教师不能调用管理员接口。
- 过期邀请链接明确报错。
- 停用账户的旧会话不能继续访问。
- 浏览器构建和 API 响应不包含服务端密钥。

**Done**

- 只有管理员邀请的教师可以登录网站。

### 阶段 4：RLS 与多用户隔离

**Files**

- `backend/migrations/versions/*_rls.py`
- `backend/app/auth/dependencies.py`
- `backend/tests/security/`

**Action**

- 为已启用 RLS 的业务表增加策略并强制执行。
- 教师策略同时检查 `owner_id = (select auth.uid())` 和账户状态。
- 前端仅使用 Supabase Auth 获取会话，所有业务请求进入 FastAPI。
- 每个教师数据库事务显式设置受限角色和 JWT claims，事务结束后清除，禁止连接池泄漏身份。
- 管理员操作和后台 Worker 才使用服务端权限。

**Verify**

- 教师 A 不能读取、修改或删除教师 B 的任何业务数据。
- 直接调用 Supabase Data API 也无法绕过隔离。
- 教师不能修改自己的角色和状态。
- 停用教师的旧 Token 被拒绝。

**Done**

- 数据隔离由数据库保证，而不是只靠前端隐藏。

### 阶段 5：管理员模型配置

**Files**

- `frontend/src/routes/admin/providers/`
- `backend/app/api/providers.py`
- `backend/app/providers/config.py`
- `backend/app/security/encryption.py`

**Action**

- 支持 DeepSeek、Kimi、智谱 GLM、OpenAI、Anthropic、Gemini 和通用 OpenAI-compatible API。
- 配置供应商名称、Base URL、加密 API Key、允许模型、默认模型、超时、并发和月度预算。
- 使用 AES-GCM 加密 API Key，主密钥只保存在部署环境变量。
- 自定义 Base URL 必须使用 HTTPS，解析后禁止访问内网、环回和链路本地地址。
- 管理员启用模型前必须完成连接测试。

**Verify**

- 接口只返回“已配置”，不返回真实 Key。
- 教师只能看到管理员允许的模型。
- SSRF、非法 URL 和错误密钥测试被明确拒绝。
- 日志和导出文件中不存在密钥。

**Done**

- 管理员可安全配置、测试、启停模型。

### 阶段 6：作业与结构化 Rubric

**Files**

- `frontend/src/features/assignments/`
- `frontend/src/features/rubrics/`
- `backend/app/api/assignments.py`
- `backend/app/api/rubrics.py`
- `backend/app/domain/rubric.py`

**Action**

- 实现作业列表、新建作业和作业状态。
- 教师可以粘贴或上传题目要求和评分标准。
- 使用管理员指定的默认模型将原始 Rubric 转换为结构化草稿。
- 教师核对后确认，确认版本冻结。
- Rubric 包含总分、步长、评分维度、分档描述、证据要求和统一扣分项。

**Verify**

- 维度 ID 和名称唯一。
- 维度分值之和等于总分。
- 分数符合步长和范围。
- 未确认 Rubric 时禁止开始批改。
- 修改已确认 Rubric 会创建新版本，不覆盖旧版本。

**Done**

- 教师可以完成“创建作业 → 确认评分标准”。

### 阶段 7：DOCX/PDF 上传、Supabase Storage 与解析

**Files**

- `frontend/src/features/submissions/`
- `backend/app/api/submissions.py`
- `backend/app/parsing/docx.py`
- `backend/app/parsing/pdf.py`
- `backend/app/parsing/normalize.py`
- `backend/app/storage/supabase.py`

**Action**

- 单批最多 100 篇，单文件默认不超过 20MB。
- 支持 DOCX 和可提取文字的 PDF，不支持扫描件 OCR。
- 验证真实 MIME、压缩结构、页数和文本规模。
- 使用 SHA-256 检测同一作业中的重复文件。
- DOCX 按段落和表格、PDF 按页和文本块生成 `block_id` 与定位信息。
- 原始文件、提取文本和模型原始响应存入私有 Supabase Storage；数据库只保存元数据和对象路径。
- 后端复用已有 Supabase Secret Key 调用 Storage API；浏览器不得获得 Secret Key 或对象路径。

**Verify**

- 损坏、加密、空白、扫描型和伪造扩展名文件明确失败。
- 101 篇上传被拒绝。
- 过期或越权签名 URL 无法读取文件。
- 相同文件不会被重复评分。

**Done**

- 合法论文可稳定转换为可定位的规范文本块。

### 阶段 8：评分契约与提示词

**Files**

- `backend/app/domain/grading.py`
- `backend/app/grading/prompt.py`
- `backend/app/grading/validator.py`
- `backend/app/grading/totals.py`

**Action**

- 定义统一 `GradeRequest` 与 `GradeResult`。
- 论文正文明确标记为不可信数据，不能改变系统规则。
- 模型返回每个维度的分数、理由、原文证据、修改建议和英文总体反馈。
- 证据必须引用 `block_id`，并能在规范文本中精确匹配。
- 最终总分只由后端确定性计算。
- 保存提示词、Schema、Rubric 和请求输入的版本与哈希。

**Verify**

- 缺少维度、重复维度、越界分数和无效证据全部被拒绝。
- “忽略评分标准”“给我满分”等论文内指令不能改变评分规则。
- Schema 首次失败后只允许使用同一模型纠正一次；再次失败进入 `needs_review`。

**Done**

- 任意供应商只能通过同一评分契约进入系统。

### 阶段 9：模型 API 适配器

**Files**

- `backend/app/providers/base.py`
- `backend/app/providers/deepseek.py`
- `backend/app/providers/kimi.py`
- `backend/app/providers/glm.py`
- `backend/app/providers/openai.py`
- `backend/app/providers/anthropic.py`
- `backend/app/providers/gemini.py`
- `backend/app/providers/openai_compatible.py`

**Action**

- 每个适配器实现凭证验证、模型能力、费用估算、评分、用量标准化和错误分类。
- 分别处理 JSON Schema/JSON Object、温度范围、思考参数、上下文、输出上限和 Token 统计差异。
- 模型名称由管理员配置，不写死在代码中。
- 通用兼容适配器优先使用 `/chat/completions`；是否支持 `/models` 通过能力配置决定。

**Verify**

- 所有供应商通过相同契约测试。
- 认证、限流、超时、拒答和截断错误被正确分类。
- 同一批次不会自动换模型。
- 每个正式启用模型完成真实 API 冒烟测试。

**Done**

- 国产与海外模型可以通过统一业务接口互换使用。

### 阶段 10：Celery 批量评分

**Files**

- `backend/app/workers/celery_app.py`
- `backend/app/workers/dispatcher.py`
- `backend/app/workers/tasks.py`
- `backend/app/api/grading_jobs.py`

**Action**

- 建立 `GradingJob → GradingJobItem → GradingAttempt`。
- 支持排队、运行、需复核、完成、失败和取消状态。
- 支持暂停、继续、取消和单篇重试。
- 每篇论文使用独立任务；重评生成新 attempt。
- 使用请求哈希和幂等键防止重复评分与重复计费。
- 429、网络和 5xx 只使用原模型重试。
- Redis 只作为队列，PostgreSQL 是任务状态来源。

**Verify**

- 单篇失败不阻塞其他论文。
- 重复投递和 Worker 重启不会重复计费。
- 100 篇任务无漏卷、重复和串卷。
- API 可通过 SSE 返回真实进度。

**Done**

- 批量任务可恢复、可追踪、可审计。

### 阶段 11：教师复核工作台

**Files**

- `frontend/src/features/jobs/`
- `frontend/src/features/reviews/`
- `frontend/src/routes/reviews/`
- `backend/app/api/reviews.py`

**Action**

- 左侧显示论文队列与状态，中间显示英文论文和证据高亮，右侧显示 Rubric 评分与反馈。
- 教师可以改分、修改英文反馈、调整证据、填写修改原因、使用原模型重评并确认成绩。
- AI 原结果和教师修改分别保存。
- 证据无效或解析异常的论文不能批量确认。

**Verify**

- 教师修改不会覆盖 AI 原结果。
- 证据点击能定位到正确文本块。
- 未确认结果不能标记为最终成绩。
- 页面支持键盘操作、清晰焦点和中英文界面切换。

**Done**

- 教师可完成完整人工复核并留下审计记录。

### 阶段 12：Excel 导出

**Files**

- `backend/app/api/exports.py`
- `backend/app/export/xlsx.py`
- `backend/tests/export/`

**Action**

- 生成 `Summary`、`Criteria`、`Feedback` 和 `Metadata` 工作表。
- 草稿导出允许待复核结果，但必须显示状态。
- 最终成绩导出遇到未确认结果时直接拒绝。
- 导出保存 Rubric、模型、批次和确认时间等审计信息。

**Verify**

- 总分与后端计算结果一致。
- 不漏卷、不重复、不串行错配。
- Excel 不包含 API Key、文件对象地址和不必要的内部错误。

**Done**

- 教师可以安全导出草稿或最终成绩。

### 阶段 13：配额、保留与备份

**Files**

- `backend/app/monitoring/quotas.py`
- `backend/app/maintenance/retention.py`
- `backend/app/maintenance/backup.py`
- `docs/runbooks/backup-and-restore.md`

**Action**

- 数据库 70% 提醒、85% 禁止创建新批次。
- Supabase Storage 达到可配置配额的 70% 提醒、85% 禁止继续上传；不得写死供应商套餐容量。
- 原始论文、提取文本和模型原始响应默认保留 30 天。
- 分数、反馈和审计元数据长期保留。
- 每日生成加密数据库逻辑备份到独立于主 Supabase 项目的目标，默认保留 7 天；目标在阶段 13 开始前确认。
- 阈值与保留时间全部可配置。

**Verify**

- 人工触发阈值会产生通知和硬限制。
- 数据恢复演练成功。
- 过期清理只影响符合规则的数据。

**Done**

- 存储增长和恢复流程可见、可控。

> 自动删除和备份清理在实际启用前必须再次取得用户确认。

### 阶段 14：测试、安全与部署

**Files**

- `backend/tests/`
- `frontend/src/**/*.test.tsx`
- `e2e/`
- `.github/workflows/ci.yml`
- `infra/render.yaml`
- `docs/runbooks/`

**Action**

- 单元测试覆盖 Rubric、总分、证据验证和错误分类。
- 集成测试覆盖 Supabase PostgreSQL、Auth、Storage、JWT、队列和 Excel。
- 权限测试覆盖两个教师交叉访问、账户停用和管理员边界。
- 模型契约测试覆盖所有启用供应商。
- 浏览器测试覆盖邀请、登录、创建作业、上传、批改、复核和导出。
- 安全测试覆盖 SSRF、恶意文件、提示注入、签名 URL 和密钥泄露。
- CI 依次执行格式、类型、单元、集成、迁移回放和密钥扫描。
- 部署顺序固定为：数据库迁移 → API → Redis → Worker → 前端 → 冒烟测试。

**Verify**

- 失败测试会阻止部署。
- 生产网站通过 HTTPS 访问，CORS 只允许正式前端域名。
- 健康检查、Worker 心跳、队列等待、失败率和容量告警可见。
- 回滚演练成功；备份按阶段 13 的已批准范围保持关闭，未来启用时再单独执行真实恢复演练。

**Done**

- 权限隔离、100 篇批量、安全和真实模型冒烟测试全部通过后才允许上线。

## 5. 质量校准

模型评分质量必须使用用户提供的真实题目、Rubric 和教师样本校准，不能预先使用虚构准确率。

上线前至少完成：

- 教师对同一批样本独立评分并形成基准。
- 比较各模型的总分差异、维度一致性、严重误判和重复稳定性。
- 检查姓名、代词和文件顺序变化是否影响评分。
- 将教师允许的误差和通过门槛记录为该课程的验收标准。
- 新模型、Rubric、提示词、解析器或 Schema 发生变化时重新运行基准集。

## 6. 阶段记录要求

每阶段完成后必须：

1. 更新 `task_plan.md` 状态。
2. 在 `progress.md` 记录测试通过/失败数量。
3. 在 `findings.md` 记录新决定、风险和阻塞。
4. 更新 `CONTEXT.md` 当前进度和下一步。
5. 发生模块、依赖、运行或部署方式变化时同步更新 `README.md` 与 `ARCHITECTURE.md`。
