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

## 第一性原理结论

- 本项目核心不是开放式自治智能体，而是可审计的批量评分流水线。
- 模型只负责分项判断、理由、证据和建议；最终总分由后端计算。
- “兼容 OpenAI API”不代表所有供应商参数、模型列表和结构化输出能力相同，因此保留独立适配器。
- 免费云资源只能在额度内保持零成本，不能承诺无限用户和无限历史数据永久免费。
- 论文正文不能直接存入关系数据库，否则免费容量很快耗尽。

## 当前风险

- Supabase Free 可能因低活跃暂停，不适合承诺教学级可用性。
- Render 免费 Web 会休眠，Background Worker 需要付费实例。
- Supabase 默认 SMTP 不适合正式邀请教师，需要自有 SMTP。
- 不同模型评分稳定性必须使用真实 Rubric 和教师样本校准。
- 自动删除涉及真实论文文件，启用前需要再次取得用户确认。

## 当前阻塞

- 阶段 1 没有未解决阻塞。
- 尚未提供正式产品域名、Supabase、R2、Render、SMTP 和模型供应商账户。
- 尚未提供用于质量校准的真实题目、Rubric 和教师评分样本。
