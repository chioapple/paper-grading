# 阶段 13 验收：配额、保留与备份

## 当前状态

阶段 13 已于 2026-07-28 完成。真实配额边界、失败关闭、并发预留、迁移与权限均已通过；自动清理和备份按用户决定保持关闭，后续启用时重新授权并单独验收。

## 1. 开发决策

开始真实接入前，请先填写并确认：

| 决策 | 当前值 |
|---|---|
| 备份 | 本阶段不启用；后续按需要接入并单独验收 |
| 独立备份目标、账户、区域 | 本阶段不适用；后续启用备份时确认 |
| 备份密钥所有者、托管位置、轮换 | 本阶段不适用；后续启用备份时确认 |
| 配额通知渠道、接收角色、去重窗口 | 暂不启用外部通知 |
| 三类原始对象的起算字段和允许清理终态 | 起算字段为创建时间；仅在对应处理完成后允许清理 |
| 人工保留的范围、理由和解除权限 | 教师可标记保留并填写理由；管理员可解除 |
| 自动清理 | 本阶段保持关闭；以第五步的关闭状态、dry-run 和状态机结果作为最终验收标准 |
| 用量刷新周期、过期定义、失败策略 | 配额判断实时查询；外部用量提醒暂不启用；查询失败时拒绝写入 |
| 逻辑备份白名单、Auth/Storage 依赖、RPO/RTO | 本阶段不适用；后续启用备份时确认 |

## 2. 本地门禁

执行终端：项目根目录。

```bash
cd "/Users/a1-6/Documents/Paper Grading/backend"
../.venv/bin/pytest -q
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app
```

执行终端：项目根目录。

```bash
cd "/Users/a1-6/Documents/Paper Grading/frontend"
npm test -- --run
npm run lint
npm run typecheck
npm run build
```

验收标准：所有默认测试、静态检查和构建通过；真实 PostgreSQL 测试只因未提供独立测试项目配置而排除。

## 3. 迁移回放

只允许在独立 Supabase 测试项目执行，不得对已验收的真实项目回退。先停止测试项目 API 和 Worker，再加载本机测试环境文件；不得回显连接地址。

```bash
cd "/Users/a1-6/Documents/Paper Grading"
set -a
source .env.stage2-test
set +a
.venv/bin/pytest -q -c backend/pyproject.toml -m postgres \
  backend/tests/test_stage13_postgres_contract.py
```

验收标准：

- `0017 → 0018 → 0017 → 0018` 使用同一 direct 连接完成；
- 最终迁移版本是 `20260726_0018`；
- 配额、保留和备份内部表全部强制 RLS；
- 私有函数固定空 `search_path`，公开 Data API 角色不能执行；
- 保留和备份角色不继承权限且不能绕过 RLS。

## 4. 配额

用户已确认按 Free Plan 的数据库容量 `500,000,000` 字节、Storage 容量
`1,000,000,000` 字节和桶 `paper-grading-test` 验收。当前项目内额外的
`test` 数据库不单独从 500 MB 中扣减；这是本阶段明确接受的验收口径。

先在独立 Supabase 测试项目的 SQL Editor 一次性执行以下完整代码。所有配置、
告警和预留均位于同一事务，最后必须显示探测通过并执行 `ROLLBACK`；本步骤不会
永久启用配额，也不会上传或删除 Storage 对象。

