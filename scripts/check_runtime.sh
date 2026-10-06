#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Synthetic local workflows only. Run each worker check sequentially.
for role in dispatch mirza; do
    probe_state="/tmp/agentic-probe-${role}-$(date +%s)-${RANDOM}.json"
    docker compose exec -T api python -m scripts.verify_runtime start \
        --role "$role" --state-file "$probe_state"
    docker compose restart "${role}-worker"
    docker compose exec -T api python -m scripts.verify_runtime finish \
        --role "$role" --state-file "$probe_state"
    docker compose exec -T api rm "$probe_state"
    mapfile -t container_ids < <(docker compose ps -q)
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' \
        "${container_ids[@]}"
done
