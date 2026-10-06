import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.contracts.context import Evidence, ReadResult


class ReadFailure(Exception):
    def __init__(self, status="unavailable", reason="read_unavailable"):
        self.status, self.reason = status, reason
        super().__init__(reason)


class ReadOnlyHTTP:
    """Fixed-origin GET transport; no redirects, arbitrary URLs or write methods."""

    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        paths: tuple[str, ...],
        *,
        auth_header="Authorization",
        transport=None,
        allow_http=False,
        attempts=3,
        timeout=8,
        max_bytes=2_000_000,
        sleep=asyncio.sleep,
    ):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Connector requires a fixed HTTP origin")
        if (
            url.scheme == "http"
            and not allow_http
            and url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Non-local HTTP requires explicit configuration")
        if attempts not in {1, 2, 3}:
            raise ValueError("Read retries must be bounded")
        value = token.get_secret_value()
        # HTTPX's INFO message includes query parameters (notably key/info).
        # Transport diagnostics must never emit credential-bearing URLs.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        headers = {
            auth_header: value if auth_header == "authtoken" else "Bearer " + value,
            "Accept": "application/vnd.manageengine.sdp.v3+json"
            if auth_header == "authtoken"
            else "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.paths, self.attempts, self.max_bytes, self.sleep = paths, attempts, max_bytes, sleep

    async def close(self):
        await self.client.aclose()

    async def get(self, path: str, params=None, *, missing_is_not_found=False):
        if not any(re.fullmatch(pattern, path) for pattern in self.paths):
            raise ReadFailure("invalid", "read_endpoint_not_allowed")
        for attempt in range(self.attempts):
            retry = False
            try:
                async with self.client.stream("GET", path, params=params) as response:
                    code = response.status_code
                    if code in {429, 502, 503, 504}:
                        retry = True
                    elif code == 404 and missing_is_not_found:
                        raise ReadFailure("not_found", "resource_not_found")
                    elif code in {404, 405, 501}:
                        raise ReadFailure("unsupported", "endpoint_unavailable")
                    elif code != 200:
                        raise ReadFailure("unavailable", "http_read_denied")
                    else:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                raise ReadFailure("incomplete", "response_too_large")
                        try:
                            return json.loads(body)
                        except ValueError:
                            raise ReadFailure("invalid", "invalid_json") from None
            except (httpx.TimeoutException, httpx.NetworkError):
                retry = True
            if retry and attempt + 1 < self.attempts:
                await self.sleep(min(2**attempt, 2))
        raise ReadFailure("unavailable", "read_retry_exhausted")


def evidence(component, resource, complete=False, data=None, contract="candidate"):
    from app.contracts.tickets import stable_id

    return Evidence(
        component=component,
        resource=resource,
        observed_at=datetime.now(UTC),
        complete=complete,
        contract=contract,
        digest=stable_id(json.dumps(data, sort_keys=True, default=str))
        if data is not None
        else None,
    )


def ok(component, resource, data, contract="candidate"):
    return ReadResult(
        status="ok", data=data, evidence=evidence(component, resource, True, str(data), contract)
    )


def failed(component, resource, exc):
    if not isinstance(exc, ReadFailure):
        exc = ReadFailure("invalid", "unexpected_response_shape")
    return ReadResult(
        status=exc.status, reason_code=exc.reason, evidence=evidence(component, resource)
    )
