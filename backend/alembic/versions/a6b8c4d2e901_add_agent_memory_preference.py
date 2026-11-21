"""add per-user agent memory preference

Revision ID: a6b8c4d2e901
Revises: f2c4e7a91b60
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6b8c4d2e901"
down_revision: Union[str, Sequence[str], None] = "f2c4e7a91b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("agent_history_max_turns", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "agent_history_max_turns")
