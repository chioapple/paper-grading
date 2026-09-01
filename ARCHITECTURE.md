# 系统架构

## 1. 总体调用关系

```mermaid
flowchart TD
    A[总管理员] --> WEB[React 网站]
    T[教师] --> WEB
    WEB --> AUTH[Supabase Auth]
    WEB --> API[FastAPI]
    API --> DB[Supabase PostgreSQL]
    API --> STORAGE[Supabase Storage]
    API --> REDIS[Redis]
    REDIS --> WORKER[评分与维护 Worker]
    REDIS --> EXPORT_WORKER[独立导出 Worker]
    REDIS -. 待确认后启用 .-> RETENTION_WORKER[独立保留 Worker]
    REDIS -. 待确认后启用 .-> BACKUP_WORKER[独立备份 Worker]
    WORKER --> PROVIDERS[模型适配层]
    PROVIDERS --> CN[DeepSeek / Kimi / GLM]
    PROVIDERS --> GLOBAL[OpenAI / Anthropic / Gemini]
    PROVIDERS --> COMPAT[OpenAI-compatible API]
    WORKER --> DB
    WORKER --> STORAGE
    EXPORT_WORKER --> DB
    EXPORT_WORKER --> STORAGE
```

## 2. 模块职责

| 模块/目录 | 职责 |
|---|---|
| `frontend/` | 登录、管理、作业、上传、批次进度、复核和导出界面 |
| `frontend/src/app/` | App Shell、路由、双语文案、界面状态和设计变量 |
| `frontend/src/features/auth/` | Supabase 浏览器会话、FastAPI 当前账户校验和权限守卫 |
| `frontend/src/routes/auth/` | 登录、找回密码、邀请与恢复回调设密 |
| `frontend/src/routes/admin/users/` | 教师列表、邀请、停用和启用界面 |
| `frontend/src/routes/admin/providers/` | 供应商配置、连接测试、启停和 Key 不回显界面 |
| `frontend/src/features/assignments/` | 作业列表、创建、本地文本导入和阶段 6 前端流程测试 |
| `frontend/src/features/rubrics/` | Rubric 生成、确认、历史版本和结构化结果界面 |
| `frontend/src/features/submissions/` | 论文选择、客户端批次预检、逐文件上传、状态列表和短时下载入口 |
| `frontend/src/features/jobs/` | 教师自己的批次、进度、论文队列和批量确认入口 |
| `frontend/src/features/reviews/` | 桌面三栏/手机标签复核、逐字证据定位、精确分数预览和教师确认流程 |
| `backend/app/api/` | 对外 HTTP 接口、参数校验和权限入口 |
| `backend/app/config.py` | 显式校验运行环境、PostgreSQL 和 Redis 连接配置 |
| `backend/app/db.py` | 创建有上限的应用连接池和异步数据库会话 |
| `backend/app/readiness.py` | 执行有超时限制的数据库就绪探针 |
| `backend/app/auth/` | 在线验证 Supabase 会话、合并 profile 状态、管理邀请与唯一管理员引导 |
| `backend/app/domain/` | 11 张业务表、Rubric 和统一评分输入/输出的严格领域契约 |
| `backend/migrations/` | 唯一 Alembic 迁移版本链，负责表结构、约束、索引和 RLS |
| `backend/app/providers/` | 供应商安全配置、七类评分适配器、能力/价格快照、Schema 投影、用量标准化、SSRF 防护和模型目录 |
| `backend/app/rubrics/` | 作业/Rubric 仓储、业务状态机和严格模型结构化调用 |
| `backend/app/security/` | 使用版本化 AES-256-GCM 加解密供应商 API Key |
| `backend/app/parsing/` | 将 DOCX/PDF 转换为可定位的规范文本块 |
| `backend/app/storage/` | 私有 Supabase Storage 上传、读取、签名 URL 和对象生命周期 |
| `backend/app/submissions/` | 论文去重预留、RLS 仓储、解析状态机、失败重试和对象补偿 |
| `backend/app/grading/` | 构建版本化提示词、隔离不可信正文、校验证据并确定性计算总分 |
| `backend/scripts/` | 只用于受控验收的本地脚本；不承载生产请求逻辑 |
| `backend/app/workers/` | 批次 API 用例、PostgreSQL 状态仓库、Celery 分发、原子 claim、租约、重试和进度收口 |
| `backend/app/reviews/` | 教师复核安全投影、严格评分重验、RLS 仓储、草稿、原子确认和原模型重评编排 |
| `backend/app/export/` | 导出 API 用例、不可变快照、独立 Celery 队列、租约状态机和四工作表 Excel 生成 |
| `backend/app/monitoring/` | 数据库与 Storage 配额计算、事务门禁、字节预留和稳定错误状态 |
| `backend/app/maintenance/` | 默认关闭的保留状态机，以及目标无关的加密备份和恢复接口 |
| `frontend/src/features/exports/` | 草稿/最终导出选择、状态轮询、失败说明、历史列表和短时下载入口 |
| `infra/local/` | 常开 Mac 的 API、Worker、Tailscale、防休眠、本地健康 watchdog、release/current/shared 门禁脚本和 `launchd` 配置 |
| `frontend/sites/` | Sites 静态资源代理、SPA 深层路径回退和前端安全响应头 |
| `docs/design/` | App Shell 概念图和可执行视觉规范 |
| `e2e/` | 本地 `/mock` 与显式授权真实环境分离的管理员、教师浏览器全流程测试 |
| `.github/workflows/ci.yml` | 严格串行执行格式、类型、测试、迁移、构建、浏览器和密钥扫描，不执行部署 |
| `docs/runbooks/` | 部署、回滚、冒烟、监控、故障和备份恢复操作边界 |

