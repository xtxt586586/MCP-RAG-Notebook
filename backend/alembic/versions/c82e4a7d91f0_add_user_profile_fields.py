"""add user profile fields

Revision ID: c82e4a7d91f0
Revises: b31c9a6e2f10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c82e4a7d91f0"
down_revision: Union[str, Sequence[str], None] = "b31c9a6e2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("bio", sa.String(length=1000), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "bio")
    op.drop_column("users", "gender")
    op.drop_column("users", "phone")
    op.drop_column("users", "display_name")
