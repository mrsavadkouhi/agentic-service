# agentic-service

Internal ICT workflow runtime for Helpdesk support-group correction and the eight
approved Mirza jobs. The confirmed behavior is in [plan.md](plan.md), the
[decision register](docs/step-1-decisions.md), and the
[service ownership catalog](docs/service-ownership.md).

Steps 2–3 provide the local runtime, authenticated normalized intake, closed ticket
contracts, deterministic policy gates, durable Temporal execution, action/audit
records and daily reminder intents. See [Step 3 execution](docs/step-3-execution.md).
Step 4 adds optional read-only connectors and an operator-only context endpoint;
installed Mirza and basic ServiceDesk reads are verified. Approval/process
authority and other live contracts remain pending. See
[read-only integration context](docs/step-4-read-connectors.md).
Classification, provisioning and Mattermost delivery belong to later steps.
Local startup needs no production credentials.

## Start locally

```bash
python3 scripts/init_local_env.py
COMPOSE_PARALLEL_LIMIT=1 docker compose build api
COMPOSE_PARALLEL_LIMIT=1 docker compose up -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:18080/health/ready
bash scripts/check_runtime.sh
docker compose stop
```

The generator preserves existing credentials and adds missing local API tokens
with mode 0600. `.env` is ignored by Git and the image build. Published ports bind
only to localhost: API 18080, PostgreSQL 15432 and Temporal 17233. Change the
corresponding `AGENTIC_*_PORT` settings if those ports are already occupied.

The persistent volume contains separate `agentic`, `temporal` and
`temporal_visibility` databases. Application workers receive only the application
database credential; Temporal receives its own database credential. Database
initialization runs once on a new volume, and the migration service upgrades only
the application database before the API/workers start.

`/health/live` checks API liveness. `/health/ready` checks the migrated application
schema, Temporal namespace and recent heartbeats for enabled workers; it returns
503 if a dependency is unavailable. `/runtime` reports independent workflow
modes/pauses and the implemented external write capabilities, currently empty.
Logs are JSON, and the API validates or generates `X-Correlation-ID` UUIDs.

`scripts/check_runtime.sh` starts one synthetic probe at a time, restarts its
worker while the probe waits, signals it to finish, then checks that the two audit
phases were recorded exactly once. It also checks that retrying activities cannot
regress a completed projection. No ServiceDesk, AD, Mirza or Mattermost calls occur.

## Resource limits

| Service | RAM cap | CPU cap |
|---|---:|---:|
| PostgreSQL | 192 MiB | 0.25 |
| Temporal | 512 MiB | 0.75 |
| API | 192 MiB | 0.25 |
| Dispatch worker | 192 MiB | 0.25 |
| Mirza worker | 192 MiB | 0.25 |

The steady runtime is capped at 1.25 GiB and 1.75 CPUs. The short migration service
has a 192 MiB/0.25 CPU cap and exits before the API/workers start. Builds use
prebuilt Python wheels and run sequentially; Docker build processes have separate
resource accounting. There is no Temporal UI or extra observability stack.
Inspect usage with `docker compose stats --no-stream`; stop this project with
`docker compose stop` when finished. Stop preserves the volume and does not affect
other projects.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pytest
.venv/bin/ruff check app migrations scripts tests/unit
docker compose config --quiet
```

`requirements.txt` contains direct pins; `requirements.lock` also pins transitive
runtime dependencies. The development lock adds the verification tools. Resolve
and review both locks when changing dependencies. The Docker image includes only
runtime dependencies and runs as a non-root user with a read-only filesystem.

`app/workflows` contains deterministic Temporal workflow code. External I/O and
database writes belong in `app/activities`. `app/storage` holds application audit,
projections and migrations. Temporal is the execution owner; database projections
do not resume workflows independently.

Workflow replay/restart follows the
[Temporal Python SDK](https://docs.temporal.io/develop/python/best-practices/testing-suite).
The API uses FastAPI's
[lifespan management](https://fastapi.tiangolo.com/advanced/events/), and application
storage uses the
[SQLAlchemy psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).

For synthetic ticket/action verification, use the explicit `compose.verify.yaml`
override and `bash scripts/check_tickets.sh`, as described in the Step 3 guide.
Base Compose never enables the fixture connector. Its API accepts normalized
production inputs for local observation only after a trusted connector and
authoritative catalog are supplied in later steps.

See [runtime operations](docs/runtime-operations.md) for configuration, migrations,
backup/restore and worker deployment. Live integration checks left from discovery
remain tracked in the decision register and block affected production writes.
