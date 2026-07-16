# 阶段 6 验收记录

## 当前状态

- 阶段 6 数据库契约、作业/Rubric API、严格模型结构化调用和前端流程已在本地完成。
- 本地后端自动化测试通过 154、失败 0，前端回归测试通过 28、失败 0；真实 PostgreSQL 测试 5 项按配置排除。
- Supabase 前向迁移和迁移后只读核验均已通过：版本、列、约束、索引、触发器、函数安全、历史门禁、RLS、Policy 和业务行数全部符合预期。
- 真实 Supabase/DeepSeek 功能验收已通过：作业为 `ready`，v1 为 `superseded`，v2 为 `confirmed`，两版均保存 `deepseek-v4-pro`、供应商快照、结构化内容和确认时间。
- 用户确认其余计数与负向门禁结果均符合本文件预期；未确认 Rubric 的批改任务引用数为 `0`。阶段 6 已完成。

## 本次迁移内容

- 作业题目要求必须为非空文本。
- Rubric 保存生成时使用的供应商配置和管理员默认模型快照。
- 同一作业最多保留一个当前草稿和一个当前确认版本。
- 结构化 Rubric 必须满足严格字段、总分、步长、维度、分档、证据和统一扣分约束。
- 作业只有存在已确认 Rubric 时才能进入 `ready`。
- 批改任务只能引用已确认 Rubric，且作业必须处于 `ready`。
- 已就绪作业不能直接替代唯一的已确认 Rubric；切换版本时必须在同一事务内先把作业转回草稿，再完成旧版替代、新版确认和重新就绪。
- 新函数固定空 `search_path`；结构校验函数只额外授予教师受限角色执行权，触发函数不向 API 角色开放。

## Supabase 迁移记录（已由用户执行并通过）

以下操作只针对独立 Supabase 测试项目。不要在生产项目执行，不要使用应用的 Supavisor 连接；Alembic 只使用 `.env.stage2-test` 中的 direct `TEST_MIGRATION_DATABASE_URL`。

### 1. 迁移前只读检查

在 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select
  (select count(*) from public.assignments) as assignments,
  (select count(*) from public.rubric_versions) as rubric_versions,
  (select count(*) from public.grading_jobs) as grading_jobs;

select count(*) as blank_instructions
from public.assignments
where btrim(instructions) = '';

select assignment_id, status, count(*) as version_count
from public.rubric_versions
where status in ('draft', 'confirmed')
group by assignment_id, status
having count(*) > 1;

select count(*) as confirmed_without_generation_snapshot
from public.rubric_versions
where status in ('confirmed', 'superseded');

select count(*) as ready_without_confirmed_rubric
from public.assignments as assignment
where assignment.status = 'ready'
  and not exists (
    select 1
    from public.rubric_versions as rubric
    where rubric.assignment_id = assignment.id
      and rubric.owner_id = assignment.owner_id
      and rubric.status = 'confirmed'
  );

select count(*) as grading_jobs_with_unconfirmed_rubric
from public.grading_jobs as job
join public.rubric_versions as rubric
  on rubric.id = job.rubric_version_id
 and rubric.assignment_id = job.assignment_id
 and rubric.owner_id = job.owner_id
where rubric.status <> 'confirmed';
```

预期：

| 检查 | 预期 |
|---|---|
| 迁移版本 | `20260715_0007` |
| 空题目要求 | `0` |
| 重复当前版本 | 返回 0 行 |
| 已确认或已替代 Rubric | `0`；阶段 6 尚未创建真实 Rubric |
| ready 作业缺确认 Rubric | `0` |
| 批改任务引用未确认 Rubric | `0` |

任一结果不符合时停止，不要自行删除或修改数据，把完整结果发回当前任务。

### 2. 执行前向迁移

在项目根目录执行：

```bash
set -a
source .env.stage2-test
set +a
MIGRATION_DATABASE_URL="$TEST_MIGRATION_DATABASE_URL" \
  .venv/bin/alembic -c backend/alembic.ini upgrade 20260716_0008
