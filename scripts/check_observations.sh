#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Local observation stack only. No connector writes or live inference.
docker compose config --quiet
probe_directory=$(mktemp -d /tmp/agentic-observation-verify.XXXXXX)
probe_succeeded=false
probe_started=false
cleanup() {
    if [[ "$probe_started" == true ]]; then
        docker compose stop || true
    fi
    if [[ "$probe_succeeded" == true ]]; then
        rm -- "$probe_directory/run.json"
        rmdir -- "$probe_directory"
    else
        printf 'Verification state retained at %s; native checks remain incomplete.\n' "$probe_directory"
    fi
}
trap cleanup EXIT
runner=(docker compose run --rm --no-deps --user "$(id -u):$(id -g)"
    --volume "$probe_directory:/verify-state" --entrypoint python
    api -m scripts.verify_observations)

"${runner[@]}" start --state-file /verify-state/run.json
probe_started=true
docker compose stop api dispatch-worker mirza-worker temporal
docker compose restart postgres
docker compose up -d --wait --wait-timeout 180 postgres temporal
"${runner[@]}" finish --state-file /verify-state/run.json
docker compose up -d --wait --wait-timeout 180 api dispatch-worker mirza-worker
docker compose exec -T api python -m alembic check
mapfile -t container_ids < <(docker compose ps -q)
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "${container_ids[@]}"
probe_succeeded=true
