"""Synthetic ownership, recovery commands and minimal audit."""

import sqlalchemy as sa
from alembic import op

revision = "0006_fixture_lifecycle"
down_revision = "0005_provisioning_fixtures"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mirza_fixture_owned_scopes",
        sa.Column("scope_id", sa.String(64), primary_key=True),
        sa.Column(
            "world_id",
            sa.String(64),
            sa.ForeignKey("provisioning_fixture_worlds.world_id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
    )
    op.create_table(
        "mirza_fixture_owned_grants",
        sa.Column("grant_id", sa.String(64), primary_key=True),
        sa.Column(
            "scope_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_owned_scopes.scope_id"),
            nullable=False,
        ),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("desired", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(30), nullable=False),
    )
    op.create_table(
        "mirza_fixture_recovery_commands",
        sa.Column("command_id", sa.String(64), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "mirza_fixture_lifecycle_audit",
        sa.Column("audit_id", sa.String(64), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(64),
            sa.ForeignKey("mirza_fixture_fulfillments.operation_id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    for name in (
        "mirza_fixture_lifecycle_audit",
        "mirza_fixture_recovery_commands",
        "mirza_fixture_owned_grants",
        "mirza_fixture_owned_scopes",
    ):
        op.drop_table(name)