## 3. 核心数据流

### 账户

1. 生产 API 启动时确认 Supabase 已关闭公开注册，否则拒绝启动。
2. 一次性命令发送首个管理员邀请，并把对应 profile 提升为唯一 `active admin`。
3. 管理员通过后端邀请教师；服务端 secret key 只存在于 FastAPI。
4. 数据库触发器只为带 `invited_at` 的 Auth 邀请建立 `teacher / invited` profile，普通 Auth 用户不会获得应用账户。
5. 教师从邮件回调设置密码，后端将 profile 幂等转换为 `active`。
6. 浏览器请求携带 JWT；FastAPI 每次在线验证会话并实时读取 profile。停用后，即使旧 JWT 尚未过期也会立即返回 403。
7. 当前账户 profile 用独立短会话实时读取并关闭；教师业务事务再写入服务端构造的 JWT claims，并临时切换到 `paper_grading_teacher_api`。

### 作业与评分标准

1. 教师创建作业并输入题目与原始 Rubric；阶段 6 的文本上传只在浏览器本地读取 UTF-8 `.txt/.md`。
2. 教师选择管理员已启用的供应商，系统固定使用该供应商的 `default_model` 将 Rubric 转换为结构化草稿，不按列表顺序猜选。
3. 教师确认后冻结 `rubric_version`。
4. 修改评分标准会创建新版本，不覆盖历史版本。
5. Rubric 分值以十进制字符串进入 JSON，由 Python 和 PostgreSQL 双重校验总分、步长、维度、连续分档、证据要求和统一扣分。
6. 数据库保证同一作业最多一个当前草稿和一个当前确认版本；批改任务只能引用已确认版本，修订草稿不会覆盖旧确认版本；切换确认版本前必须先把已就绪作业转回草稿。
7. 确认 Rubric 时，服务层在同一事务内核验供应商仍启用、连接测试仍匹配当前配置且模型等于管理员默认模型；数据库保存外键和历史快照，不把可变化的启用状态写成历史约束。

### 模型配置

