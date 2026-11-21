from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b31c9a6e2f10"
down_revision: Union[str, Sequence[str], None] = "ec5103cfa3a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_records",
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
        sa.Column(
            "last_reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "review_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_review_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "interval_days",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint(
            "note_id",
            name="uq_review_records_note_id",
        ),
    )

    op.create_index(
        "ix_review_records_user_id",
        "review_records",
        ["user_id"],
    )

    op.create_index(
        "ix_review_records_next_review_at",
        "review_records",
        ["next_review_at"],
    )

    # 为已有笔记创建首次回顾记录，默认明天可回顾。
    op.execute(
        sa.text(
            """
            INSERT INTO review_records
            (
                id,
                note_id,
                user_id,
                review_count,
                next_review_at,
                interval_days
            )
            SELECT
                gen_random_uuid(),
                id,
                user_id,
                0,
                now() + interval '1 day',
                1
            FROM notes
            ON CONFLICT (note_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_records_next_review_at",
        table_name="review_records",
    )
    op.drop_index(
        "ix_review_records_user_id",
        table_name="review_records",
    )
    op.drop_table("review_records")