```

命令必须无报错返回终端提示符。不要执行 `downgrade`。

### 3. 迁移后只读核验

在 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'rubric_versions'
  and column_name in ('provider_config_id', 'model')
order by column_name;

select conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in (
  'public.assignments'::regclass,
  'public.rubric_versions'::regclass
)
  and conname in (
    'assignments_instructions_check',
    'rubric_versions_provider_config_id_fkey',
    'rubric_versions_generation_check',
    'rubric_versions_content_check',
    'rubric_versions_confirmation_check'
  )
order by conname;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and indexname in (
    'rubric_versions_provider_config_id_idx',
    'rubric_versions_one_draft_idx',
    'rubric_versions_one_confirmed_idx'
  )
order by indexname;

select tgname, pg_get_triggerdef(oid) as definition
from pg_trigger
where tgrelid in (
  'public.assignments'::regclass,
  'public.grading_jobs'::regclass
)
  and not tgisinternal
  and tgname in (
    'assignments_require_confirmed_rubric',
    'grading_jobs_require_confirmed_rubric'
  )
order by tgname;

select
  p.proname,
  p.proconfig,
  p.provolatile,
  has_function_privilege('anon', p.oid, 'execute') as anon_can_execute,
  has_function_privilege('authenticated', p.oid, 'execute') as authenticated_can_execute,
  has_function_privilege('service_role', p.oid, 'execute') as service_role_can_execute,
  has_function_privilege('paper_grading_teacher_api', p.oid, 'execute')
    as teacher_api_can_execute
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'paper_grading_valid_structured_rubric',
    'paper_grading_require_confirmed_rubric_for_ready_assignment',
    'paper_grading_require_confirmed_job_rubric',
    'paper_grading_protect_rubric_history'
  )
order by p.proname;

select pg_get_functiondef(
  'public.paper_grading_protect_rubric_history()'::regprocedure
) as rubric_history_function;

select
  c.relname,
  c.relrowsecurity,
  c.relforcerowsecurity,
  count(p.policyname) as policy_count
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
left join pg_policies as p
  on p.schemaname = n.nspname
 and p.tablename = c.relname
where n.nspname = 'public'
  and c.relname in ('assignments', 'rubric_versions', 'grading_jobs')
group by c.relname, c.relrowsecurity, c.relforcerowsecurity
order by c.relname;

select
  (select count(*) from public.assignments) as assignments,
  (select count(*) from public.rubric_versions) as rubric_versions,
  (select count(*) from public.grading_jobs) as grading_jobs;
```

### 4. 预期结果

| 检查 | 预期 |
|---|---|
| Alembic 版本 | `20260716_0008` |
| 新列 | `provider_config_id`、`model` 均存在且可空 |
| 约束 | 5 个目标约束全部存在 |
| 索引 | 3 个目标索引全部存在；草稿和确认索引均为部分唯一索引 |
| 触发器 | 2 个目标触发器全部存在 |
| 函数安全 | 4 个函数的 `proconfig` 均为 `search_path=""`；三个 Supabase API 角色均不可执行 |
| 校验函数权限 | 只有 `paper_grading_valid_structured_rubric` 对 `paper_grading_teacher_api` 为 `true`；另外三个函数为 `false` |
| 函数易变性 | 结构校验函数为 `i`；另外三个函数为 `v` |
| 历史冻结函数 | 函数定义同时包含 `NEW/OLD.provider_config_id`、`NEW/OLD.model` 和 `ready assignment cannot lose its confirmed rubric` |
| RLS | 3 张表的 `relrowsecurity`、`relforcerowsecurity` 均为 `true` |
| Policy 数量 | `assignments=3`、`rubric_versions=3`、`grading_jobs=2` |
| 业务行数 | 与迁移前完全相同 |

上述迁移和只读核验已通过，以下只执行真实功能验收，不再运行迁移。

## 真实功能验收（等待用户执行）

以下操作会在独立 Supabase 测试项目创建一条作业和两个 Rubric 版本。由用户执行；Codex 在收到结果前不继续阶段 6 收口。

### 1. 启动后端

新开一个终端执行：

```bash
cd "/Users/a1-6/Documents/Paper Grading"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
set -a
source .env.stage5-local
set +a
./.venv/bin/uvicorn app.main:app \
  --app-dir backend \
  --reload \
  --host 127.0.0.1 \
  --port 8000
```

### 2. 启动前端

再开一个终端执行：

```bash
cd "/Users/a1-6/Documents/Paper Grading"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
set -a
source .env.stage5-local
set +a
npm --prefix frontend run dev -- --host 127.0.0.1
```

两个终端都要保持运行；验收结束前不要按 `Control-C`。

### 3. 完成页面流程

1. 使用已激活教师账户登录。
2. 创建作业，标题固定为 `阶段六验收 - 2026-07-16`。
3. 题目要求填写：`阅读短文，写一篇结构清晰的英文议论文。`
4. 原始评分标准填写：

```text
内容与任务回应 10 分：观点明确，论证充分，并使用具体证据。
结构与衔接 6 分：段落完整，逻辑清晰，衔接自然。
语言准确性 4 分：语法、词汇和拼写准确。
```

