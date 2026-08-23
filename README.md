# Paper Grading

## 项目简介

Paper Grading 是一个面向教师的云端英文作文批改网站。管理员创建教师账户并统一配置模型 API；教师创建作业、确认评分标准、批量上传论文、复核 AI 评分建议并导出 Excel。

阶段 1 至阶段 13 已完成。阶段 14 第 6.2 节及之前已经完成，当前正在把部署切换为
Sites 前端、常开 Mac 后端、本机 Redis、Tailscale Funnel、`launchd` 和 UptimeRobot。
Sites 项目与前端适配已经完成，真实部署、告警和回滚仍在验收，因此阶段 14 保持进行中。
自动清理与备份保持关闭。评分提示词为 `grading-prompt.v3`，历史版本仍按原快照重建。

## 计划功能

- 管理员邀请、启用和停用教师账户。
- 教师数据隔离和数据库 RLS 权限保护。
- 题目要求与 Rubric 结构化、确认和版本管理。
- 单批最多 100 篇 DOCX/PDF 上传和预检。
- DeepSeek、Kimi、智谱 GLM、OpenAI、Anthropic、Gemini 和兼容 API。
- 异步批量评分、暂停、继续、取消和单篇重试。
- 原文证据定位、教师改分和审计记录。
- 草稿与最终成绩 Excel 导出。
- 中英文教师界面，默认英文学生反馈。

首版不做扫描件 OCR、查重、AI 写作检测、事实核验、学生门户和自动发布成绩。

## 技术架构

| 部分 | 计划技术 |
|---|---|
| 前端 | React + Vite + TypeScript |
| 后端 | FastAPI + Pydantic |
| 数据库和认证 | Supabase PostgreSQL + Auth |
| 文件存储 | Supabase Storage 私有桶 |
| 批量任务 | Celery + Redis |
| 网站部署 | Sites 前端 + 常开 Mac API/Worker + Tailscale Funnel |
| 模型调用 | 服务端 Provider Adapter |

调用关系和模块职责见 `ARCHITECTURE.md`。

## 本地运行

首次安装：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e './backend[dev]'
npm --prefix frontend ci
```

启动后端前必须显式提供环境和应用 PostgreSQL 地址。生产环境的 `DATABASE_URL` 使用 Supavisor session pooler 5432 并加 `?ssl=require`；迁移地址与应用地址分开：

```bash
export APP_ENV=development
export DATABASE_URL=postgresql+asyncpg://localhost:5432/paper_grading
export REDIS_URL=redis://127.0.0.1:6379/0
export DATABASE_POOL_SIZE=5
export DATABASE_POOL_TIMEOUT_SECONDS=5.0
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
export SUPABASE_SECRET_KEY=sb_secret_...
export SUPABASE_STORAGE_BUCKET=paper-grading-test
export SUPABASE_STORAGE_SIGNED_URL_TTL_SECONDS=60
export SUPABASE_STORAGE_TIMEOUT_SECONDS=60.0
export PROVIDER_MASTER_KEY=<32字节随机值的标准Base64>
export AUTH_INVITE_REDIRECT_URL=http://127.0.0.1:5173/auth/callback
export FRONTEND_ORIGIN=http://127.0.0.1:5173
./.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

本地 Redis 返回 `PONG` 后，再启动 Celery Worker：

```bash
redis-cli ping
cd backend
../.venv/bin/python -m app.workers.supervisor
```

启动器会建立两个独立进程：`grading@...` 只消费 `paper_grading.grading`，`maintenance@...`
只消费 `paper_grading.maintenance` 并运行 Beat。两者不共享执行槽；维护任务最多运行 25 秒，
不能再占住评分 Worker。

