"""Create PostgreSQL-backed knowledge graph tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h3c8a1d2e9f0"
down_revision: Union[str, Sequence[str], None] = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "knowledge_base_id", "normalized_name", "entity_type",
            name="uq_graph_entities_scope_name_type",
        ),
    )
    op.create_index(
        "ix_graph_entities_scope_type",
        "graph_entities",
        ["user_id", "knowledge_base_id", "entity_type"],
    )

    op.create_table(
        "graph_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_mentions_source",
        "graph_mentions",
        ["user_id", "knowledge_base_id", "source_type", "source_id"],
    )
    op.create_index("ix_graph_mentions_entity", "graph_mentions", ["entity_id"])

    op.create_table(
        "graph_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_relations_scope_source",
        "graph_relations",
        ["user_id", "knowledge_base_id", "source_entity_id"],
    )
    op.create_index("ix_graph_relations_target", "graph_relations", ["target_entity_id"])
    op.create_index(
        "ix_graph_relations_evidence_source",
        "graph_relations",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_graph_relations_evidence_source", table_name="graph_relations")
    op.drop_index("ix_graph_relations_target", table_name="graph_relations")
    op.drop_index("ix_graph_relations_scope_source", table_name="graph_relations")
    op.drop_table("graph_relations")
    op.drop_index("ix_graph_mentions_entity", table_name="graph_mentions")
    op.drop_index("ix_graph_mentions_source", table_name="graph_mentions")
    op.drop_table("graph_mentions")
    op.drop_index("ix_graph_entities_scope_type", table_name="graph_entities")
    op.drop_table("graph_entities")
