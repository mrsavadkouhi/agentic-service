# Runtime operations

The Compose stack is a local development runtime. Steps 2–3 provide runtime probes
and a ticket execution foundation with an opt-in synthetic connector. Production TLS, identity integration,
restricted administrator connectors, secret handling and rollout are later work.

## Modes and pause controls

`AGENTIC_DISPATCH_MODE` and `AGENTIC_MIRZA_MODE` accept `observe`, `review` and
`automatic`, defaulting to `observe`. Only the explicit local verification override
can execute synthetic database effects. No mode enables a production write
connector. Check `/runtime`, which reports `external_write_capabilities: []` and
the synthetic connector switch. See [Step 3](step-3-execution.md) for authenticated
intake, revision-checked cancellation, action recovery and reminder intent semantics.

Each role has its own task queue and `AGENTIC_DISPATCH_PAUSED` or
`AGENTIC_MIRZA_PAUSED` setting. A paused worker keeps a paused heartbeat but polls
no workflow tasks. A pending synthetic workflow remains durable in Temporal and
can resume after the worker is unpaused. Production emergency-pause semantics
for in-flight privileged activities must be implemented before adding those tools.

After changing application environment settings, recreate the affected services:

```bash
docker compose up -d --force-recreate api dispatch-worker mirza-worker
```

Restart alone does not refresh environment settings. Initial database passwords
are applied only when creating a new volume; changing `.env` does not rotate
credentials stored in an existing PostgreSQL volume. Never print the expanded
Compose configuration or container environment when troubleshooting credentials.

## Migrations

The `migrate` service runs `alembic upgrade head` once before API/worker startup.
To apply a later reviewed migration, stop application writers first:

```bash
docker compose stop api dispatch-worker mirza-worker
docker compose run --rm --no-deps migrate
docker compose up -d api dispatch-worker mirza-worker
```

Readiness requires the expected schema revision. Startup does not call
`create_all`. Review downgrade/data-loss behavior before using a downgrade; take
a backup first. Temporal schemas are managed by the pinned Temporal setup image,
not by application Alembic migrations.

## Backups and restore

For this small local stack, stop writers while taking a coordinated logical
snapshot. Backup files can contain application/workflow data and remain outside Git.

```bash
mkdir -p backups
chmod 700 backups
docker compose stop api dispatch-worker mirza-worker temporal
docker compose exec -T postgres pg_dump -U postgres -Fc agentic > backups/agentic.dump
docker compose exec -T postgres pg_dump -U postgres -Fc temporal > backups/temporal.dump
docker compose exec -T postgres pg_dump -U postgres -Fc temporal_visibility > backups/temporal_visibility.dump
chmod 600 backups/*.dump
docker compose up -d temporal api dispatch-worker mirza-worker
```

Restore into the same compatible database/server versions and role setup, with
writers stopped. These commands replace the corresponding application/workflow
data, so choose the intended backup before running them:

```bash
docker compose stop api dispatch-worker mirza-worker temporal
docker compose exec -T postgres pg_restore -U postgres --clean --if-exists -d agentic < backups/agentic.dump
docker compose exec -T postgres pg_restore -U postgres --clean --if-exists -d temporal < backups/temporal.dump
docker compose exec -T postgres pg_restore -U postgres --clean --if-exists -d temporal_visibility < backups/temporal_visibility.dump
docker compose up -d temporal api dispatch-worker mirza-worker
```

Verify `/health/ready`, then run a synthetic probe. Do not delete the persistent
volume as routine cleanup. Production backup/PITR procedures require a separate
deployment review once real data is introduced.

## Workers and recovery

All application processes use the same image with different commands:

```bash
python -m app.worker --role dispatch
python -m app.worker --role mirza
```

Workers validate the application schema, poll their own queue, and update a
heartbeat every five seconds. A failed worker/heartbeat exits for the operator or
deployment platform to restart. The Compose scaffold has no uncontrolled restart
loop. Worker health probes read an ephemeral local marker; API readiness also
requires a recent database heartbeat with the expected queue and mode.

Temporal retains pending workflow history across worker restarts. Probe activities
use transactional audit keys and lock the projection, preventing duplicate audit
phases or regression on a delayed activity retry. Correlation IDs follow a probe
through worker logs and audit rows. Step 3 adds ticket/approval contracts, stable
action receipts and history replay checks; installed API verification and real
execution/delivery remain later work.

To deploy workers later, provision separate least-privilege secrets per role and
the authenticated Temporal/PostgreSQL endpoints. Do not put live keys in workflow
arguments, logs, environment examples or audit projections. Review workflow
compatibility before replacing code that owns existing history.
