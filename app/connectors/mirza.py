import json
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import SecretStr

from app.connectors.http import ReadFailure, failed, ok
from app.contracts.context import (
    BudgetRead,
    MirzaInventory,
    MirzaKey,
    MirzaTeam,
    MirzaUser,
    ReasoningRead,
)
from app.contracts.tickets import stable_id

LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh")
ALIASES = {
    "off": "none",
    "disabled": "none",
    "disable": "none",
    "false": "none",
    "min": "minimal",
    "minimum": "minimal",
    "lowest": "minimal",
    "med": "medium",
    "normal": "medium",
    "standard": "medium",
    "balanced": "medium",
    "extra high": "xhigh",
    "extra-high": "xhigh",
    "extra_high": "xhigh",
    "veryhigh": "xhigh",
    "very high": "xhigh",
    "very-high": "xhigh",
    "max": "xhigh",
    "maximum": "xhigh",
    "highest": "xhigh",
    "ultra": "xhigh",
}


def highest(value):
    if value is None:
        return None
    values = value if isinstance(value, list) else [value]
    known = []
    for item in values:
        text = str(item).strip().casefold()
        if isinstance(item, bool) or text in {"", "default", "auto", "unset"}:
            continue
        level = ALIASES.get(text, text)
        if level not in LEVELS:
            raise ReadFailure("invalid", "unrecognized_reasoning_grant")
        known.append(level)
    return max(known, key=LEVELS.index) if known else None


def reasoning(row):
    meta = row.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta)
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ReadFailure("invalid", "metadata_shape")
    models = meta.get("reasoning_models", {})
    if not isinstance(models, dict):
        raise ReadFailure("invalid", "reasoning_models_shape")
    grants = {str(m).strip().casefold(): highest(v) for m, v in models.items()}
    return ReasoningRead(
        all_models=highest(
            [
                x
                for x in (highest(meta.get("reasoning_levels")), grants.pop("*", None))
                if x is not None
            ]
        ),
        models={m: v for m, v in grants.items() if v is not None},
    )


def effective_reasoning(rows, default="medium"):
    if default not in LEVELS:
        raise ReadFailure("invalid", "reasoning_default_unverified")
    base = highest([default] + [r.all_models for r in rows if r.all_models is not None])
    names = {name for row in rows for name in row.models}
    return ReasoningRead(
        all_models=base,
        models={
            name: highest([base] + [row.models[name] for row in rows if name in row.models])
            for name in sorted(names)
        },
    )


