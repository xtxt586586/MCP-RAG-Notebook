from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4a7e8c91b20"
down_revision: Union[str, Sequence[str], None] = "c82e4a7d91f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["notes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_review_events_note_id",
        "review_events",
        ["note_id"],
    )
    op.create_index(
        "ix_review_events_user_id",
        "review_events",
        ["user_id"],
    )
    op.create_index(
        "ix_review_events_reviewed_at",
        "review_events",
        ["reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_events_reviewed_at",
        table_name="review_events",
    )
    op.drop_index(
        "ix_review_events_user_id",
        table_name="review_events",
    )
    op.drop_index(
        "ix_review_events_note_id",
        table_name="review_events",
    )
    op.drop_table("review_events")