1. 管理员提交供应商、Base URL、Key、允许模型、默认模型、超时、并发和预算。
2. 后端把 Key 与供应商 UUID 绑定后使用 AES-256-GCM 加密；API 只返回“已配置”状态。
3. 连接测试按精确模型能力执行：支持模型列表时只读核验 Key 和默认模型；未声明支持时用合成内容执行一次计费冒烟。自定义地址必须解析到公网，并把 TCP 连接固定到已校验 IP。本地开发可经显式开关只为内置官方域名临时允许 VPN 的 `198.18.0.0/15` fake-IP；生产、自定义地址和其他非公网地址始终拒绝。
4. 测试结果绑定当前 `config_version`；Base URL、Key、模型或超时变化时，数据库触发器自动清除测试并改回草稿。
5. 只有当前配置测试通过后才能启用；教师目录只返回已启用配置的允许模型。

### 论文批改

1. 教师一次选择最多 100 篇；前端最多并发 3 个单文件上传请求。
2. 后端流式预检真实格式和 20MB 上限，计算 SHA-256，并按作业去重。
3. 原文件写入私有 Supabase Storage；解析器生成带页码/段落和真实坐标的规范文本块，再写入版本化 JSON 对象。
4. 数据库只保存元数据、状态和服务端生成的对象路径；下载前先经过教师归属与 ready 状态检查，再签发短时 URL。
5. API 在教师 RLS 事务中锁定 ready 作业和确认 Rubric，校验 1–100 篇 ready 论文，保存不可变批次快照后再投递 Celery。
6. Redis 消息只包含 item UUID 和单调版本；真实评分进入 `paper_grading.grading`，周期补发与租约检查进入 `paper_grading.maintenance`。Supervisor 启动两个独立 Worker 进程分别消费两条队列，维护任务还有 25 秒硬超时，因此不会占用评分执行槽；PostgreSQL 才是任务状态和进度事实源。
7. Worker 先用专用 `NOLOGIN/NOBYPASSRLS` 角色原子 claim，再按批次保存的供应商配置版本、模型、能力、价格和 Schema 快照调用唯一适配器。
8. 重复消息或旧版本消息不能取得 claim；调用开始后 Worker 丢失或网络结果不明时进入 `needs_review`，不自动再次计费。
9. 只有明确未计费的 408、429 和 5xx 能按同一模型快照自动重试；首次结构失败只允许一次同快照纠正。
10. `grading-prompt.v3` 明确要求所有评分理由、扣分理由、修改建议和总体反馈使用英文，并把非英文 Rubric/作业文字翻译或释义后再写入叙述字段；模型结果还必须通过 Schema、英文脚本、维度、步长、扣分和逐字证据校验。提示词构建器保留 v1/v2/v3 的精确规则与哈希重建能力。后端计算 `max(0, 维度小计 - 固定扣分)` 并保存原始响应对象、哈希、用量和费用状态。
11. AI 成功结果仍进入 `needs_review`；阶段 11 教师确认后才生成 `completed` 和最终成绩版本。

### 教师复核

1. `/grading-jobs` 只列出当前教师自己的批次、论文名、进度和复核指针，不要求浏览器输入 UUID。
2. 详情从私有 Storage 读取归属已核验的规范文本，只投影 Rubric、文本块、AI 分项结果和当前教师草稿；对象路径、原始响应、哈希、请求 ID、Token 和费用不进入响应。
3. 教师输入重新通过阶段 8 的英文叙述、维度、步长、上限、扣分和逐字证据校验；总分由后端 Decimal 计算，浏览器只显示预览。
4. AI attempt 永不覆盖；草稿按 attempt 绑定并单调修订，新 attempt 会使旧草稿冲突。修改 AI 结果必须填写原因。
5. 教师无任务表更新和审计写权限。保存和确认仅通过固定空 `search_path` 的私有 `SECURITY DEFINER` 函数执行。
6. 单篇和批量确认在事务内重验归属、attempt、Rubric、论文状态和修订；批量全有或全无，重复确认返回同一结果。
7. 确认把论文从 `needs_review` 原子变为 `completed`；最后一篇确认时批次同时完成并写结束时间和只追加审计。confirmed review 不可修改、删除或再次重评。
8. `needs_review` 可能来自成功评分，也可能来自未知或失败调用。队列用 `review_available` 明确区分：成功 current-round attempt 才能进入详情；否则只允许经过费用确认的原模型重评，并继续复用批次固定快照。

### 导出

