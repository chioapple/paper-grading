"""为教师业务数据增加强制 RLS 隔离。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260715_0006"
down_revision: str | None = "20260714_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUSINESS_TABLES = (
    "profiles",
    "provider_configs",
    "assignments",
    "rubric_versions",
    "submissions",
    "grading_jobs",
    "grading_job_items",
    "grading_attempts",
    "teacher_reviews",
    "audit_logs",
    "exports",
)
TEACHER_DATABASE_ROLE = "paper_grading_teacher_api"
TABLE_COMMANDS = {
    "assignments": ("SELECT", "INSERT", "UPDATE"),
    "rubric_versions": ("SELECT", "INSERT", "UPDATE"),
    "submissions": ("SELECT", "INSERT"),
    "grading_jobs": ("SELECT", "INSERT"),
    "grading_job_items": ("SELECT", "INSERT"),
    "grading_attempts": ("SELECT",),
    "teacher_reviews": ("SELECT", "INSERT", "UPDATE"),
    "audit_logs": ("SELECT",),
    "exports": ("SELECT", "INSERT"),
}
TABLE_PRIVILEGES = {
    "assignments": "SELECT, INSERT, UPDATE",
    "rubric_versions": "SELECT, INSERT, UPDATE",
    "submissions": "SELECT, INSERT",
    "grading_jobs": "SELECT, INSERT",
    "grading_job_items": "SELECT, INSERT",
    "grading_attempts": "SELECT",
    "teacher_reviews": "SELECT, INSERT, UPDATE",
    "audit_logs": "SELECT",
    "exports": "SELECT, INSERT",
}
POLICIES = (
    ("profiles", "profiles_teacher_select"),
    *(
        (table_name, f"{table_name}_teacher_{command.lower()}")
        for table_name, commands in TABLE_COMMANDS.items()
        for command in commands
    ),
)

ACTIVE_OWNER_PREDICATE = """
owner_id = (SELECT paper_grading_private.current_active_teacher_id())
""".strip()


def create_owner_policy(table_name: str, command: str) -> None:
    """为一张租户表创建最小命令策略。"""

    policy_name = f"{table_name}_teacher_{command.lower()}"
    if command in {"ALL", "SELECT"}:
        condition = f"USING ({ACTIVE_OWNER_PREDICATE})"
        if command == "ALL":
            condition += f" WITH CHECK ({ACTIVE_OWNER_PREDICATE})"
    elif command == "INSERT":
        condition = f"WITH CHECK ({ACTIVE_OWNER_PREDICATE})"
    elif command == "UPDATE":
        condition = f"USING ({ACTIVE_OWNER_PREDICATE}) WITH CHECK ({ACTIVE_OWNER_PREDICATE})"
    else:
        raise ValueError(f"不支持的 RLS 命令：{command}")
    op.execute(
        f"CREATE POLICY {policy_name} ON public.{table_name} "
        f"FOR {command} TO {TEACHER_DATABASE_ROLE} {condition}"
    )


def upgrade() -> None:
    """增加阶段四教师隔离策略。"""

    op.execute(
        f"""
        DO $paper_grading$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = '{TEACHER_DATABASE_ROLE}'
            ) THEN
                CREATE ROLE {TEACHER_DATABASE_ROLE} NOLOGIN NOINHERIT NOBYPASSRLS;
            END IF;
        END;
        $paper_grading$
        """
    )
    op.execute(f"ALTER ROLE {TEACHER_DATABASE_ROLE} NOLOGIN NOINHERIT NOBYPASSRLS")
    op.execute(f"GRANT {TEACHER_DATABASE_ROLE} TO postgres")
    op.execute("CREATE SCHEMA IF NOT EXISTS paper_grading_private")
    op.execute("REVOKE ALL ON SCHEMA paper_grading_private FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA paper_grading_private TO {TEACHER_DATABASE_ROLE}")
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.current_active_teacher_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT profile.id
            FROM public.profiles AS profile
            WHERE profile.id = (SELECT auth.uid())
              AND profile.role = 'teacher'
              AND profile.status = 'active'
        $$
        """
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION paper_grading_private.current_active_teacher_id() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.current_active_teacher_id() "
        f"TO {TEACHER_DATABASE_ROLE}"
    )

    for table_name in BUSINESS_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table_name} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM anon")
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM authenticated")
        op.execute(
            f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM {TEACHER_DATABASE_ROLE}"
        )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {TEACHER_DATABASE_ROLE}")
    op.execute(f"GRANT SELECT ON TABLE public.profiles TO {TEACHER_DATABASE_ROLE}")
    op.execute(
        """
        CREATE POLICY profiles_teacher_select ON public.profiles
        FOR SELECT TO paper_grading_teacher_api
        USING (id = (SELECT paper_grading_private.current_active_teacher_id()))
        """
    )

    for table_name, privileges in TABLE_PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON TABLE public.{table_name} TO {TEACHER_DATABASE_ROLE}")
    for table_name, commands in TABLE_COMMANDS.items():
        for command in commands:
            create_owner_policy(table_name, command)


def downgrade() -> None:
    """恢复阶段三的默认拒绝 RLS 状态。"""

    for table_name, policy_name in reversed(POLICIES):
        op.execute(f"DROP POLICY {policy_name} ON public.{table_name}")
    op.execute("DROP FUNCTION paper_grading_private.current_active_teacher_id()")
    for table_name in BUSINESS_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(
            f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM {TEACHER_DATABASE_ROLE}"
        )
        op.execute(f"GRANT ALL PRIVILEGES ON TABLE public.{table_name} TO anon, authenticated")
    op.execute(f"REVOKE USAGE ON SCHEMA paper_grading_private FROM {TEACHER_DATABASE_ROLE}")
    op.execute("DROP SCHEMA paper_grading_private")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {TEACHER_DATABASE_ROLE}")
    op.execute(f"REVOKE {TEACHER_DATABASE_ROLE} FROM postgres")
    op.execute(f"DROP ROLE {TEACHER_DATABASE_ROLE}")
