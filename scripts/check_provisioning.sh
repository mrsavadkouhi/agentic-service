#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose config --quiet
probe_directory=$(mktemp -d /tmp/agentic-provisioning-verify.XXXXXX)
probe_succeeded=false
cleanup() {
    docker compose stop || true
    if [[ "$probe_succeeded" == true ]]; then
        rm -- "$probe_directory/run.json" "$probe_directory/vault-key"
        rmdir -- "$probe_directory"
    else
        printf 'Private verification state retained at %s; native checks remain incomplete.\n' "$probe_directory"
    fi
}
trap cleanup EXIT
.venv/bin/python scripts/init_fixture_vault.py "$probe_directory/vault-key"
runner=(docker compose run --rm --no-deps --user "$(id -u):$(id -g)"
    --volume "$probe_directory:/verify-state" --entrypoint python
    mirza-worker -m scripts.verify_provisioning)

"${runner[@]}" start --state-file /verify-state/run.json --vault-key-file /verify-state/vault-key
docker compose stop api dispatch-worker mirza-worker temporal
docker compose restart postgres
docker compose up -d --wait --wait-timeout 180 postgres temporal
"${runner[@]}" finish --state-file /verify-state/run.json --vault-key-file /verify-state/vault-key
docker compose up -d --wait --wait-timeout 180 api dispatch-worker mirza-worker
docker compose exec -T api python -m alembic check
mapfile -t container_ids < <(docker compose ps -q)
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "${container_ids[@]}"
probe_succeeded=true
