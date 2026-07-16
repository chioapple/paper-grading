# 阶段 7 验收：DOCX/PDF 上传、Supabase Storage 与解析

## 当前状态

- 阶段 7 本地实现已完成：文件预检、DOCX/PDF 严格解析、可定位文本块、SHA-256 去重、私有 Supabase Storage 写入、短时下载地址、论文 API 和响应式上传页面均已落地。
- 本地自动化测试：后端通过 202、失败 0，真实 PostgreSQL 测试 5 项按配置排除；前端通过 32、失败 0。
- Ruff、格式、mypy、前端 lint、类型检查、生产构建和差异检查均通过。
- 桌面与 390×844 手机页面已通过本地替身验收，控制台错误 0、警告 0。
- 当前本地 Alembic 头和 Supabase 测试项目均为 `20260716_0009`。
- 用户已确认本文件全部输出正确：Storage Policy、自检、数据库前向迁移、真实上传、失败重试、并发去重、跨教师隔离、对象路径和 API 脱敏均通过。
- 阶段 7 已完成。

## 已实现边界

- 浏览器每次最多选择 100 篇，单文件最多 20MB；API 每次只流式处理一个文件，页面最多并发 3 个请求，避免一次请求缓存 100 个大文件。
- 服务器依据文件内容识别真实 DOCX/PDF，不信任扩展名或浏览器 MIME。
- DOCX 检查 OOXML 主文档契约、加密、宏、重复条目、路径穿越、DTD/实体、CRC、解压总量和压缩比。
- DOCX 正文按段落和表格单元格生成定位；页眉、页脚、文本框、修订、内容控件和嵌套表格会明确失败，不会静默丢文。
- PDF 最多 200 页；按真实文本行保存页码、页内序号和实际坐标；扫描页、加密、损坏、空白和不可提取页面会明确失败，不执行 OCR。
- 两种格式均限制最多 50 万字符和 5 万个文本块。
- 同一作业以 SHA-256 去重；已失败的同一文件允许重新解析，已完成的同一文件不重复写入对象。
- 原文件和 `document-blocks.v1.json` 使用服务端生成的私有对象路径；浏览器看不到对象路径和哈希。
- 只有当前教师名下、状态为 `ready` 的论文才能获得 30–300 秒的短时下载地址，当前默认 60 秒。
- 解析失败的原文件保留并由数据库失败记录引用，供后续审计和重试；未被数据库引用的规范文本对象会立即补偿删除。统一保留期和自动清理由阶段 13 实现。

## 一、准备 Supabase Storage（由用户操作）

当前后端使用 Supabase Storage 标准 API，不使用 Cloudflare，也不创建 Supabase S3 Access Key。后端复用已有 `SUPABASE_SECRET_KEY`；该 Key 绕过 Storage RLS，因此只能存在于 FastAPI，浏览器仍必须通过 FastAPI 的教师归属检查获取短时下载地址。参考：

- <https://supabase.com/docs/guides/storage/buckets/creating-buckets>
- <https://supabase.com/docs/guides/storage/security/access-control>
- <https://supabase.com/docs/guides/storage/uploads/standard-uploads>
- <https://supabase.com/docs/reference/javascript/storage-from-createsignedurl>

### 1. 创建私有测试桶

1. 进入当前独立测试项目的 Supabase Dashboard → Storage。
2. 新建桶，建议名称：`paper-grading-test`。
3. `Public bucket` 必须关闭。
4. 文件大小限制设为 `20 MB`。
5. 允许 MIME 类型：`application/pdf`、`application/vnd.openxmlformats-officedocument.wordprocessingml.document`、`application/json`。
6. 不为 `anon` 或 `authenticated` 创建上传、读取、更新或删除 Policy；浏览器不直接操作 Storage。
7. 在 SQL Editor 执行以下只读检查；独立测试项目应返回 `0` 行，若存在 Policy 就停止并回传结果：

```sql
select policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
order by policyname;
```

### 2. 创建阶段 7 本地配置

在项目根目录执行。该命令复制现有阶段 5/6 配置，随后只在本机补充 Storage 字段，不产生第二套密钥：

