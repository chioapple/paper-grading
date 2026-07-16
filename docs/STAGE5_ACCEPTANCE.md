# 阶段 5 验收：管理员模型配置

## 当前状态

- 本地前后端、加密、连接测试、权限、界面和前向迁移 `20260715_0007` 已实现。
- 第一次 Supabase 迁移因 Alembic 对约束名重复套用命名规则而失败；修复后用户已成功执行 `0006 → 0007`，终端无报错返回。
- 用户回传的汇总核验五项全部为 `true`；迁移版本、列、5 个约束、触发器和函数安全均通过。
- 迁移验收时 `provider_configs` 总数、启用数和已测试数均为 0；随后已通过本地管理页面创建、测试并启用 DeepSeek 配置。
- 替代 DeepSeek Key 只在本地管理页面输入，真实模型列表连接测试、默认模型校验、启用和 Key 不回显均通过；关闭梯子并重启后端后的最终数据库就绪检查也已通过。
- 任何出现在聊天中的真实 API Key 都视为已泄露，必须撤销，不能继续使用。

## Supabase 操作流程（已完成，留档）

以下命令只由用户在项目根目录执行。它会把测试项目从 `20260715_0006` 升级到 `20260715_0007`，不会删除表；若存在以前已启用或已测试的供应商配置，会统一改回 `draft` 并清除测试时间，要求重新测试。

1. 先确认 `.env.stage2-test` 仍指向独立 Supabase 测试项目，不是生产项目。
2. 若上次迁移出现 `provider_configs_provider_configs_*_check_check` 错误，无需手工清理；该次迁移使用事务，失败后会整体回滚。可先在 Supabase SQL Editor 确认版本仍为 `20260715_0006`：

```sql
select version_num from public.alembic_version;
```

3. 使用已修复的本地迁移重新执行前向迁移：

```bash
set -a
source .env.stage2-test
set +a
MIGRATION_DATABASE_URL="$TEST_MIGRATION_DATABASE_URL" \
  .venv/bin/alembic -c backend/alembic.ini upgrade 20260715_0007
```

4. 在 Supabase SQL Editor 执行只读核验：

```sql
select version_num from public.alembic_version;

select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'provider_configs'
  and column_name in ('config_version', 'tested_config_version')
order by column_name;

select conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.provider_configs'::regclass
  and conname in (
    'provider_configs_enabled_check',
    'provider_configs_key_material_check',
    'provider_configs_test_version_check',
    'provider_configs_text_check',
    'provider_configs_default_model_check'
  )
order by conname;

select tgname, pg_get_triggerdef(oid) as definition
from pg_trigger
where tgrelid = 'public.provider_configs'::regclass
  and not tgisinternal
  and tgname = 'provider_configs_invalidate_test';

select
  p.proname,
  p.proconfig,
  has_function_privilege('anon', p.oid, 'execute') as anon_can_execute,
  has_function_privilege('authenticated', p.oid, 'execute') as authenticated_can_execute,
  has_function_privilege('service_role', p.oid, 'execute') as service_role_can_execute
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'paper_grading_invalidate_provider_test';

select
  count(*) as total,
  count(*) filter (where status = 'enabled') as enabled,
  count(*) filter (where tested_at is not null) as tested
from public.provider_configs;
```

5. 预期结果：

| 检查 | 预期 |
|---|---|
| Alembic 版本 | `20260715_0007` |
| 新列 | 两列都存在；`config_version` 非空，`tested_config_version` 可空 |
| 约束 | 5 个约束全部存在 |
| 触发器 | `provider_configs_invalidate_test` 存在 |
| 函数 | `proconfig` 为 `search_path=""`；三个 API 角色的执行权限均为 `false` |
| 旧配置 | 以前的启用/测试状态已失效，必须重新连接测试 |

6. 用户已回传迁移输出和 SQL 结果，全部检查通过。

## Supabase 验收结果

