"""Create ignored local-only credentials without overwriting an existing .env."""

import os
import secrets
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parents[1] / ".env"
    admin, app, temporal = (secrets.token_hex(24) for _ in range(3))
    contents = (
        "# Local development only; generated independently of production credentials.\n"
        f"POSTGRES_PASSWORD={admin}\nAPP_DB_PASSWORD={app}\nTEMPORAL_DB_PASSWORD={temporal}\n"
        f"AGENTIC_DATABASE_URL=postgresql+psycopg://agentic:{app}@postgres:5432/agentic\n"
        "AGENTIC_TEMPORAL_ADDRESS=temporal:7233\nAGENTIC_TEMPORAL_NAMESPACE=agentic\n"
        "AGENTIC_DISPATCH_MODE=observe\nAGENTIC_MIRZA_MODE=observe\n"
        "AGENTIC_DISPATCH_PAUSED=false\nAGENTIC_MIRZA_PAUSED=false\n"
        "AGENTIC_API_PORT=18080\nAGENTIC_POSTGRES_PORT=15432\nAGENTIC_TEMPORAL_PORT=17233\n"
    )
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env preserved.")
        return
    with os.fdopen(fd, "w") as stream:
        stream.write(contents)
    print("Created local-only .env with mode 0600; credential values are not printed.")


if __name__ == "__main__":
    main()