导出使用第三个独立消费者，必须在另一个终端启动；它只消费 `paper_grading.exports`，配置不需要供应商主密钥：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
unset PROVIDER_MASTER_KEY
cd backend
../.venv/bin/celery -A app.export.celery_app:celery_app worker --loglevel=INFO --concurrency=1 --queues=paper_grading.exports --hostname=exports@%h
```

默认 `ALLOW_OFFICIAL_PROVIDER_FAKE_IP=false`。仅当本地 VPN 把内置供应商官方域名映射到
`198.18.0.0/15`、用户已明确允许且只为本次真实验收时，才可在 Worker 终端临时设为 `true`；
停止 Worker 后必须立即恢复 `false`。该例外不适用于自定义 Base URL、真实内网地址或生产环境，
生产配置会在启动时拒绝它。

启动前端：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage7-local
set +a
export VITE_API_BASE_URL='http://127.0.0.1:8000'
export VITE_SUPABASE_URL="${SUPABASE_URL}"
export VITE_SUPABASE_PUBLISHABLE_KEY="${SUPABASE_PUBLISHABLE_KEY}"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

前端还需显式提供 `VITE_SUPABASE_URL`、`VITE_SUPABASE_PUBLISHABLE_KEY` 和 `VITE_API_BASE_URL`。`SUPABASE_SECRET_KEY`、`PROVIDER_MASTER_KEY` 和模型 API Key 只能存在于后端，不能使用 `VITE_` 前缀。生产 API 启动时会读取 Supabase Auth 公开设置；公开注册未关闭时直接停止启动。

可在本机生成 `PROVIDER_MASTER_KEY`，生成结果只保存到本机
`.env.stage14-production` 或本地开发环境：

```bash
./.venv/bin/python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

`/health/live` 用于进程存活检查；数据库不可用时 `/health/ready` 会明确返回 503。

## 部署

个人非商业部署不再使用 Render。`frontend/.openai/hosting.json` 绑定 Sites 项目；
`frontend/sites/worker.js` 提供 SPA 深层路径回退和安全响应头；`infra/local/` 管理本机
API、评分/维护 Worker、独立 Excel 导出 Worker、Tailscale、防休眠和 watchdog。
本机 Redis 只作为 broker，业务状态仍以 PostgreSQL 为准。

阶段 14 生产验收开始前，先在仓库根目录执行 `./infra/local/stage14-predeployment-gate.sh`；
它只做代码门禁检查，成功固定输出 `stage14_predeployment_gate=true`。

导出 Worker 也不接收通用 `DATABASE_URL`。`0017` 创建可登录、无初始密码的 `paper_grading_export_worker` 最小角色；部署者须在数据库侧单独设置强密码，并把该角色的 Supavisor session pooler 5432 地址仅注入 `EXPORT_DATABASE_URL`。该角色只能读冻结导出表并执行领取、完成和失败函数，不能读取供应商、作业、论文、评分 attempt 或教师复核来源表。

评分/维护 Worker 同样不能使用 API 数据库角色。`0019` 把既有 `paper_grading_worker` 最小角色改为可登录，并只增加私有 schema 使用权与两个 Storage 配额函数执行权，不增加表权限或设置密码；部署者须在数据库侧交互设置独立强密码，并把 `paper_grading_worker.<project-ref>` 的 Supavisor session pooler 5432 地址仅注入评分 Worker 的 `DATABASE_URL`。

每次发布 Mac 后端和 Sites 前端前，必须先在受控环境显式执行迁移；迁移失败就停止部署：

```bash
MIGRATION_DATABASE_URL='postgresql+asyncpg://...?ssl=require' .venv/bin/alembic -c backend/alembic.ini upgrade head
```

`MIGRATION_DATABASE_URL` 必须是启用 SSL 的 Supabase direct 直连地址，只在支持 IPv6 的受控迁移环境临时提供，不得注入 API 或 Worker 运行环境，也不得回退使用 `DATABASE_URL`。