| 检查 | 结果 |
|---|---|
| 迁移版本 | `20260715_0007`，通过 |
| 新列 | `config_version:NO`、`tested_config_version:YES`，通过 |
| 约束 | 5 个目标约束，汇总检查通过 |
| 触发器 | `provider_configs_invalidate_test`，通过 |
| 函数安全 | `search_path=""` 且三个 API 角色无执行权限，通过 |
| 旧配置 | `total=0`、`enabled=0`、`tested=0`，通过 |

## 真实连接验收流程（已完成，留档）

### 1. 准备本地运行密钥

#### VPN / 代理节点要求

- 一次验收期间固定同一个节点，不要在 API 运行中切换节点；切换会中断连接池中的现有连接。
- 浏览器代理不代表 PostgreSQL TCP 流量会经过同一节点。使用系统全局或 TUN 模式时，需确认终端流量也经过该节点；否则让终端直接访问 Supavisor。
- Supabase Dashboard → Database Settings → Network Restrictions：若从未启用限制，保持不变；若已启用，手动把当前稳定节点的 IPv4 出口地址以 `/32` 加入允许列表，并保留原有 CIDR。节点变化后重复更新，不能为了省事开放 `0.0.0.0/0`。
- 本项目应用连接固定使用 Supavisor Session pooler 5432；`TEST_MIGRATION_DATABASE_URL` direct 地址仍只用于 Alembic。

1. 在 Supabase 项目控制台的 API Keys 页面准备 publishable key 和 secret key。
2. 在 Supabase 项目控制台点击 `Connect`，选择 `Session pooler`，确认端口为 `5432`。把 URI 的协议改为 `postgresql+asyncpg://`，替换真实数据库密码，并在末尾使用 `?ssl=require`。应用连接禁止复用 `TEST_MIGRATION_DATABASE_URL` 直连地址。
3. 在项目根目录执行以下 zsh 命令。输入内容不会出现在命令历史中，生成的 `.env.stage5-local` 已被 Git 忽略且权限为仅当前用户可读写。

```zsh
source .env.stage2-test

read -r "SUPABASE_PUBLISHABLE_KEY?Supabase publishable key: "
read -rs "SUPABASE_SECRET_KEY?Supabase secret key: "
echo
read -rs "DATABASE_URL?Supabase session pooler 5432 DATABASE_URL: "
echo

PROVIDER_MASTER_KEY="$(./.venv/bin/python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
SUPABASE_URL="https://${TEST_SUPABASE_PROJECT_REF}.supabase.co"

umask 077
{
  printf 'APP_ENV=development\n'
  printf 'DATABASE_URL=%q\n' "$DATABASE_URL"
  printf 'SUPABASE_URL=%q\n' "$SUPABASE_URL"
  printf 'SUPABASE_PUBLISHABLE_KEY=%q\n' "$SUPABASE_PUBLISHABLE_KEY"
  printf 'SUPABASE_SECRET_KEY=%q\n' "$SUPABASE_SECRET_KEY"
  printf 'AUTH_INVITE_REDIRECT_URL=http://127.0.0.1:5173/auth/callback\n'
  printf 'FRONTEND_ORIGIN=http://127.0.0.1:5173\n'
  printf 'PROVIDER_MASTER_KEY=%q\n' "$PROVIDER_MASTER_KEY"
  printf 'VITE_SUPABASE_URL=%q\n' "$SUPABASE_URL"
  printf 'VITE_SUPABASE_PUBLISHABLE_KEY=%q\n' "$SUPABASE_PUBLISHABLE_KEY"
  printf 'VITE_API_BASE_URL=http://127.0.0.1:8000\n'
} > .env.stage5-local
chmod 600 .env.stage5-local

unset DATABASE_URL SUPABASE_SECRET_KEY PROVIDER_MASTER_KEY
```

4. 只验证配置格式和连接入口，不输出任何密钥：

