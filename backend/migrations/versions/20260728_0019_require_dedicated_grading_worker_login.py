"""允许评分 Worker 使用独立最小登录角色。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0019"
down_revision: str | None = "20260726_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """开放既有最小 Worker 角色登录和评分写 Storage 所需配额函数。"""

    op.execute("ALTER ROLE paper_grading_worker LOGIN NOINHERIT NOBYPASSRLS")
    op.execute("GRANT USAGE ON SCHEMA paper_grading_private TO paper_grading_worker")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint) "
        "TO paper_grading_worker"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.finalize_storage_growth(uuid, text) "
        "TO paper_grading_worker"
    )


def downgrade() -> None:
    """回退时关闭该角色直接登录。"""

    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "paper_grading_private.finalize_storage_growth(uuid, text) "
        "FROM paper_grading_worker"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint) "
        "FROM paper_grading_worker"
    )
    op.execute("REVOKE USAGE ON SCHEMA paper_grading_private FROM paper_grading_worker")
    op.execute("ALTER ROLE paper_grading_worker NOLOGIN NOINHERIT NOBYPASSRLS")