```zsh
cp .env.stage5-local .env.stage7-local
chmod 600 .env.stage7-local

read -r "SUPABASE_STORAGE_BUCKET?Supabase Storage bucket name: "

umask 077
grep -Ev '^SUPABASE_STORAGE_(BUCKET|SIGNED_URL_TTL_SECONDS|TIMEOUT_SECONDS)=' \
  .env.stage7-local > .env.stage7-local.next
{
  printf 'SUPABASE_STORAGE_BUCKET=%q\n' "$SUPABASE_STORAGE_BUCKET"
  printf 'SUPABASE_STORAGE_SIGNED_URL_TTL_SECONDS=60\n'
  printf 'SUPABASE_STORAGE_TIMEOUT_SECONDS=60.0\n'
} >> .env.stage7-local.next
mv .env.stage7-local.next .env.stage7-local
chmod 600 .env.stage7-local
unset SUPABASE_STORAGE_BUCKET
```

只验证配置，不打印密钥：

```zsh
set -a
source .env.stage7-local
set +a
PYTHONPATH=backend ./.venv/bin/python -c 'from app.config import Settings; s=Settings.load(); print("stage7 config valid", s.supabase_storage_bucket, s.supabase_storage_signed_url_ttl_seconds)'
```

预期输出桶名和 `60`，不得输出 Access Key 或 Secret。

确认 Storage 与迁移连接属于同一个独立测试项目；该命令只输出 project ref：

```zsh
stage7_ref=$(
  set -a
  source .env.stage7-local
  set +a
  ./.venv/bin/python -c 'import os; from urllib.parse import urlparse; print(urlparse(os.environ["SUPABASE_URL"]).hostname.split(".")[0])'
)
stage2_ref=$(
  set -a
  source .env.stage2-test
  set +a
  printf '%s' "$TEST_SUPABASE_PROJECT_REF"
)
if [[ "$stage7_ref" != "$stage2_ref" ]]; then
  echo "stage7 project mismatch: Storage=$stage7_ref database=$stage2_ref"
  exit 1
fi
echo "stage7 project match: $stage7_ref"
unset stage7_ref stage2_ref
```

### 3. 真实 Storage 私有和过期验收

以下脚本先核验桶为私有、20MB 上限和三种允许 MIME，再写入一条不含论文的临时 JSON；脚本验证后自动删除，运行约 62 秒，不输出密钥或签名 URL：

```zsh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
set -a
source .env.stage7-local
set +a
PYTHONPATH=backend ./.venv/bin/python backend/scripts/stage7_supabase_storage_acceptance.py
```

预期只输出：

```text
stage7 Supabase Storage acceptance passed
```

任一错误都停止，把错误文字发回当前任务；不要发送 Key 或 URL。

## 二、Supabase 前向迁移（只由用户操作）

以下操作只针对独立 Supabase 测试项目。不要在生产项目执行，不要使用应用的 Supavisor 地址；Alembic 只使用 `.env.stage2-test` 中的 direct `TEST_MIGRATION_DATABASE_URL`。

### 1. 迁移前只读检查

在 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select
  count(*) as submissions,
  count(*) filter (where status = 'ready') as ready,
  count(*) filter (where status = 'failed') as failed
from public.submissions;

select count(*) as invalid_stage7_rows
from public.submissions
where file_size_bytes <= 0
   or file_size_bytes > 20971520
   or octet_length(content_sha256) <> 32
   or char_length(original_filename) not between 1 and 255
   or btrim(original_filename) = ''
   or source_object_key <> (
        'teachers/' || owner_id::text ||
        '/assignments/' || assignment_id::text ||
        '/submissions/' || id::text ||
        case
          when media_type = 'application/pdf' then '/source.pdf'
          else '/source.docx'
        end
   )
   or (
        extracted_object_key is not null
        and extracted_object_key <> (
          'teachers/' || owner_id::text ||
          '/assignments/' || assignment_id::text ||
          '/submissions/' || id::text || '/document-blocks.v1.json'
        )
   )
   or not (
        (status in ('uploaded', 'parsing')
          and extracted_object_key is null and error_code is null)
        or (status = 'ready'
          and extracted_object_key is not null and error_code is null)
        or (status = 'failed'
          and extracted_object_key is null
          and error_code is not null
          and btrim(error_code) <> '')
   );
```

预期：

| 检查 | 预期 |
|---|---|
| Alembic 版本 | `20260716_0008` |
| `invalid_stage7_rows` | `0` |
| 论文计数 | 记录迁移前数值，迁移后必须完全相同 |

任一结果不符合时停止，不要修改或删除数据，把完整结果发回当前任务。

### 2. 执行前向迁移

在项目根目录执行：

```zsh
set -a
source .env.stage2-test
set +a
MIGRATION_DATABASE_URL="$TEST_MIGRATION_DATABASE_URL" \
  .venv/bin/alembic -c backend/alembic.ini upgrade 20260716_0009
