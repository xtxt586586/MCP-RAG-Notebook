"""add memory reset and summary progress state

Revision ID: c8e1f4a2b703
Revises: b7d9e5f3a102
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e1f4a2b703"
down_revision: Union[str, Sequence[str], None] = "b7d9e5f3a102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "memory_summary_turns",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("memory_reset_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "memory_reset_at")
    op.drop_column("conversations", "memory_summary_turns")
