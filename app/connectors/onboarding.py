"""SELECT-only onboarding index; the packed ServiceDesk field can lag creation."""

from app.connectors.offboarding import Offboarding, normalize_processes
from app.contracts.context import OnboardingProcess

CHILD_COLUMNS = ("office_id", "ex_id", "helpdesk_id", "voip_id")
QUERY = """
SELECT automation_id::text AS automation_id, office_id::text AS office_id,
       ex_id::text AS ex_id, helpdesk_id::text AS helpdesk_id, voip_id::text AS voip_id
FROM public.onboarding_process
WHERE automation_id::text = %s OR office_id::text = %s OR ex_id::text = %s
   OR helpdesk_id::text = %s OR voip_id::text = %s
ORDER BY automation_id
LIMIT 101
"""


def normalize_onboarding_processes(rows, ticket_id):
    # Cast only confirmed ticket-ID columns in the fixed SELECT. hr_id is unused
    # in the observed table; its relation semantics are not established.
    records = normalize_processes(rows, ticket_id, child_columns=CHILD_COLUMNS)
    return tuple(OnboardingProcess.model_validate(record.model_dump()) for record in records)


class Onboarding(Offboarding):
    query = QUERY
    child_columns = CHILD_COLUMNS
    resource = "onboarding_relationships"
    failure_reason = "onboarding_read_unavailable"
    normalize = staticmethod(normalize_onboarding_processes)