```sql
BEGIN;

DO $$
DECLARE
    database_used bigint;
    storage_used bigint;
    actual_state text;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM storage.buckets
        WHERE id = 'paper-grading-test'
    ) THEN
        RAISE EXCEPTION 'stage13 quota probe: storage bucket missing';
    END IF;

    IF EXISTS (SELECT 1 FROM public.quota_reservations) THEN
        RAISE EXCEPTION 'stage13 quota probe: existing reservations must be reviewed';
    END IF;

    database_used := pg_catalog.pg_database_size(pg_catalog.current_database());
    SELECT COALESCE(
        pg_catalog.sum((metadata->>'size')::bigint),
        0
    )
    INTO storage_used
    FROM storage.objects
    WHERE bucket_id = 'paper-grading-test';

    IF database_used >= 350000000 THEN
        RAISE EXCEPTION 'stage13 quota probe: database already exceeds warning boundary';
    END IF;
    IF storage_used >= 700000000 THEN
        RAISE EXCEPTION 'stage13 quota probe: storage already exceeds warning boundary';
    END IF;

    UPDATE public.quota_resource_states
    SET enabled = true,
        capacity_bytes = 500000000,
        warning_ratio = 0.7000,
        hard_limit_ratio = 0.8500,
        source_identifier = NULL
    WHERE resource = 'database';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'stage13 quota probe: database configuration missing';
    END IF;

    UPDATE public.quota_resource_states
    SET enabled = true,
        capacity_bytes = 1000000000,
        warning_ratio = 0.7000,
        hard_limit_ratio = 0.8500,
        source_identifier = 'paper-grading-test'
    WHERE resource = 'storage';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'stage13 quota probe: storage configuration missing';
    END IF;

    SELECT state
    INTO actual_state
    FROM paper_grading_private.check_database_growth(
        'stage13-acceptance-database-blocked',
        425000000 - database_used
    );
    IF actual_state IS DISTINCT FROM 'blocked' THEN
        RAISE EXCEPTION 'stage13 quota probe: database 85 percent was %', actual_state;
    END IF;

    SELECT state
    INTO actual_state
    FROM paper_grading_private.check_database_growth(
        'stage13-acceptance-database-warning',
        350000000 - database_used
    );
    IF actual_state IS DISTINCT FROM 'warning' THEN
        RAISE EXCEPTION 'stage13 quota probe: database 70 percent was %', actual_state;
    END IF;

    SELECT state
    INTO actual_state
    FROM paper_grading_private.reserve_storage_growth(
        'stage13-acceptance-storage-blocked',
        'stage13-acceptance/quota-blocked.bin',
        pg_catalog.decode(pg_catalog.repeat('85', 32), 'hex'),
        850000000 - storage_used
    );
    IF actual_state IS DISTINCT FROM 'blocked' THEN
        RAISE EXCEPTION 'stage13 quota probe: storage 85 percent was %', actual_state;
    END IF;

    SELECT state
    INTO actual_state
    FROM paper_grading_private.reserve_storage_growth(
        'stage13-acceptance-storage-warning',
        'stage13-acceptance/quota-warning.bin',
        pg_catalog.decode(pg_catalog.repeat('70', 32), 'hex'),
        700000000 - storage_used
    );
    IF actual_state IS DISTINCT FROM 'warning' THEN
        RAISE EXCEPTION 'stage13 quota probe: storage 70 percent was %', actual_state;
    END IF;
END
$$;

SELECT 'stage13_quota_probe_passed' AS result;

ROLLBACK;

SELECT resource, enabled, capacity_bytes, source_identifier
FROM public.quota_resource_states
ORDER BY resource;
```

验收结果必须同时满足：

- 返回 `stage13_quota_probe_passed`；
- `ROLLBACK` 后 `database` 与 `storage` 两行的 `enabled` 都是 `false`；
- `capacity_bytes` 和 `source_identifier` 保持探测前的值。

2026-07-28 用户回传：`stage13_quota_probe_passed`，且 `database`、`storage`
的 `enabled` 在回滚后均为 `false`。70%/85% 边界探测已通过；本节其余真实并发
与业务接口验收仍待执行。

剩余验收已合并到第 3 步的同一条命令，不需要启动前后端、不需要上传大文件。
再次执行第 3 步命令，预期结果由 `2 passed` 变为：

```text
4 passed
```

新增的两个真实测试会验证无效配额信息失败关闭，以及两个并发 Storage 字节预留
只能有一个越过前置门禁。测试只创建随机命名的数据库预留，不调用 Storage API；
结束时删除本次预留和告警，并恢复测试前的完整配额配置。执行前仍必须停止测试项目
API 和 Worker，且 Storage 配额保持关闭、预留表为空；否则测试会主动停止。

