#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f compose.yaml -f compose.verify.yaml)
# Run only with the explicit local synthetic override. Existing resource caps apply.
for role in dispatch mirza; do
    state_file="/tmp/agentic-ticket-${role}-${RANDOM}.json"
    "${compose[@]}" exec -T api python -m scripts.verify_tickets start \
        --role "$role" --state-file "$state_file"
    "${compose[@]}" restart "${role}-worker"
    "${compose[@]}" exec -T api python -m scripts.verify_tickets finish \
        --role "$role" --state-file "$state_file"
    "${compose[@]}" exec -T api rm "$state_file"
    mapfile -t container_ids < <("${compose[@]}" ps -q)
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "${container_ids[@]}"
done
"${compose[@]}" exec -T api python -m scripts.verify_tickets gates
"${compose[@]}" exec -T api python -m alembic check
