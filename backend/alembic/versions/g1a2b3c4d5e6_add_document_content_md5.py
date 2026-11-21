"""Add content hash used for original-project style deduplication."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_md5", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_documents_content_md5",
        "documents",
        ["content_md5"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_content_md5", table_name="documents")
    op.drop_column("documents", "content_md5")
