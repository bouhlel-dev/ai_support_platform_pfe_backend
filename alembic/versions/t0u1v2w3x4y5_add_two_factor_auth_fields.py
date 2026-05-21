"""
Add two_factor_enabled and totp_secret fields to users table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t0u1v2w3x4y5"
down_revision: Union[str, None] = "s9t0u1v2w3x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("totp_secret", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "two_factor_enabled")