def moment(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # Database timestamps may be naive; their timezone must be configured/verified,
    # rather than silently treated as local Tehran time.
    if parsed.tzinfo is None:
        raise ReadFailure("invalid", "mirza_timestamp_timezone_unknown")
    return parsed


def budget(row):
    if "spend" not in row:
        raise ReadFailure("invalid", "budget_spend_unknown")
    limit = Decimal(str(row["max_budget"])) if row.get("max_budget") is not None else None
    return BudgetRead(
        limit=limit,
        spend=Decimal(str(row["spend"])),
        reset_at=moment(row.get("budget_reset_at")),
        duration=row.get("budget_duration"),
    )


class Mirza:
    PATHS = (
        r"/team/list",
        r"/team/info",
        r"/user/list",
        r"/user/info",
        r"/key/list",
        r"/key/info",
        r"/v1/models",
    )

    def __init__(
        self, http, *, page_size=100, max_pages=40, tool_suffix="-Tool", contract="candidate"
    ):
        self.http, self.page_size, self.max_pages = http, page_size, max_pages
        self.tool_suffix, self.contract = tool_suffix, contract
        self._key_handles: dict[str, SecretStr] = {}

    async def pages(self, path, envelope, size_param):
        output, seen = [], set()
        expected = None
        for page in range(1, self.max_pages + 1):
            data = await self.http.get(
                path,
                {
                    "page": page,
                    size_param: self.page_size,
                    **({"return_full_object": "true"} if path == "/key/list" else {}),
                },
            )
            if not isinstance(data, dict) or not isinstance(data.get(envelope), list):
                raise ReadFailure("invalid", "mirza_page_envelope")
            rows, total = data[envelope], data.get("total_pages")
            count = data.get("total" if envelope == "users" else "total_count")
            current = data.get("page" if envelope == "users" else "current_page")
            if type(total) is not int or total < 0 or len(rows) > self.page_size:
                raise ReadFailure("incomplete", "mirza_pagination_unknown")
            if type(count) is not int or count < 0 or type(current) is not int or current != page:
                raise ReadFailure("incomplete", "mirza_pagination_count_unknown")
            if total != (count + self.page_size - 1) // self.page_size:
                raise ReadFailure("incomplete", "mirza_page_count_inconsistent")
            if expected is not None and expected != (total, count):
                raise ReadFailure("unstable", "mirza_catalog_count_changed")
            expected = (total, count)
            if total > self.max_pages:
                raise ReadFailure("incomplete", "pagination_limit")
            for row in rows:
                if not isinstance(row, dict):
                    raise ReadFailure("invalid", "mirza_row_shape")
                ident = row.get("user_id") if envelope == "users" else row.get("token")
                if not isinstance(ident, str) or not ident or ident in seen:
                    raise ReadFailure("unstable", "repeated_or_missing_mirza_identity")
                seen.add(ident)
            output.extend(rows)
            if page >= total:
                if len(output) != count:
                    raise ReadFailure("incomplete", "mirza_catalog_count_mismatch")
                return output
            if not rows:
                raise ReadFailure("incomplete", "empty_nonterminal_page")
        raise ReadFailure("incomplete", "pagination_limit")

    async def inventory(self):
        try:
            users_raw = await self.pages("/user/list", "users", "page_size")
            keys_raw = await self.pages("/key/list", "keys", "size")
            teams_raw = await self.http.get("/team/list")
            # This installed candidate endpoint is an unpaginated full list; reject
            # alternate envelopes until their pagination contract is established.
            if not isinstance(teams_raw, list):
                raise ReadFailure("incomplete", "team_list_contract")
            models_raw = await self.http.get("/v1/models")
            if not isinstance(models_raw, dict) or not isinstance(models_raw.get("data"), list):
                raise ReadFailure("invalid", "served_models_shape")
            served = tuple(row["id"] for row in models_raw["data"])
            teams = tuple(
                MirzaTeam(
                    team_id=row["team_id"],
                    alias=row["team_alias"],
                    kind="tool"
                    if row["team_alias"].strip().casefold().endswith(self.tool_suffix.casefold())
                    else "non_tool",
                    models=tuple(row["models"]),
                    budget=budget(row),
                    reasoning=reasoning(row),
                )
                for row in teams_raw
            )
            users = tuple(
                MirzaUser(
                    user_id=row["user_id"],
                    email=row.get("user_email"),
                    team_ids=tuple(row["teams"]),
                    budget=budget(row),
                    reasoning=reasoning(row),
                )
                for row in users_raw
            )
            keys, handles = [], {}
            now = datetime.now(UTC)
            for row in keys_raw:
                token = row["token"]
                ref = "litellm-key-" + stable_id(token)
                handles[ref] = SecretStr(token)
                expires = moment(row.get("expires"))
                keys.append(
                    MirzaKey(
                        key_ref=ref,
                        owner_id=row.get("user_id") or None,
                        team_id=row.get("team_id"),
                        expired=expires is not None and expires <= now,
                        expires_at=expires,
                        budget=budget(row),
                        reasoning=reasoning(row),
                    )
                )
            if len({t.team_id for t in teams}) != len(teams) or len(set(served)) != len(served):
                raise ReadFailure("invalid", "duplicate_catalog_identity")
            result = MirzaInventory(
                users=users, teams=teams, keys=tuple(keys), served_models=served
            )
            self._key_handles = handles  # Restricted in-process mapping, never serialized.
            return ok("mirza", "inventory", result, self.contract)
        except Exception as exc:
            self._key_handles.clear()
            return failed("mirza", "inventory", exc)

    async def key(self, key_ref):
        try:
            handle = self._key_handles.get(key_ref)
            if handle is None:
                raise ReadFailure("not_found", "unknown_key_reference")
            data = await self.http.get("/key/info", {"key": handle.get_secret_value()})
            row = data["info"]
            expires = moment(row.get("expires"))
            return ok(
                "mirza",
                "key",
                MirzaKey(
                    key_ref=key_ref,
                    owner_id=row.get("user_id") or None,
                    team_id=row.get("team_id"),
                    expired=expires is not None and expires <= datetime.now(UTC),
                    expires_at=expires,
                    budget=budget(row),
                    reasoning=reasoning(row),
                ),
                self.contract,
            )
        except Exception as exc:
            return failed("mirza", "key", exc)
