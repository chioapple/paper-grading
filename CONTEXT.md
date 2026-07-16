# CONTEXT

- 当前正在做什么：阶段 9 已完成并收口，下一步进入阶段 10“Celery 批量评分”。
- 上次停在哪：七类供应商统一适配器、本地质量门禁、DeepSeek 真实评分冒烟和 `STAGE9_ACCEPTANCE.md` 全部真实验收均已通过。
- 关键决定：供应商参数不能统一为 `temperature=0`；DeepSeek、Kimi、GLM、OpenAI、Anthropic、Gemini 按各自已确认能力发送参数。支持模型列表时只读验证 Key 和模型，不支持时使用合成内容执行一次计费冒烟。价格不硬编码，缺价格快照时费用为不可估算而不是 0。同一批次固定 `provider_config_id + config_version + model + capabilities + Schema`，失败不换供应商或模型。
- 当前下一步：按 `docs/DEVELOPMENT_PLAN.md` 开始阶段 10，建立可恢复、可追踪、可审计的 Celery 批量评分流水线。
- 重要边界：Supabase 操作仍只提供文字流程，由用户执行；聊天中出现的真实 API Key 视为泄露，必须撤销且不得写入项目。
- 当前版本：本地迁移头和 Supabase 测试项目均为 `20260716_0011`；后端通过 283、失败 0，前端最近通过 32、失败 0。
- 真实模型验收：DeepSeek `deepseek-v4-pro` 冒烟通过，首次调用即 `accepted`，用量、请求 ID 和响应 SHA-256 均完整。
- Supabase 验收：用户确认 `STAGE9_ACCEPTANCE.md` 全部步骤正确且符合预期，最终版本、字段、约束、函数权限和业务表行数均通过。
- 用户决定：用 Supabase Storage 替代 Cloudflare；所有 Supabase 操作仍只提供文字流程，由用户执行并通知结果后继续。
- 当前网络：网站关闭 VPN 运行，应用使用 Supavisor session pooler 5432；最终真实就绪检查已通过。
- 迁移网络诊断：根因是 Supabase Network Restrictions 只放行 IPv4；追加当前 IPv6 `/128` 后，`nc -6` 连接 direct 5432 成功，Alembic 随后无报错完成 `0008` 前向迁移。前后端是否启动与迁移无关。