1. 教师针对一个明确评分批次选择草稿或最终导出；最终导出要求每篇都有 confirmed review。
2. 数据库函数在单一事务内核验归属和当前来源，并把批次信息及每篇 attempt/review/result 冻结到 `exports` 与 `export_items`。
3. API 只向独立 `paper_grading.exports` 队列发送 export ID；导出 Worker 不读取实时评分表，也不持有供应商主密钥。
4. Worker 用有时限的令牌原子领取，生成无公式、无外部链接的四工作表 Excel，私有 Storage 上传成功且文件哈希一致后才完成；连续软超时或三次进程丢失由数据库审计计数收口为明确失败，避免永久运行。
5. 教师下载前再次经过归属与 RLS 检查，API 只签发短时 URL 和安全文件名，不暴露对象路径或文件哈希。

## 4. 关键设计决定

### 可审计流水线，不使用开放式自治智能体

评分必须遵循固定输入、固定 Rubric、结构化输出和教师确认。开放式自治智能体会增加不可控工具调用和评分漂移，因此首版不采用。

### 模型只评分，后端算总分

模型只返回分项分数、理由、证据、建议和扣分是否适用；总分由后端确定性计算，最低为 0，并单独保留小计与扣分合计，避免算术错误和重复扣分。

### 供应商适配器与通用协议并存

DeepSeek、Kimi 和 GLM 虽提供兼容接口，但结构化输出、温度、思考参数、输出上限、用量和错误格式仍不同。七类供应商各保留独立入口；通用兼容适配器只按显式能力快照发参数。能力未知就失败，不按模型名猜测或自动降级。

### RLS 是最终数据隔离边界

前端隐藏和后端过滤不能替代数据库隔离。11 张公开业务表全部强制 RLS；`anon/authenticated` 没有业务表权限，教师无法用 Data API 绕过 FastAPI。FastAPI 在线验证 Token 和 active profile 后，在显式事务内写入最小 JWT claims，再 `SET LOCAL ROLE paper_grading_teacher_api`。私有安全函数只返回当前 active teacher 的 UUID，提交或回滚后角色与 claims 自动清除。

### PostgreSQL 保存状态，Supabase Storage 保存大对象

数据库只保存账户、元数据、精简评分和审计记录；论文、提取文本和原始模型响应进入私有 Supabase Storage，以控制 PostgreSQL 容量。数据库灾备不能与主数据库放在同一个 Supabase 项目，阶段 13 另定独立备份目标。

### Redis 只传消息，PostgreSQL 保存任务事实

Celery 可以重复投递或丢失消息，因此消息本身不能代表论文状态。每次供应商调用必须先取得 PostgreSQL 原子 claim；批次计数、暂停、继续、取消、重试、租约和 SSE 全部重新读取数据库。评分与维护使用独立队列并轮转消费；维护消息每 30 秒产生一次，25 秒内未开始即失效，避免数据库冷连接慢于调度周期时形成永久积压。Redis 不保存论文正文、供应商 Key 或模型快照。

Excel 导出使用独立 Celery 应用、队列、数据库登录角色和本机独立进程；进程只接收
`EXPORT_DATABASE_URL`，不持有通用 postgres 凭据。创建事务冻结模型参数、Rubric、
attempt/review 来源与逐篇结果；Worker 只读冻结表。同一快照的生成时间、工作簿属性和
ZIP 成员固定，因此重领可复用同一路径和 SHA-256。失租 Worker 只有在数据库仍接受其
令牌并先转为 failed 后，才可删除本次刚创建的同哈希对象。

### 迁移与应用连接严格分开

