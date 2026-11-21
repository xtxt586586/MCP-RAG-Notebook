"""add persisted conversation memory summary

Revision ID: b7d9e5f3a102
Revises: a6b8c4d2e901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d9e5f3a102"
down_revision: Union[str, Sequence[str], None] = "a6b8c4d2e901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("memory_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "memory_summary")
