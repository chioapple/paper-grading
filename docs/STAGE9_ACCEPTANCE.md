# 阶段 9 验收：模型 API 适配器

## 当前状态

- 本地实现已完成：DeepSeek、Kimi、GLM、OpenAI、Anthropic、Gemini 和 OpenAI-compatible 均通过统一评分接口。
- 统一契约已覆盖精确配置版本、模型能力、规范 Schema、输出上限、原始响应哈希、Token 用量、价格快照和稳定错误码。
- 凭证验证遵循显式能力快照：支持模型列表时只读核验模型；不支持时使用合成内容执行一次计费冒烟，不上传真实论文。
- 不自动换供应商、不自动换模型、不自动降级结构化输出；首次结构失败只允许使用同一快照纠正一次。
- 本地后端测试通过 283、失败 0；真实 PostgreSQL 测试按配置排除。Ruff、格式和 mypy 已通过。
- DeepSeek 真实评分冒烟已由用户执行并通过：`status=accepted`、`provider=deepseek`、`model=deepseek-v4-pro`、`attempt_count=1`，请求 ID、Token 用量和 64 位响应哈希均完整。
- Supabase 迁移前只读检查已由用户确认通过：当前版本为 `20260716_0010`，`grading_jobs` 和 `grading_attempts` 均为 0 行。
- 用户已确认本文件全部步骤正确且符合预期；阶段 9 验收完成。

## Supabase 操作边界

Codex 不执行以下 Supabase 操作。请用户按顺序执行并只回传不含密码、Token、Secret Key、签名 URL、论文正文或模型原始响应的结果。

本阶段不创建、邀请、修改或删除 Auth 用户，不修改 Storage 桶、Policy、对象或 Key。唯一 Supabase 操作是把独立测试项目从 `20260716_0010` 回放迁移到 `20260716_0011`。

## 一、迁移前只读检查

验收结果：已通过。用户确认版本和两张评分表行数均与本节预期一致。

在独立 Supabase 测试项目的 SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select 'grading_jobs' as table_name, count(*) as row_count
from public.grading_jobs
union all
select 'grading_attempts' as table_name, count(*) as row_count
from public.grading_attempts;
```

必须同时满足：

- 版本是 `20260716_0010`；
- `grading_jobs = 0`；
- `grading_attempts = 0`。

任一条件不满足就停止，不删除或修改现有记录，并把不含敏感信息的结果返回给 Codex。

## 二、执行真实迁移回放

验收结果：已通过。用户确认真实迁移结果符合本节预期。

第一步全部满足后，在项目根目录执行：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage2-test
set +a
./.venv/bin/pytest -m postgres backend/tests/test_stage9_postgres_contract.py -q
```

该测试只使用 `.env.stage2-test` 中的 Supabase direct 测试库地址，按 `0010 → 0011 → 0010 → 0011` 回放，最终停在 `0011`。它不会创建或删除 Auth 用户、Storage 对象、作业、论文或评分记录；若版本或两张评分表不为空，会在修改前直接失败。

## 三、迁移后只读检查

验收结果：已通过。用户确认最终版本、字段、约束、函数权限和业务表行数均符合本节预期。

测试通过后，在同一 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and (
    (table_name = 'grading_jobs' and column_name in (
      'provider_config_version', 'result_schema'
    ))
    or (table_name = 'grading_attempts'
        and column_name = 'raw_response_sha256')
  )
order by table_name, ordinal_position;

select constraint_record.conname,
       pg_get_constraintdef(constraint_record.oid) as definition
from pg_catalog.pg_constraint as constraint_record
where constraint_record.conname in (
  'grading_jobs_snapshot_check',
  'grading_attempts_raw_response_check'
)
order by constraint_record.conname;

select function_record.proconfig,
       position('NEW.provider_config_version' in
         pg_get_functiondef(function_record.oid)) > 0
         as protects_provider_config_version,
       position('NEW.result_schema' in
         pg_get_functiondef(function_record.oid)) > 0
         as protects_result_schema,
       exists (
         select 1
         from pg_catalog.aclexplode(
           coalesce(
             function_record.proacl,
             pg_catalog.acldefault('f', function_record.proowner)
           )
         ) as privilege
         where privilege.grantee = 0
           and privilege.privilege_type = 'EXECUTE'
       ) as public_can_execute,
       has_function_privilege('anon', function_record.oid, 'execute')
         as anon_can_execute,
       has_function_privilege('authenticated', function_record.oid, 'execute')
         as authenticated_can_execute,
       has_function_privilege('service_role', function_record.oid, 'execute')
         as service_role_can_execute
from pg_catalog.pg_proc as function_record
join pg_catalog.pg_namespace as namespace
  on namespace.oid = function_record.pronamespace
where namespace.nspname = 'public'
  and function_record.proname = 'paper_grading_protect_job_snapshot';

select 'grading_jobs' as table_name, count(*) as row_count
from public.grading_jobs
union all
select 'grading_attempts' as table_name, count(*) as row_count
from public.grading_attempts;
```

预期结果：

- 版本为 `20260716_0011`；
- 新增 3 列：两个 `grading_jobs` 列非空，`raw_response_sha256` 可空；
- 作业约束包含 `provider_config_version > 0` 和 `jsonb_typeof(result_schema) = 'object'`；
- 原始响应约束要求对象路径与 32 字节 SHA-256 同时为空或同时存在；
- 保护函数固定空 `search_path`，保护两个新作业快照字段，四类执行权限均为 `false`；
- 两张评分表仍为 0 行。

## 四、DeepSeek 真实评分冒烟

验收结果：已通过。用户提供的安全摘要满足本节全部要求，未在聊天中暴露 API Key 或模型原始正文。

该步骤不读取或修改 Supabase。脚本只使用交互输入的 DeepSeek Key，不回显、不保存，也不输出模型原始正文。

执行：

```bash
cd '/Users/a1-6/Documents/Paper Grading/backend'
../.venv/bin/python scripts/stage9_deepseek_smoke.py
```

当前已启用模型按 DeepSeek 官方资料填写：

- 模型 ID：`deepseek-v4-pro`；
- 上下文 Token 上限：`1000000`；
- 模型输出 Token 上限：`384000`；
- 本次调用输出 Token 上限：`4096`。

API Key 只在终端交互提示中输入，不要写进命令、文件或聊天。成功时脚本只输出安全摘要，必须满足：

- `status = accepted`；
- `provider = deepseek`；
- `model` 为供应商实际返回模型；
- `attempt_count` 为 `1` 或唯一纠正后的 `2`；
- `raw_response_sha256` 为 64 位十六进制字符串。

若失败，只把安全摘要中的 `code` 或 `message` 返回给 Codex，不要发送 Key、原始响应或请求正文。

## 五、验收收口

第二、三、四部分均已由用户确认符合预期。阶段 9 已完成，下一步进入阶段 10。
