# Paper Grading

## 项目简介

Paper Grading 是一个面向教师的云端英文作文批改网站。管理员创建教师账户并统一配置模型 API；教师创建作业、确认评分标准、批量上传论文、复核 AI 评分建议并导出 Excel。

阶段 1“项目与环境初始化”已完成。阶段 2 的数据模型和迁移已落地，正在等待独立真实 PostgreSQL 测试库验收。

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
| 文件存储 | Cloudflare R2 |
| 批量任务 | Celery + Redis |
| 网站部署 | Render Static Site + Web Service + Background Worker |
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
export DATABASE_POOL_SIZE=5
export DATABASE_POOL_TIMEOUT_SECONDS=5.0
./.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

启动前端：

```bash
npm --prefix frontend run dev -- --host 127.0.0.1
```

`/health/live` 用于进程存活检查；数据库不可用时 `/health/ready` 会明确返回 503。

## 部署

`infra/render.yaml` 已固定前端和 API 的真实构建、启动与健康检查命令，但自动部署关闭，尚未创建任何 Render 资源。Redis 和 Worker 在阶段 10 实现后再加入。

Render 免费 Web Service 不支持 pre-deploy command。每次手动部署 API 前，必须先在受控环境显式执行迁移；迁移失败就停止部署：

```bash
MIGRATION_DATABASE_URL='postgresql+asyncpg://...?ssl=require' .venv/bin/alembic -c backend/alembic.ini upgrade head
```

`MIGRATION_DATABASE_URL` 必须是启用 SSL 的 Supabase direct 直连地址，只在支持 IPv6 的受控迁移环境临时提供，不得注入 Render API，也不得回退使用 `DATABASE_URL`。

最终部署顺序仍为：数据库迁移 → API → Redis → Worker → 前端 → 冒烟测试。

## 测试

前端检查：

```bash
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
```

后端检查：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
../.venv/bin/pytest
```

PostgreSQL 迁移离线编译：

```bash
MIGRATION_DATABASE_URL=postgresql+asyncpg://localhost:5432/paper_grading .venv/bin/alembic -c backend/alembic.ini upgrade head --sql
```

真实 PostgreSQL 迁移和约束验收：

```bash
TEST_MIGRATION_DATABASE_URL='postgresql+asyncpg://...?ssl=require' \
TEST_SUPABASE_PROJECT_REF='...' \
TEST_DATABASE_RESET_CONFIRMATION='I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA' \
TEST_TEACHER_AUTH_USER_ID='...' \
TEST_OTHER_AUTH_USER_ID='...' \
.venv/bin/pytest -m postgres backend/tests/test_postgres_contract.py
```

测试地址、project ref 和两个测试用户必须来自同一个独立 Supabase 测试项目，两个用户尚未创建 `profile`。验收会执行升级、回退、再次升级并验证非法写入；代码会拒绝与当前 `MIGRATION_DATABASE_URL` 相同的项目。普通 `pytest` 不运行这组破坏性测试，显式执行 `-m postgres` 时缺少任一配置都会失败。

仓库与前端生产构建密钥扫描：

```bash
.venv/bin/detect-secrets scan --all-files --no-verify --exclude-files '(^|/)(\.venv|node_modules|\.git|\.playwright-cli|\.(mypy|pytest|ruff)_cache)/' .
```

## 搜索记录

### 2026-07-13

- [skills.sh](https://skills.sh/)：未发现可以直接替代本项目完整开发流程的单一技能；继续采用当前分阶段方案，避免引入来源不明的完整脚手架。
- [Supabase 开源仓库](https://github.com/supabase/supabase)：确认 PostgreSQL、Auth、Storage 和 RLS 组合适合账户与数据隔离，但业务批改仍保留在 FastAPI。
- [Supabase 数据库连接文档](https://supabase.com/docs/guides/database/connecting-to-postgres)：Render 运行时使用 IPv4 的 session pooler 5432；迁移使用 direct 地址，二者不共用配置。
- [OpenAI Python SDK](https://github.com/openai/openai-python)：确认异步客户端和流式接口可作为官方 OpenAI 适配器基础，不将其当作所有供应商完全兼容的证明。
- [Open WebUI provider 文档](https://github.com/open-webui/docs/blob/main/docs/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible.mdx)：参考其“协议兼容与供应商能力分离”思路；不采用其完整应用架构。
- GitHub 未找到同时满足“教师人工复核、严格 Rubric、批量论文、RLS、多供应商适配”的可直接复用完整项目，因此不复制现有仓库。

## 已完成

- [x] 确认产品和技术路线。
- [x] 确认国产与海外模型 API 范围。
- [x] 同步详细开发计划和项目记录。
- [x] 初始化前后端工程、环境配置和质量检查。
- [x] 实现并验证基础 App Shell 与健康检查。

## 进行中

- [-] 阶段 2 数据模型、复合外键、约束、索引、默认拒绝的 RLS、连接池和 Alembic 迁移已落地；待真实 PostgreSQL 验收。

## 待办

- [ ] 完成真实数据库验收、认证和 RLS 策略。
- [ ] 实现管理员账户与模型配置。
- [ ] 实现作业、Rubric、上传和文档解析。
- [ ] 实现模型适配器与批量评分。
- [ ] 实现教师复核和 Excel 导出。
- [ ] 完成安全、质量和生产部署验收。
