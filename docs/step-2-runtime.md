# Step 2 — Local runtime verification

Status: completed on 2026-10-06. Policy planning is sufficient to start development;
remaining live integration/identity/approval checks stay open in the
[Step 1 register](step-1-decisions.md) and block affected production actions.

## Implemented

- FastAPI liveness, dependency/schema/worker readiness and runtime metadata.
- Separate dispatch and Mirza Temporal workers with distinct queues and
  independently configured mode/pause settings; observation defaults.
- Application PostgreSQL migrations and separate Temporal/visibility databases
  with a different database role/credential.
- JSON logging, validated UUID correlation IDs and credential-safe diagnostics.
- A synthetic workflow that persists an idempotent start phase, waits for a
  signal across worker restart, then records completion. There are no ticket
  intake, real classifier, provisioning or message-delivery implementations yet.
- Pinned direct/transitive dependencies, non-root application image, capped
  local Compose stack, ignored generated credentials, repository instructions,
  and startup/migration/backup/restore/worker operations documentation.

## Results

| Check | Result |
|---|---|
| Unit checks | 6 passed: dependency readiness, independent pause/modes, absent write endpoints, correlation IDs and secret-safe errors/logging |
| Ruff | Passed for application, migrations, scripts and unit tests |
| Dependency compatibility | `pip check` passed |
| Compose and shell validation | Passed |
| Compose build/start | Successful; API, PostgreSQL, Temporal and both workers healthy |
| Alembic/model consistency | No new upgrade operations detected |
| Dispatch restart probe | Waiting workflow recovered and completed; exactly 2 audit phases |
| Mirza restart probe | Waiting workflow recovered and completed; exactly 2 audit phases |
| Activity retry reconciliation | Duplicate completion/start writes neither duplicated events nor regressed completed state |

Verification commands:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app migrations scripts tests/unit
.venv/bin/python -m pip check
docker compose config --quiet
bash -n docker/init-databases.sh scripts/check_runtime.sh
COMPOSE_PARALLEL_LIMIT=1 docker compose build api
COMPOSE_PARALLEL_LIMIT=1 docker compose up -d --wait --wait-timeout 120
docker compose exec -T api python -m alembic check
bash scripts/check_runtime.sh
docker compose stop --timeout 20
```

The HTTP test client needed execution outside the restricted sandbox to wake its
event-loop thread. Unit checks use mocks; runtime checks used only the local
Compose services. The test client reports an upstream deprecation warning for
its HTTPX integration; checks passed.

## Resource observations and cleanup

The steady-service caps total **1.25 GiB RAM and 1.75 CPUs**. Builds/checks ran
sequentially; no Temporal UI or extra services were started. Pinned Python and
PostgreSQL base images already cached locally were reused.

Observed full-stack snapshots used about **432–452 MiB RAM**. After the second
restart probe, CPU usage totaled about **1.25% of one CPU** in that sample. These
are sampled local synthetic-workload observations, not a production capacity or
peak-usage estimate. Migration has its own cap and exits before application startup.

The project's containers were stopped after verification; the local PostgreSQL
volume and image remain for the next step. No unrelated containers were stopped.
No production tickets, grants, notifications or credentials were used. No commit
or push was made.

## Next step

Step 3 defines typed ticket/action contracts, durable event ordering, action IDs,
approval/clarification state and reminder delivery records. The synthetic probe
is only a runtime check; it is not the business implementation of the 100 policy
examples or the daily 10:00 AM reminder schedule. Live connector discovery and
historical examples remain tracked for the later production gates.
