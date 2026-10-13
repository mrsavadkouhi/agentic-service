"""Observation proposals and daily inference reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0003_observations"
down_revision = "0002_tickets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ticket_observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(200), nullable=False),
        sa.Column("ticket_id", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("budget_day", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ticket_observations_ticket_id", "ticket_observations", ["ticket_id"])
    op.create_table(
        "inference_budgets",
        sa.Column("budget_day", sa.Date(), primary_key=True),
        sa.Column("reserved_usd", sa.Numeric(12, 6), nullable=False),
    )


def downgrade():
    op.drop_table("inference_budgets")
    op.drop_index("ix_ticket_observations_ticket_id", table_name="ticket_observations")
    op.drop_table("ticket_observations")