```

命令必须无报错返回终端提示符。不要执行 `downgrade`。

### 3. 迁移后只读核验

在 Supabase SQL Editor 执行：

```sql
select version_num from public.alembic_version;

select conname, contype, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.submissions'::regclass
  and conname in (
    'submissions_file_check',
    'submissions_original_filename_check',
    'submissions_state_check',
    'submissions_object_keys_check',
    'submissions_source_object_key_key'
  )
order by conname;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'submissions'
  and indexname = 'submissions_extracted_object_key_idx';

select
  p.proname,
  p.prosecdef,
  p.proconfig,
  pg_get_userbyid(p.proowner) as owner,
  has_function_privilege('anon', p.oid, 'execute') as anon_can_execute,
  has_function_privilege('authenticated', p.oid, 'execute') as authenticated_can_execute,
  has_function_privilege('service_role', p.oid, 'execute') as service_role_can_execute,
  has_function_privilege('paper_grading_teacher_api', p.oid, 'execute')
    as teacher_api_can_execute
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'paper_grading_private'
  and p.proname = 'transition_submission';

select
  has_table_privilege('paper_grading_teacher_api', 'public.submissions', 'select')
    as teacher_can_select,
  has_table_privilege('paper_grading_teacher_api', 'public.submissions', 'insert')
    as teacher_can_insert,
  has_table_privilege('paper_grading_teacher_api', 'public.submissions', 'update')
    as teacher_can_update,
  has_table_privilege('paper_grading_teacher_api', 'public.submissions', 'delete')
    as teacher_can_delete;

select
  c.relrowsecurity,
  c.relforcerowsecurity,
  count(p.policyname) as policy_count
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
left join pg_policies as p
  on p.schemaname = n.nspname
 and p.tablename = c.relname
where n.nspname = 'public'
  and c.relname = 'submissions'
group by c.relrowsecurity, c.relforcerowsecurity;

select
  count(*) as submissions,
  count(*) filter (where status = 'ready') as ready,
  count(*) filter (where status = 'failed') as failed
from public.submissions;
```

预期：

| 检查 | 预期 |
|---|---|
| Alembic 版本 | `20260716_0009` |
| 约束 | 5 个目标约束全部存在 |
| 索引 | `submissions_extracted_object_key_idx` 为非空条件唯一索引 |
| 状态函数 | `prosecdef=true`，`proconfig` 含空 `search_path` |
| 函数权限 | `anon/authenticated/service_role=false`，`teacher_api=true` |
| 表权限 | `select=true`、`insert=true`、`update=false`、`delete=false` |
| RLS | `relrowsecurity=true`、`relforcerowsecurity=true`、Policy 数量 `2` |
| 业务计数 | 与迁移前完全相同 |

## 三、真实上传与跨教师验收（只由用户操作）

Storage 自检和 `0009` 迁移均通过后，在同一测试项目启动前后端，并按下表验收。签名 URL 是临时 bearer token；不要把 URL、Token 或 Key 发到聊天中。

| 检查 | 操作 | 必须结果 |
|---|---|---|
| 真实格式 | 教师 A 在已确认 Rubric 的作业中分别上传一篇合法 DOCX 和可提取文字的 PDF | 两篇均为 `ready`，下载内容与原文件一致 |
| 明确失败 | 上传扫描 PDF、损坏文件或伪造扩展名文件 | 返回稳定错误码，记录为 `failed`，不伪装成功 |
| 重复与并发 | 对同一作业同时发起两次相同文件上传 | 只保留一条论文记录和一组对象；另一次返回重复结果 |
| 失败重试 | 重新上传一篇状态为 `failed` 的相同文件 | 原记录转回处理流程，不永久停在 `uploaded/parsing` |
| 跨教师隔离 | 教师 B 使用教师 A 的作业 ID 和论文 ID 请求下载接口 | API 返回 `404`，不会为教师 B 签发新 URL |
| 对象路径 | 在 Storage Dashboard 查看教师 A 的对象 | 只存在服务端生成的 `teachers/<teacher>/assignments/<assignment>/submissions/<submission>/...` 路径 |
| API 脱敏 | 查看上传、列表和下载接口响应 | 不包含 SHA-256、对象路径、Secret Key 或内部 Storage 错误 |

用户已确认 Storage Policy 只读结果、自检结果、迁移前后 SQL、Alembic 终端结果和上表结果全部正确。阶段 7 验收完成。
