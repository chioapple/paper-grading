"""兼容 Supabase Auth 分两步写入邀请状态。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅在邀请状态首次出现时创建受邀教师 profile。"""

    op.execute(
        """
        CREATE TRIGGER profiles_create_invited_teacher_on_invite
        AFTER UPDATE OF invited_at ON auth.users
        FOR EACH ROW
        WHEN (OLD.invited_at IS NULL AND NEW.invited_at IS NOT NULL)
        EXECUTE FUNCTION public.paper_grading_create_invited_teacher()
        """
    )


def downgrade() -> None:
    """恢复仅监听 Auth 用户插入的上一版触发器。"""

    op.execute("DROP TRIGGER profiles_create_invited_teacher_on_invite ON auth.users")