阶段 3 的真实 Auth 验收步骤见 `docs/STAGE3_ACCEPTANCE.md`，阶段 4 的隔离验收见 `docs/STAGE4_ACCEPTANCE.md`，阶段 5 的模型配置迁移见 `docs/STAGE5_ACCEPTANCE.md`，阶段 6 的真实 Rubric 流程见 `docs/STAGE6_ACCEPTANCE.md`，阶段 7 的 Supabase Storage、迁移和上传验收见 `docs/STAGE7_ACCEPTANCE.md`，阶段 8 的评分快照迁移见 `docs/STAGE8_ACCEPTANCE.md`，阶段 10 的批量流水线验收见 `docs/STAGE10_ACCEPTANCE.md`，阶段 11 的教师复核验收见 `docs/STAGE11_ACCEPTANCE.md`，阶段 12 的迁移、权限、Storage、Excel 和浏览器步骤见 `docs/STAGE12_ACCEPTANCE.md`。阶段 13 验收见 `docs/STAGE13_ACCEPTANCE.md`，阶段 14 总验收见 `docs/STAGE14_ACCEPTANCE.md`；部署、回滚、冒烟、监控与恢复步骤统一位于 `docs/runbooks/`。外部写入、付费和破坏性操作仍只由用户明确授权后执行。

最终部署顺序固定为：数据库迁移 → API → Redis → 评分/维护 Worker → Excel 导出 Worker → 前端 → 冒烟测试。

## 测试

前端检查：

```bash
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run audit:dependencies
npm --prefix frontend run build
npm --prefix frontend run e2e:local
```

后端检查：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests scripts
../.venv/bin/pytest
```

PostgreSQL 迁移离线编译：

```bash
MIGRATION_DATABASE_URL=postgresql+asyncpg://localhost:5432/paper_grading .venv/bin/alembic -c backend/alembic.ini upgrade head --sql
```

真实 PostgreSQL 迁移和约束验收：

```bash
TEST_MIGRATION_DATABASE_URL='postgresql+asyncpg://...?ssl=require' \
TEST_DATABASE_URL='postgresql+asyncpg://postgres.<project-ref>:...@aws-0-<region>.pooler.supabase.com:5432/postgres?ssl=require' \
TEST_SUPABASE_PROJECT_REF='...' \
TEST_DATABASE_RESET_CONFIRMATION='I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA' \
TEST_TEACHER_AUTH_USER_ID='...' \
TEST_OTHER_AUTH_USER_ID='...' \
.venv/bin/pytest -m postgres backend/tests/test_postgres_contract.py
```

Direct 测试地址、Session Pooler 地址、project ref 和两个测试用户必须来自同一个独立 Supabase 测试项目。迁移回放只用 Direct；权限、RLS 和事务契约只用 Session Pooler 5432。代码会拒绝错误端口、错误项目用户名和与当前部署迁移库相同的项目。普通 `pytest` 不运行这组真实 PostgreSQL 测试，显式执行 `-m postgres` 时缺少任一配置都会失败。

仓库与前端生产构建密钥扫描：

```bash
git ls-files -co --exclude-standard -z |
  xargs -0 .venv/bin/detect-secrets-hook --baseline .secrets.baseline
find frontend/dist -type f -print0 |
  xargs -0 .venv/bin/detect-secrets-hook
