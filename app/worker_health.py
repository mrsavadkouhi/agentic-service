import argparse
import json
import time
from pathlib import Path


def marker_path(role: str) -> Path:
    return Path(f"/tmp/agentic-{role}-health.json")


def is_healthy(role: str) -> bool:
    try:
        payload = json.loads(marker_path(role).read_text())
        return (
            payload["role"] == role
            and payload["state"] in {"running", "paused"}
            and 0 <= time.time() - payload["timestamp"] < 20
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["dispatch", "mirza"], required=True)
    args = parser.parse_args()
    raise SystemExit(0 if is_healthy(args.role) else 1)


if __name__ == "__main__":
    main()

