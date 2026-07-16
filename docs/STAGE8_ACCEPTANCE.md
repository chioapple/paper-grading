# 阶段 8 验收：评分契约与提示词

## 当前状态

- 阶段 8 本地实现已完成：统一评分请求、严格模型输出、逐字证据、确定性总分、提示词信任边界、唯一一次纠正、四类审计快照和迁移 `20260716_0010` 均已落地。
- 后端自动化测试通过 237、失败 0；6 项真实 PostgreSQL 测试按配置排除。Ruff、格式和 mypy 已通过。
- 用户已确认本文件全部操作结果与预期一致：迁移回放、版本、新列、约束、函数权限和两张评分表行数均正确。阶段 8 已完成。

## Supabase 操作边界

本阶段不创建、邀请、修改或删除 Supabase User/Auth 用户；不新建或修改 Storage 桶、Policy、MIME、Key 或对象。唯一外部操作是把独立测试项目的 PostgreSQL 从 `20260716_0009` 迁移到 `20260716_0010` 并核验。

不要把数据库地址、密码、Token、Secret Key 或签名 URL 发到聊天中。

## 一、迁移前只读检查

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

- 版本是 `20260716_0009`；
- `grading_jobs = 0`；
- `grading_attempts = 0`。

任一条件不满足就停止，不删除或修改现有记录，并把不含敏感信息的结果返回给 Codex。

## 二、执行真实迁移回放

确认第一步全部满足后，在项目根目录执行：

```bash
cd '/Users/a1-6/Documents/Paper Grading'
set -a
source .env.stage2-test
set +a
./.venv/bin/pytest -m postgres backend/tests/test_stage8_postgres_contract.py -q
```

该测试只使用 `.env.stage2-test` 中的 Supabase direct 测试库地址，按 `0009 → 0010 → 0009 → 0010` 回放迁移，最终停在 `0010`。它不会创建或删除 Auth 用户、Storage 对象、作业、论文或评分记录；若版本或两张评分表不为空，会在修改前直接失败。

## 三、迁移后只读检查

测试通过后，在同一 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and (
    (table_name = 'grading_jobs' and column_name in (
      'result_schema_version', 'result_schema_hash', 'rubric_hash'
    ))
    or (table_name = 'grading_attempts' and column_name = 'request_version')
  )
order by table_name, ordinal_position;

select constraint_record.conname,
       pg_get_constraintdef(constraint_record.oid) as definition
from pg_catalog.pg_constraint as constraint_record
where constraint_record.conname in (
  'grading_jobs_snapshot_check',
  'grading_attempts_request_check'
)
order by constraint_record.conname;

select function_record.proname,
       function_record.proconfig,
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
  and function_record.proname in (
    'paper_grading_protect_job_snapshot',
    'paper_grading_protect_attempt_history'
  )
order by function_record.proname;

select 'grading_jobs' as table_name, count(*) as row_count
from public.grading_jobs
union all
select 'grading_attempts' as table_name, count(*) as row_count
from public.grading_attempts;
```

预期结果：

- 版本为 `20260716_0010`；
- 新增 4 列且全部 `is_nullable = NO`；
- 两个约束分别包含 Schema/Rubric 哈希和请求版本检查；
- 两个函数的 `proconfig` 都是 `search_path=""`；四个执行权限列全部为 `false`；
- 两张评分表仍为 0 行。

## 四、验收结果

- 迁移前版本为 `20260716_0009`，`grading_jobs` 和 `grading_attempts` 均为 0 行。
- `0009 → 0010 → 0009 → 0010` 真实迁移回放通过，最终版本为 `20260716_0010`。
- 新增 4 列均为非空；两个约束包含预期的 Schema、Rubric 哈希和请求版本检查。
- 两个保护函数均固定空 `search_path`，`PUBLIC`、`anon`、`authenticated`、`service_role` 均不可直接执行。
- 迁移回放后两张评分表仍为 0 行，没有创建或删除 Auth 用户及 Storage 对象。

用户已确认以上结果全部正确。阶段 8 验收完成，下一阶段入口为阶段 9“模型 API 适配器”。
