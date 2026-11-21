"""Track knowledge graph rebuild progress."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "j5e8b3d0a721"
down_revision: Union[str, Sequence[str], None] = "i4d7a2c9f610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_rebuild_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "processed_task_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_rebuild_jobs_user_id", "graph_rebuild_jobs", ["user_id"])
    op.create_index(
        "ix_graph_rebuild_jobs_knowledge_base_id",
        "graph_rebuild_jobs",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_graph_rebuild_jobs_knowledge_base_id", table_name="graph_rebuild_jobs")
    op.drop_index("ix_graph_rebuild_jobs_user_id", table_name="graph_rebuild_jobs")
    op.drop_table("graph_rebuild_jobs")
