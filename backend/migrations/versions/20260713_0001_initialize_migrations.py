"""初始化迁移版本链。"""

from collections.abc import Sequence

revision: str = "20260713_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """阶段 1 不创建业务表。"""


def downgrade() -> None:
    """阶段 1 没有业务表需要回退。"""
