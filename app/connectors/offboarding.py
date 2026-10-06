"""Bounded SELECT-only access to the existing n8n offboarding process map."""

import math
import re

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.connectors.http import ReadFailure, failed, ok
from app.contracts.context import OffboardingProcess

CHILD_COLUMNS = (
    "helpdesk_id", "sysadmin_id", "network_id", "devflow_id", "foundation_id",
    "voip_id", "platform_id", "di_id",
)
MAX_ROWS = 100
QUERY = """
SELECT automation_id, helpdesk_id, sysadmin_id, network_id, devflow_id,
       foundation_id, voip_id, platform_id, di_id
FROM public.offboarding_process
WHERE automation_id = %s OR helpdesk_id = %s OR sysadmin_id = %s
   OR network_id = %s OR devflow_id = %s
   OR foundation_id = %s OR voip_id = %s OR platform_id = %s OR di_id = %s
ORDER BY automation_id
LIMIT 101
"""


def ticket_reference(value, *, optional=False):
    if optional and (value is None or value == ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,30}", value):
        raise ReadFailure("invalid", "invalid_offboarding_ticket_reference")
    return value


def normalize_processes(rows, ticket_id, *, child_columns=CHILD_COLUMNS):
    ticket_reference(ticket_id)
    if len(rows) > MAX_ROWS:
        raise ReadFailure("incomplete", "offboarding_mapping_limit")
    result, parents = [], set()
    for row in rows:
        if not isinstance(row, dict) or not {"automation_id", *child_columns} <= row.keys():
            raise ReadFailure("invalid", "offboarding_mapping_shape")
        parent = ticket_reference(row["automation_id"])
        children = tuple(
            child for column in child_columns
            if (child := ticket_reference(row[column], optional=True)) is not None
        )
        if parent in parents:
            raise ReadFailure("ambiguous", "duplicate_offboarding_parent")
        if parent in children or len(set(children)) != len(children):
            raise ReadFailure("invalid", "conflicting_offboarding_relationships")
        if ticket_id != parent and ticket_id not in children:
            raise ReadFailure("invalid", "offboarding_query_mismatch")
        parents.add(parent)
        result.append(OffboardingProcess(parent_id=parent, child_ids=children))
    return tuple(sorted(result, key=lambda process: process.parent_id))


class Offboarding:
    query = QUERY
    child_columns = CHILD_COLUMNS
    resource = "offboarding_relationships"
    failure_reason = "offboarding_read_unavailable"
    normalize = staticmethod(normalize_processes)

    def __init__(self, database_url, *, timeout=8, contract="candidate", connect=None):
        self.database_url = database_url
        self.timeout, self.contract = timeout, contract
        self.connect = connect or AsyncConnection.connect

    async def read(self, ticket_id):
        try:
            ticket_reference(ticket_id)
            # A fresh connection prevents transaction settings leaking into any
            # application pool. No writes, DDL, credential or employee queries.
            connection = await self.connect(
                self.database_url.get_secret_value(),
                connect_timeout=math.ceil(self.timeout),
                options=f"-c default_transaction_read_only=on "
                f"-c statement_timeout={math.ceil(self.timeout * 1000)}",
                row_factory=dict_row,
            )
            async with connection:
                await connection.execute("SET TRANSACTION READ ONLY")
                cursor = await connection.execute(
                    self.query, (ticket_id,) * (1 + len(self.child_columns))
                )
                rows = await cursor.fetchall()
                processes = self.normalize(rows, ticket_id)
            return ok("servicedesk", self.resource, processes, self.contract)
        except ReadFailure as exc:
            return failed("servicedesk", self.resource, exc)
        except Exception:
            # PostgreSQL exceptions can contain server/credential/row details.
            return failed(
                "servicedesk", self.resource,
                ReadFailure("unavailable", self.failure_reason),
            )