业务层由本地门禁验证：批次门禁与创建事务共用、Storage 在远端写入前预留精确
字节、不可用状态拒绝写入，后端和前端只显示稳定文案。2026-07-28 本地定向回归
后端 `19 passed`、前端 `7 passed`；完整本地门禁后端 `463 passed`、前端
`70 passed`。

2026-07-28 用户回传最终真实 PostgreSQL 验收：`4 passed`。新增的失败关闭和
并发 Storage 字节预留测试通过，第四步完成。

验收标准：

- 70% 边界返回 `warning`，85% 边界返回 `blocked`，均包含等号；
- 数据库采样失败和 Storage 查询失败返回 `unavailable`，不能当作 0；
- 两个并发 Storage 写入不能同时越过硬限制；
- 新建批次被后端权威事务阻断，上传在每个单文件写入前按精确字节预留；
- 教师只看到稳定错误文案，不看到容量、对象路径或数据库错误。

阈值探测和并发测试不代表永久启用。测试结束后真实配置必须仍保持关闭。

## 5. 保留

本阶段自动清理保持关闭，只验收关闭状态、dry-run 和状态机，不执行真实删除。

验收标准：

- 自动删除默认返回 `disabled`；
- dry-run 只读，不写候选、不删对象；
- 领取使用短租约，重复投递只有一个 Worker 能删除；
- 删除前重新验证策略、到期时间和人工保留；
- Storage 已不存在视为幂等成功；
- 删除超时记为结果未知，删除成功后数据库断连可安全重投；
- 导出对象、成绩、反馈、Rubric、教师确认和审计记录不进入 30 天范围。

三类对象的起算字段、合法终态和人工保留规则已按第 1 步确认。本阶段不生成真实候选；第五步结果作为本阶段最终验收标准。后续启用真实自动删除时，必须再次取得用户明确授权并单独验收。

验收记录（2026-07-28）：当前“不执行真实删除”的验收范围通过。

- 保留服务、数据库仓库和 Storage 状态机测试：`17 passed`；
- `submission_source`、`submission_extracted`、`grading_raw_response` 均为 `enabled = false`、`retention_days = 30`；
- dry-run 前对象数为 `0`，候选数为 `0`，dry-run 后对象数仍为 `0`；
- 自动清理保持关闭，未生成候选、未删除 Storage 对象。

## 6. 备份与恢复

本阶段不接入备份目标，不执行备份写入、备份清理或恢复演练。本节仅保留后续启用备份时的验收要求；接入前先按 [backup-and-restore.md](runbooks/backup-and-restore.md) 填完决策表。

验收标准：

- 每日备份目标独立于主 Supabase 项目；
- 使用独立备份密钥流式 AES-256-GCM 加密，manifest 不含密钥；
- 上传禁用覆盖，并核对目标版本、密文字节数和 SHA-256；
- 明文临时文件在加密后立即删除，全部临时文件最终清理；
- 备份范围和不覆盖的 Auth、Storage、Redis、密钥写清楚；
- 在隔离环境真实下载、解密、恢复并通过最小业务一致性检查；
- 只有隔离恢复通过才记录 `verified`；
- 7 天备份清理保持关闭，直到用户再次明确授权。

验收记录（2026-07-28）：本阶段“备份保持未启用”的验收范围通过。

- 本地备份加密、完整性和临时文件清理测试：`8 passed`；
- `creation_enabled = false`、`cleanup_enabled = false`；
- 备份间隔为 24 小时、保留期为 7 天，但两个功能均未启用；
- `target_identifier` 未配置；
- `backup_runs` 和 `backup_restore_runs` 均无记录；
- 未创建、上传、清理或恢复任何真实备份。

## 7. 最终确认

只有以下全部通过后，才能把阶段 13 标记为完成：

- 本地门禁；
- 独立测试项目迁移和真实配额阻断；
- 保留策略保持关闭，且第五步的关闭状态、dry-run 和状态机验收通过；
- 备份保持未启用；
- 用户最终确认。

验收记录（2026-07-28）：以上条件全部满足。用户回传最终配额验收 `4 passed`
并确认阶段状态，阶段 13 正式完成。
