"""Create runtime probe audit/projection and worker heartbeat tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_probes",
        sa.Column("probe_id", sa.String(36), primary_key=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("worker_role", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("worker_role IN ('dispatch', 'mirza')", name="probe_role"),
        sa.CheckConstraint("mode IN ('observe', 'review', 'automatic')", name="probe_mode"),
        sa.CheckConstraint("state IN ('waiting', 'completed')", name="probe_state"),
    )
    op.create_table(
        "runtime_probe_events",
        sa.Column("probe_id", sa.String(36), sa.ForeignKey("runtime_probes.probe_id"),
                  primary_key=True),
        sa.Column("phase", sa.String(20), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("phase IN ('started', 'completed')", name="probe_phase"),
    )
    op.create_table(
        "runtime_workers",
        sa.Column("worker_id", sa.String(36), primary_key=True),
        sa.Column("worker_role", sa.String(20), nullable=False),
        sa.Column("task_queue", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("worker_role IN ('dispatch', 'mirza')", name="worker_role"),
        sa.CheckConstraint("mode IN ('observe', 'review', 'automatic')", name="worker_mode"),
        sa.CheckConstraint("state IN ('running', 'paused', 'stopped')", name="worker_state"),
    )
    op.create_index("ix_runtime_workers_worker_role", "runtime_workers", ["worker_role"])


def downgrade() -> None:
    op.drop_index("ix_runtime_workers_worker_role", table_name="runtime_workers")
    op.drop_table("runtime_workers")
    op.drop_table("runtime_probe_events")
    op.drop_table("runtime_probes")

