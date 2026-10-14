"""Isolated Mirza policy previews and pinned review identities."""

import sqlalchemy as sa
from alembic import op

revision = "0004_mirza_reviews"
down_revision = "0003_observations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mirza_review_heads",
        sa.Column("owner_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
    )
    op.create_table(
        "mirza_policy_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(200), nullable=False),
        sa.Column("ticket_id", sa.String(200), nullable=False),
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mirza_policy_reviews_ticket_id", "mirza_policy_reviews", ["ticket_id"])


def downgrade():
    op.drop_index("ix_mirza_policy_reviews_ticket_id", table_name="mirza_policy_reviews")
    op.drop_table("mirza_policy_reviews")
    op.drop_table("mirza_review_heads")