5. 总分填写 `20`，评分步长填写 `1`，保存作业；成功后页面会自动进入该作业的 Rubric 页面。
6. 在 Rubric 页面选择阶段 5 已启用的 DeepSeek 供应商，点击“生成结构化草稿”。创建作业页面不选择模型，因为此时作业和 Rubric 草稿尚未保存。
7. 确认页面显示总分 `20`、步长 `1`，且包含维度、连续分档、证据要求和统一扣分项，然后点击“确认评分标准”。
8. 返回作业列表，确认作业状态为“可批改”，Rubric 为“已确认 v1”。
9. 再次进入作业，点击“创建新版本”，在原始评分标准末尾追加：`所有评价必须引用学生原文证据。`
10. 保存 v2，再次选择 DeepSeek、生成并确认。
11. 确认版本记录显示 `v2 已确认` 和 `v1 已替代`，已确认页面仍显示其生成供应商和模型。

任何一步报错都停止，把页面提示和后端终端最后一段错误一并发回。

### 4. 在 Supabase SQL Editor 只读核验

先执行：

```sql
select
  a.id as assignment_id,
  a.title,
  a.status as assignment_status,
  rv.version,
  rv.status as rubric_status,
  rv.total_score,
  rv.score_step,
  rv.model,
  (rv.provider_config_id is not null) as has_provider_snapshot,
  (rv.structured_rubric is not null) as has_structured_rubric,
  (rv.confirmed_at is not null) as has_confirmed_at
from public.assignments as a
join public.rubric_versions as rv
  on rv.assignment_id = a.id
 and rv.owner_id = a.owner_id
where a.title = '阶段六验收 - 2026-07-16'
order by rv.version;
```

预期正好 2 行：两行作业状态均为 `ready`；v1 为 `superseded`，v2 为 `confirmed`；总分均为 `20`、步长均为 `1`；模型非空，三个 `has_*` 均为 `true`。

再执行：

```sql
select count(*) as invalid_stage6_rows
from public.assignments as a
left join public.rubric_versions as rv
  on rv.assignment_id = a.id
 and rv.owner_id = a.owner_id
where a.title = '阶段六验收 - 2026-07-16'
  and (
    a.status <> 'ready'
    or rv.provider_config_id is null
    or rv.model is null
    or rv.structured_rubric is null
    or rv.confirmed_at is null
  );

select count(*) as grading_jobs_with_unconfirmed_rubric
from public.grading_jobs as job
join public.rubric_versions as rubric
  on rubric.id = job.rubric_version_id
 and rubric.assignment_id = job.assignment_id
 and rubric.owner_id = job.owner_id
where rubric.status <> 'confirmed';
```

两个结果都必须为 `0`。

### 5. 验证未确认版本不能启动批改

以下检查会尝试用已替代的 v1 创建批改任务，并在数据库触发器正确拒绝后自动恢复；不会留下批改任务。请在 Supabase SQL Editor 执行：

```sql
do $$
declare
  target record;
  guard_rejected boolean := false;
begin
  select
    a.owner_id,
    a.id as assignment_id,
    rv.id as rubric_id,
    rv.provider_config_id,
    rv.model
  into strict target
  from public.assignments as a
  join public.rubric_versions as rv
    on rv.assignment_id = a.id
   and rv.owner_id = a.owner_id
  where a.title = '阶段六验收 - 2026-07-16'
    and rv.version = 1
    and rv.status = 'superseded';

  begin
    insert into public.grading_jobs (
      owner_id,
      assignment_id,
      rubric_version_id,
      provider_config_id,
      model,
      model_parameters,
      prompt_version,
      prompt_hash,
      idempotency_key
    ) values (
      target.owner_id,
      target.assignment_id,
      target.rubric_id,
      target.provider_config_id,
      target.model,
      '{}'::jsonb,
      'stage6-negative-check',
      decode(repeat('00', 32), 'hex'),
      'stage6-negative-' || gen_random_uuid()::text
    );
  exception
    when check_violation then
      if sqlerrm <> 'grading job requires a confirmed rubric and ready assignment' then
        raise;
      end if;
      guard_rejected := true;
  end;

  if not guard_rejected then
    raise exception '阶段六门禁失效：数据库接受了未确认 Rubric';
  end if;

  raise notice 'unconfirmed_rubric_guard=passed';
end
$$;

select count(*) as negative_check_rows_left
from public.grading_jobs
where idempotency_key like 'stage6-negative-%';
```

预期：`do` 语句无报错完成，`negative_check_rows_left=0`。如果出现任何错误，停止并把完整错误发回。

请把作业列表截图、版本记录截图、第一条 SQL 的两行结果、三个计数结果和负向门禁执行结果发回当前任务。