Alembic 是唯一迁移事实源，已经执行的迁移不原地改写。阶段 2 基线是 `20260713_0002`，安全收尾使用前向迁移 `20260714_0003`；阶段 3 使用 `0004`、`0005`，阶段 4 使用 `0006`，阶段 5 使用 `0007`，阶段 6 使用 `0008`，阶段 7 使用 `0009`，阶段 8 使用 `0010` 保存评分契约快照，阶段 9 使用 `0011` 锁定供应商配置版本、Schema 正文和原始响应哈希，阶段 10 使用 `0012` 建立批次状态、Worker 权限、租约、重试和完整 attempt 审计，`0013` 删除教师只读批次校验中的多余行锁，`0014` 分开处理两张触发表的延迟完整性记录字段；阶段 11 使用 `0015` 保存独立扣分与精确总分并建立最小权限原子复核函数，`0016` 保证部分确认时仍含排队或运行中论文的批次保持可调度；阶段 12 使用 `0017` 建立不可变导出快照、最小权限函数和租约状态机；阶段 13 使用 `0018` 建立默认关闭的配额、保留、备份和恢复审计基础；阶段 14 使用 `0019` 允许既有最小评分 Worker 角色登录并执行 Storage 配额预留/收口，不增加表权限，密码仍由部署者在仓库外设置。应用使用有上限的持久连接池；Mac 生产进程通过启用 SSL 的 Supavisor session pooler 5432 访问数据库。迁移只读取启用 SSL 的 direct 连接地址，且从支持 IPv6 的受控环境运行；不回退到应用连接池地址，也不把迁移凭据注入 API 或 Worker 环境。真实验收同样分离连接：`TEST_MIGRATION_DATABASE_URL` 只做 Alembic 回放，`TEST_DATABASE_URL` 使用同一测试项目的 Supavisor Session Pooler 5432 执行权限、RLS 和事务契约。

### 身份与历史记录由数据库兜底

`profiles.id` 必须引用 Supabase `auth.users.id`。首版账户只停用、不硬删除，因此该外键使用 `ON DELETE RESTRICT`。审计日志禁止更新和删除；模型评分只允许从运行中完成一次，完成后不可修改；教师复核草稿可以编辑，但确认后不可修改或删除。模型和教师分数上限必须与对应 Rubric 一致。

### 邀请制账户是双重边界

Supabase Auth 配置负责关闭注册入口，数据库触发器再用 `auth.users.invited_at` 限制 profile 创建。触发器只接受插入即受邀或 `invited_at` 首次从空变为有值两种事件，重复更新不会再次创建 profile。前端没有注册按钮不构成安全边界。生产启动检查、触发器和 FastAPI 的实时 profile 状态检查三层必须同时成立。

### 失败显式暴露

文档解析、模型结构、证据定位和权限检查失败时进入明确错误状态；不自动换模型、不猜测补分、不静默截断。

## 5. 安全边界

- API Key 由后端 AES-256-GCM 加密，随机 nonce 与供应商 UUID 绑定；浏览器和安全投影永远不可读取明文。
- 自定义 Base URL 限制为 HTTPS，拒绝凭据、查询、重定向和非公网地址，并固定已验证 IP 防止 DNS 重绑定。
- 论文内容视为不可信数据，不能修改系统评分指令。
- Supabase Storage 桶保持私有；Secret Key 只存在于后端，下载必须先通过 FastAPI 教师归属检查，再签发短时 URL。
- 管理员管理账户与系统，默认不提供论文正文读取接口。
- 未经教师确认的结果不能导出为最终成绩。
- 阶段 14 生产验收固定使用 `PROVIDER_CALLS_ENABLED=false`。API 不构造供应商连接测试器，
  评分任务与周期分发在数据库或外部网络访问前失败关闭；因此阶段 14 只能做无写入冒烟和
  既有数据只读核对，模型质量校准必须在阶段 14 之后另行授权。

## 6. 当前状态

阶段 1 至阶段 13 已完成。阶段 14 的本地实现、简易验收流程和系统性复查已经完成；
Tailscale 1.98 Funnel 配置读写、环境值安全转义、模型调用硬关闭和无外部写入的本地 watchdog
均有回归测试。前一候选已完成 Funnel、双 release、Sites 私有部署和页面检查；本轮需把免费
Keyword 监控修复形成新候选并取得精确 CI 8/8，再重做受 SHA 影响的 release/Sites 准备。
生产环境文件、前向迁移、`launchd`、实际免费邮件告警和双端回滚尚未执行。
阶段 14 只允许零新增费用、无模型调用的验收；自动清理、备份创建和备份清理继续关闭。