```

`.secrets.baseline` 只包含已人工核对的测试占位符与界面文案哈希；新增候选、常见 Key/Token/Password 赋值或高熵内容都会失败。CI 不打印候选值。

## 搜索记录

### 2026-07-13

- [skills.sh](https://skills.sh/)：未发现可以直接替代本项目完整开发流程的单一技能；继续采用当前分阶段方案，避免引入来源不明的完整脚手架。
- [Supabase 开源仓库](https://github.com/supabase/supabase)：确认 PostgreSQL、Auth、Storage 和 RLS 组合适合账户与数据隔离，但业务批改仍保留在 FastAPI。
- [Supabase 数据库连接文档](https://supabase.com/docs/guides/database/connecting-to-postgres)：Mac 运行时使用 session pooler 5432；迁移使用 direct 地址，二者不共用配置。
- [OpenAI Python SDK](https://github.com/openai/openai-python)：确认异步客户端和流式接口可作为官方 OpenAI 适配器基础，不将其当作所有供应商完全兼容的证明。
- [Open WebUI provider 文档](https://github.com/open-webui/docs/blob/main/docs/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible.mdx)：参考其“协议兼容与供应商能力分离”思路；不采用其完整应用架构。
- GitHub 未找到同时满足“教师人工复核、严格 Rubric、批量论文、RLS、多供应商适配”的可直接复用完整项目，因此不复制现有仓库。

### 2026-07-14

- [Supabase 数据库函数文档](https://supabase.com/docs/guides/database/functions)：数据库函数固定空 `search_path`，内部触发函数撤销 `PUBLIC` 和 API 角色的直接执行权限。
- [Supabase API 安全文档](https://supabase.com/docs/guides/api/securing-your-api)：函数不受 RLS 保护，必须用最小 `EXECUTE` 权限单独控制。
- [Supabase 密码安全文档](https://supabase.com/docs/guides/auth/password-security)：泄露密码保护属于 Auth 配置且仅 Pro 及以上套餐可用，不作为阶段 2 数据库迁移门槛。
- [Supabase Auth 用户文档](https://supabase.com/docs/guides/auth/users)：邀请和用户管理使用服务端管理员接口，secret key 不进入浏览器。
- [Supabase Auth 开源仓库](https://github.com/supabase/auth)：`/settings` 可公开读取 `disable_signup`；生产 API 据此拒绝公开注册仍开启的项目。
- [Supabase API Key 文档](https://supabase.com/docs/guides/getting-started/api-keys)：浏览器只使用 publishable key，后端管理员操作使用 secret key；新 key 不是用户 JWT。
- [Supabase Authorization Header 文档](https://supabase.com/docs/guides/functions/auth-headers)：用户访问令牌放入 `Authorization`，publishable/secret key 属于 `apikey` 边界，不能当成用户身份。
### 2026-07-15

- [Supabase RLS 文档](https://supabase.com/docs/guides/database/postgres/row-level-security)：复杂账户状态检查使用私有 `SECURITY DEFINER` 函数，策略中的稳定函数包在 `select` 中。
- [Supabase API 安全文档](https://supabase.com/docs/guides/api/securing-your-api)：Data API 必须同时通过表权限和 RLS；阶段 4 对 `anon/authenticated` 撤销业务表权限。
- [Supabase Postgres Roles](https://supabase.com/docs/guides/database/postgres/roles)：教师业务使用自建 `NOLOGIN/NOBYPASSRLS` 角色，不复用浏览器的 `authenticated` 角色。
- [Supabase 数据库连接文档](https://supabase.com/docs/guides/database/connecting-to-postgres)：持久后端继续使用 Supavisor session pooler 5432，事务级角色和 claims 不依赖连接碰巧清理。
- [DeepSeek API 文档](https://api-docs.deepseek.com/)：内置 DeepSeek Base URL 使用 `https://api.deepseek.com`；模型名称不写死，由连接测试读取当前模型列表并核验管理员默认模型。
- [DeepSeek Models API](https://api-docs.deepseek.com/api/list-models)：连接测试使用只读模型列表接口验证 Key 和默认模型，不发送论文内容。

### 2026-07-16

- [Supabase Storage 权限文档](https://supabase.com/docs/guides/storage/security/access-control)：服务端 secret key 可绕过 Storage RLS；浏览器不持有该 key，下载仍先经 FastAPI 归属检查再签发短时 URL。
- [Supabase Storage 标准上传文档](https://supabase.com/docs/guides/storage/uploads/standard-uploads)：阶段 7 使用服务端流式标准上传和确定性对象路径；单文件继续限制为 20MB。
- [DeepSeek 模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)：`deepseek-v4-pro` 使用 1M 上下文、最大 384K 输出并支持 JSON Output；价格必须保存为可更新快照。
- [Kimi Chat API](https://platform.kimi.com/docs/api/chat)：Kimi 使用独立输出上限、思考和温度规则，不能复用全局 `temperature=0`。
- [GLM 对话补全](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8)：GLM 使用 `do_sample=false` 固定采样；未找到官方 Models API 契约时不宣称支持模型列表。
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)：官方 OpenAI 适配器使用 Responses 与严格 JSON Schema，不复用通用兼容协议。
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)：Anthropic 使用独立认证、结构化输出、停止原因和缓存用量字段。
- [Gemini GenerateContent](https://ai.google.dev/api/generate-content)：Gemini 使用独立 Schema、思考用量、拒答和截断信号，保持默认采样参数。
- [Tailscale Funnel 文档](https://tailscale.com/docs/features/tailscale-funnel)：个人非商业部署使用固定 `*.ts.net` HTTPS 入口，本机 API 不直接开放公网端口。
- [Sites 文档](https://learn.chatgpt.com/docs/sites)：前端通过 Sites 保存版本并部署，运行时密钥不写入 `.openai/hosting.json`。

## 已完成

- [x] 确认产品和技术路线。
- [x] 确认国产与海外模型 API 范围。
- [x] 同步详细开发计划和项目记录。
- [x] 初始化前后端工程、环境配置和质量检查。
- [x] 实现并验证基础 App Shell 与健康检查。
- [x] 完成 Supabase 数据模型、约束、索引、默认拒绝 RLS、迁移回放和真实破坏性验收。
- [x] 完成阶段 3 前后端本地实现、自动化测试和桌面/手机浏览器验收。
- [x] 完成阶段 3 真实 Supabase 与账户行为验收。
- [x] 完成阶段 4 RLS、教师受限事务和本地安全测试。
- [x] 完成阶段 4 真实 Supabase 隔离、旧 Token、邀请回归和 Advisors 验收。
- [x] 完成阶段 5 本地供应商配置、Key 加密、连接测试、权限接口、管理页面和浏览器验收。
- [x] 完成阶段 5 Supabase 前向迁移、Session pooler 真实连接和替代 DeepSeek Key 启用验收。
- [x] 完成关闭梯子后的阶段 5 最终数据库就绪复验。
- [x] 完成阶段 6 数据库迁移、本地作业/Rubric API、严格模型结构化调用和前端流程。
- [x] 完成阶段 6 真实 Supabase/DeepSeek 功能验收并收口。
- [x] 完成阶段 7 本地文件预检、DOCX/PDF 解析、私有 Supabase Storage 边界、论文 API、上传页面和自动化门禁。
- [x] 完成阶段 7 真实 Supabase Storage、数据库迁移、上传、失败重试、并发去重和跨教师验收。
- [x] 完成阶段 8 本地评分契约、提示词信任边界、证据校验、后端总分、唯一纠正和审计快照。
- [x] 完成阶段 8 真实 Supabase `0010` 迁移回放、字段、约束和函数权限验收。
- [x] 完成阶段 9 七类供应商适配器、能力/费用/用量契约、安全 HTTP 传输、错误分类和本地质量门禁。
- [x] 完成阶段 9 DeepSeek 真实评分冒烟及 `STAGE9_ACCEPTANCE.md` 全部验收。
- [x] 完成阶段 10 本地批次 API、Celery Worker、幂等状态机、SSE、审计持久化和自动化门禁。
- [x] 完成阶段 10 `0014` 延迟完整性触发器回归和真实批次行为验收。
- [x] 完成阶段 11 本地复核 API、原子确认迁移、教师工作台、自动化和替身浏览器检查。
- [x] 完成阶段 11 真实 Supabase、双教师、真实论文和浏览器验收。
- [x] 完成阶段 12 Excel 导出本地实现、独立 Worker、四工作表、前端流程和自动化门禁。
- [x] 完成阶段 12 真实 Supabase、Storage、Excel 和浏览器验收。
- [x] 完成阶段 13 配额、保留与备份安全基础及真实配额验收。
- [x] 确认阶段 13 自动清理和备份保持关闭，后续启用时单独验收。
- [x] 完成阶段 14 第 6.2 节及之前验收、Sites 前端适配和本机部署脚本。

## 待办

- [ ] 完成阶段 14 真实外部验收。
- [ ] 完成质量校准和生产上线验收。
