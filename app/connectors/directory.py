from app.connectors.http import ReadFailure, failed, ok
from app.contracts.context import DirectoryPerson


class Directory:
    PATHS = (r"/internal/identity", r"/internal/department")

    def __init__(self, http, contract="candidate"):
        self.http, self.contract = http, contract

    async def person(self, email):
        try:
            row = await self.http.get("/internal/identity", {"email": email})
            if (
                not isinstance(row, dict)
                or type(row.get("matches")) is not int
                or row["matches"] < 0
            ):
                raise ReadFailure("invalid", "directory_match_contract")
            if row["matches"] != 1:
                raise ReadFailure(
                    "not_found" if row["matches"] == 0 else "ambiguous",
                    "directory_email_not_unique",
                )
            result = DirectoryPerson.model_validate(row["identity"])
            if result.email != email.strip().casefold():
                raise ReadFailure("invalid", "directory_email_mismatch")
            result = result.model_copy(
                update={"employee_status": "eligible" if result.eligible() else "ineligible"}
            )
            return ok("directory", "identity", result, self.contract)
        except Exception as exc:
            return failed("directory", "identity", exc)

    async def department(self, email):
        try:
            row = await self.http.get("/internal/department", {"email": email})
            if (
                type(row.get("matches")) is not int
                or row.get("email", "").casefold() != email.casefold()
            ):
                raise ReadFailure("invalid", "department_lookup_contract")
            if row["matches"] != 1:
                raise ReadFailure(
                    "not_found" if row["matches"] == 0 else "ambiguous",
                    "directory_email_not_unique",
                )
            if not isinstance(row.get("department"), str):
                raise ReadFailure("invalid", "department_missing")
            return ok("directory", "department", row["department"], self.contract)
        except Exception as exc:
            return failed("directory", "department", exc)