```zsh
set -a
source .env.stage5-local
set +a
PYTHONPATH=backend ./.venv/bin/python -c 'from app.config import Settings; from sqlalchemy.engine import make_url; s=Settings.load(); u=make_url(s.database_url); assert u.host and u.host.endswith(".pooler.supabase.com") and u.port == 5432, "DATABASE_URL 必须使用 Supavisor session pooler 5432"; print("stage5 local config valid")'
```

预期只输出 `stage5 local config valid`。

> 若此前按旧流程把 `TEST_MIGRATION_DATABASE_URL` 写入 `.env.stage5-local`，必须重新执行本节覆盖该文件。迁移直连地址只供 Alembic 使用，不供 FastAPI 连接池使用。

#### 只修正现有 `.env.stage5-local` 的连接地址

若其他密钥已经准备完成，只需执行以下流程，不必重新输入它们：

```zsh
cd "/Users/a1-6/Documents/Paper Grading"

read -rs "NEW_DATABASE_URL?Supabase Session pooler 5432 URI: "
echo

NEW_DATABASE_URL="${NEW_DATABASE_URL/#postgres:\/\//postgresql+asyncpg://}"
NEW_DATABASE_URL="${NEW_DATABASE_URL/#postgresql:\/\//postgresql+asyncpg://}"
NEW_DATABASE_URL="${NEW_DATABASE_URL%%\?*}?ssl=require"

umask 077
while IFS= read -r line; do
  if [[ "$line" == DATABASE_URL=* ]]; then
    printf 'DATABASE_URL=%q\n' "$NEW_DATABASE_URL"
  else
    printf '%s\n' "$line"
  fi
done < .env.stage5-local > .env.stage5-local.next

chmod 600 .env.stage5-local.next
mv .env.stage5-local.next .env.stage5-local
unset NEW_DATABASE_URL

set -a
source .env.stage5-local
set +a
PYTHONPATH=backend ./.venv/bin/python -c 'from app.config import Settings; from sqlalchemy.engine import make_url; s=Settings.load(); u=make_url(s.database_url); assert u.host and u.host.endswith(".pooler.supabase.com") and u.port == 5432, "DATABASE_URL 必须使用 Supavisor session pooler 5432"; print("stage5 pooler config valid")'
```

预期只输出 `stage5 pooler config valid`，不得把连接 URI 或任何 Key 发到聊天中。

### 2. 准备 DeepSeek 替代 Key

- 撤销已在聊天中出现的 DeepSeek Key，创建替代 Key。
- 替代 Key 不写入 `.env.stage5-local`，也不发送到聊天；只在本地“模型配置”页面输入一次。

### 3. 连接验收

- 启动本地 API 和前端，管理员登录后新建 DeepSeek 配置。
- 使用替代 Key 完成连接测试；只有当前配置测试通过后才能启用。
- 验证列表、编辑接口和浏览器不回显 API Key。
- 验证教师接口只返回管理员允许且已启用的模型，永远不返回 API Key。

## 真实连接验收结果

| 检查 | 结果 |
|---|---|
| 应用数据库 | 关闭 VPN 并重启后端后，`live=200`、`ready=200`，数据库状态为 `available` |
| DeepSeek | 模型列表连接测试通过；默认模型 `deepseek-v4-pro` 存在于供应商可用列表 |
| 启用约束 | 当前配置已测试后才允许启用；页面状态为“已启用” |
| Key 安全 | 列表只显示“Key 已配置”；编辑 Key 字段为密码框、值为空；422 校验错误不返回原始输入、上下文或密钥 |
| 教师投影 | 自动化测试确认只返回已启用供应商的允许模型和默认模型，不包含 Key |
| 响应式界面 | 桌面与 390×844 移动端检查通过 |
| 自动化测试 | 后端 112、前端 20，失败 0；静态检查和生产构建通过 |

阶段 5 功能、安全与真实环境验收全部通过，阶段已完成；下一步进入阶段 6。
