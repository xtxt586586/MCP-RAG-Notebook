"""add conversation archive state

Revision ID: f2c4e7a91b60
Revises: e7f9a1c2d3b4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c4e7a91b60"
down_revision: Union[str, Sequence[str], None] = "e7f9a1c2d3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_conversations_archived_at"),
        "conversations",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_conversations_archived_at"),
        table_name="conversations",
    )
    op.drop_column("conversations", "archived_at")
