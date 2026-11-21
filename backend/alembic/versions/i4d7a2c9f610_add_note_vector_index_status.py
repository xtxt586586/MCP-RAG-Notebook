"""Persist note vector indexing status."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i4d7a2c9f610"
down_revision: Union[str, Sequence[str], None] = "h3c8a1d2e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column(
            "vector_index_status",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "notes",
        sa.Column("vector_index_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notes", "vector_index_error")
    op.drop_column("notes", "vector_index_status")
