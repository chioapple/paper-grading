"""原子同步 Supabase Auth 邀请与教师 profile。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260714_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Auth 用户创建成功时，在同一数据库事务内建立受邀教师 profile。"""

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_create_invited_teacher()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            teacher_name text;
        BEGIN
            IF NEW.invited_at IS NULL THEN
                RETURN NEW;
            END IF;

            teacher_name := btrim(COALESCE(NEW.raw_user_meta_data ->> 'display_name', ''));
            IF teacher_name = '' THEN
                RAISE EXCEPTION 'invited teacher display_name is required'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO public.profiles (id, role, status, display_name)
            VALUES (NEW.id, 'teacher', 'invited', teacher_name);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER profiles_create_invited_teacher
        AFTER INSERT ON auth.users
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_create_invited_teacher()
        """
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.paper_grading_create_invited_teacher() FROM PUBLIC"
    )
    op.execute(
        """
        DO $paper_grading$
        DECLARE
            target_role text;
        BEGIN
            FOR target_role IN
                SELECT rolname
                FROM pg_catalog.pg_roles
                WHERE rolname IN ('anon', 'authenticated', 'service_role')
            LOOP
                EXECUTE pg_catalog.format(
                    'REVOKE EXECUTE ON FUNCTION '
                    'public.paper_grading_create_invited_teacher() FROM %I',
                    target_role
                );
            END LOOP;
        END;
        $paper_grading$
        """
    )


def downgrade() -> None:
    """移除阶段三 Auth 同步触发器。"""

    op.execute("DROP TRIGGER profiles_create_invited_teacher ON auth.users")
    op.execute("DROP FUNCTION public.paper_grading_create_invited_teacher()")
