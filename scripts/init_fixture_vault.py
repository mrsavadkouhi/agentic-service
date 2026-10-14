"""Generate a private, local simulation key without printing or replacing it."""

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    args.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(Fernet.generate_key() + b"\n")
    print("Created private local fixture vault key; value is not printed.")


if __name__ == "__main__":
    main()
