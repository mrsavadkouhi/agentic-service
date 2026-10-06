"""Verify the configured SELECT-only map without printing credentials or rows."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.offboarding import Offboarding  # noqa: E402
from app.connectors.onboarding import Onboarding  # noqa: E402


async def verify(ticket_id, process="offboarding"):
    sources = {
        "offboarding": ("AGENTIC_OFFBOARDING_DATABASE_URL", Offboarding),
        "onboarding": ("AGENTIC_ONBOARDING_DATABASE_URL", Onboarding),
    }
    setting, reader_type = sources[process]
    dsn = os.environ.get(setting)
    if not dsn:
        print(json.dumps({"status": "unavailable", "reason": "connector_not_configured"}))
        return 1
    result = await reader_type(SecretStr(dsn), contract="installed").read(ticket_id)
    print(json.dumps({
        "status": result.status,
        "reason": result.reason_code,
        "matching_process_count": len(result.data) if result.data is not None else None,
        "grant_context_verified": False,
    }))
    return 0 if result.status == "ok" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-id", required=True)
    parser.add_argument("--process", choices=("offboarding", "onboarding"), default="offboarding")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(verify(args.ticket_id, args.process)))


if __name__ == "__main__":
    main()
