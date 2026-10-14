"""Authenticated encryption inside the privileged boundary; never log plaintext."""

import hmac
import json
import stat
from pathlib import Path

from cryptography.fernet import Fernet


class SecretCipher:
    def __init__(self, key: bytes):
        self._cipher = Fernet(key)

    @classmethod
    def from_file(cls, path: Path):
        details = path.stat()
        if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077 or details.st_size > 128:
            raise ValueError("Private vault key file required")
        return cls(path.read_bytes().strip())

    def seal(self, binding: str, value: dict) -> bytes:
        return self._cipher.encrypt(
            json.dumps({"binding": binding, "value": value}, sort_keys=True).encode()
        )

    def open(self, binding: str, ciphertext: bytes) -> dict:
        try:
            envelope = json.loads(self._cipher.decrypt(ciphertext))
            if not hmac.compare_digest(envelope["binding"], binding):
                raise ValueError
            if not isinstance(envelope["value"], dict):
                raise ValueError
            return envelope["value"]
        except Exception:
            raise ValueError("Secret unavailable or binding mismatch") from None
