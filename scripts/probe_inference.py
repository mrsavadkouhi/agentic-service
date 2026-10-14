"""Read served model names using an inference credential held only in memory."""

import argparse
import asyncio
import getpass
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import SecretStr  # noqa: E402

from app.connectors.http import ReadFailure, ReadOnlyHTTP  # noqa: E402


async def probe(endpoint, token):
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/", "/v1", "/v1/", "/api/v1", "/api/v1/"}
    ):
        raise ValueError("Use a fixed HTTPS inference endpoint")
    model_path = (url.path.rstrip("/") or "/v1") + "/models"
    http = ReadOnlyHTTP(
        f"https://{url.netloc}", SecretStr(token), (re.escape(model_path),),
        attempts=1, timeout=10
    )
    statuses = []

    async def observed_response(response):
        statuses.append(response.status_code)

    http.client.event_hooks["response"].append(observed_response)
    try:
        data = await http.get(model_path)
        rows = data.get("data")
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("Invalid served model response")
        names = [row.get("id") for row in rows if isinstance(row, dict)]
        if len(names) != len(rows) or any(
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", name)
            for name in names
        ):
            raise ValueError("Invalid served model names")
        print(
            json.dumps(
                {
                    "inference_read_available": True,
                    "served_models": sorted(set(names)),
                    "model_calls": 0,
                    "configuration_changes": 0,
                }
            )
        )
        return 0
    except ReadFailure as exc:
        print(
            json.dumps(
                {
                    "inference_read_available": False,
                    "reason_code": exc.reason,
                    "http_status": statuses[-1] if statuses else None,
                }
            )
        )
        return 1
    finally:
        await http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    try:
        token = (
            getpass.getpass("Inference token (not stored): ")
            if sys.stdin.isatty()
            else sys.stdin.readline().strip()
        )
        if not token or len(token) > 500:
            raise ValueError("Inference token unavailable")
        raise SystemExit(asyncio.run(probe(args.endpoint, token)))
    except Exception as exc:
        print(json.dumps({"inference_read_available": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
