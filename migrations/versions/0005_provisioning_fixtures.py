"""Isolated synthetic fulfillment, claim, secret and delivery records."""

import sqlalchemy as sa
from alembic import op

revision = "0005_provisioning_fixtures"
down_revision = "0004_mirza_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provisioning_fixture_worlds",
        sa.Column("world_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "mirza_fixture_fulfillments",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column(
            "world_id",
            sa.String(64),
            sa.ForeignKey("provisioning_fixture_worlds.world_id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "mirza_fixture_steps",
        sa.Column("step_id", sa.String(64), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("claim_ref", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "mirza_fixture_secrets",
        sa.Column("secret_ref", sa.String(80), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "mirza_fixture_messages",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("recipient_ref", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
    )


def downgrade():
    for name in (
        "mirza_fixture_messages",
        "mirza_fixture_secrets",
        "mirza_fixture_steps",
        "mirza_fixture_fulfillments",
        "provisioning_fixture_worlds",
    ):
        op.drop_table(name)
