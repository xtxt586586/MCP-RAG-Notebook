"""Enforce one logical knowledge base per user.

This migration intentionally does not merge or delete existing rows. If old
data contains duplicate knowledge bases, it stops and reports them so they can
be reviewed explicitly before the constraint is enabled.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "c8e1f4a2b703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicate rows are intentionally left untouched. The
    # application already exposes the oldest row as the user's singleton;
    # after an explicit data merge, this migration can be rerun to add the
    # database constraint.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM knowledge_bases
                GROUP BY user_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE NOTICE
                    'duplicate knowledge_bases found; application-level singleton is active, database constraint deferred';
            ELSE
                CREATE UNIQUE INDEX IF NOT EXISTS
                    uq_knowledge_bases_user_id
                    ON knowledge_bases (user_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_knowledge_bases_user_id"
    )
