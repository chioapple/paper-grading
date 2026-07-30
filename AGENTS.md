# Paper Grading 项目代理规则

本文件作用于当前项目及全部子目录。项目内的新对话开始工作前，必须先读取本文件和 `CONTEXT.md`；复杂任务再按需读取 `README.md`、`ARCHITECTURE.md`、`docs/DEVELOPMENT_PLAN.md`、`task_plan.md`、`progress.md`、`findings.md` 与 `lessons.md`。

## Skill 自动路由

1. 每次收到开发任务后，先根据任务内容检索当前会话实际可用的 skills 和插件能力，并自动选择最少且足够的组合，不等待用户点名。
2. 选中 skill 后，必须完整读取对应 `SKILL.md` 并严格执行；缓存目录里存在但当前会话未暴露的 skill，不得当成可用能力。
3. 日常开发不需要在每次回复中重复列出使用了哪些 skills。只有以下情况才说明：
   - 用户主动询问；
   - skill 或插件不可用、发生冲突或导致任务暂停；
   - 上级系统、开发者或 skill 自身规则明确要求披露；
   - skill 对实现方案造成了重要改变，需要用户知道。
4. 不为了使用 skill 而使用 skill；与任务无关的能力必须跳过。
5. 本地 skill 根目录是 `/Users/a1-6/.codex/skills` 和 `/Users/a1-6/.agents/skills`。`.codex/plugins/cache` 只是插件缓存，不能据此判断当前可调用。

## 当前项目路由表

| 开发任务 | 优先使用的 skill / 插件 | 使用位置 |
|---|---|---|
| React、Vite、TypeScript 页面与组件 | `build-web-apps:frontend-app-builder`、`build-web-apps:react-best-practices` | 阶段 1、3、6、11 |
| 前端调试与视觉检查 | `build-web-apps:frontend-testing-debugging`、`browser`、`playwright` | 阶段 3、11、14 |
| PostgreSQL、索引和查询设计 | `build-web-apps:supabase-postgres-best-practices` | 阶段 2、4 |
| 测试先行开发 | `tdd` | Rubric、权限、评分契约、任务幂等和配额规则 |
| Bug、测试失败和性能回归 | `diagnose` | 全阶段，重点是阶段 10、14 |
| DOCX 输入与解析验证 | `documents` 或 `doc` | 阶段 7 |
| PDF 输入与解析验证 | `pdf` | 阶段 7 |
| Excel 导出与内容核验 | `spreadsheets` | 阶段 12 |
| OpenAI 接口、Key 和错误排查 | `openai-docs`、`openai-developers` | 阶段 5、8、9；仅代表 OpenAI |
| 教师复核工作台体验检查 | `product-design:audit` | 阶段 11 |
| 评分质量校准和结果验证 | `data-analytics` 相关 skills | 上线前质量校准 |
| GitHub PR、评审和 CI | `github` 相关 skills | 阶段 14及后续维护 |
| 任务拆分、缺陷管理和交接 | `to-issues`、`triage`、`handoff` | 全开发周期 |
| 状态机或界面方案验证 | `prototype` | 阶段 6、10、11之前 |
| 模块边界与耦合复查 | `improve-codebase-architecture` | 核心模块形成后 |

## 使用边界

- `shadcn` 只有在项目明确采用 shadcn/ui 后才能使用，不能因 skill 存在而擅自增加依赖。
- `openai-docs` 和 `openai-developers` 不能替代 DeepSeek、Kimi、GLM、Anthropic、Gemini 的官方文档和真实测试。
- 本项目个人非商业部署使用 `sites` 托管前端；FastAPI、Redis 和三个 Worker 运行在
  用户常开 Mac，Tailscale Funnel 提供 HTTPS，`launchd` 管理进程。Render 配置已退出
  当前方案。
- 禁止使用 `using-git-worktrees` 或擅自创建 worktree。
- 项目明确采用可审计的批量评分流水线，不使用 Agents SDK 或开放式自治智能体架构。
- `superpowers` 和 `codex-security` 即使配置为启用，也必须先确认当前会话实际暴露对应 skill 后才能调用。
- 当前未找到 `planning-with-files`、`gsd-method-guide` 和 OpenSpec 时，必须明确按不可用处理，不得假装已执行这些流程。

## 完成要求

每次改动后执行 Bug Review 和第一性原理复查，运行与风险相称的测试，并按项目现有规则更新 `CONTEXT.md`；用户纠正形成的新规则写入 `lessons.md`。
