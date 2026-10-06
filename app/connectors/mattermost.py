from urllib.parse import quote

from app.connectors.http import ReadFailure, failed, ok
from app.contracts.context import MattermostBot, MattermostPerson


class Mattermost:
    PATHS = (r"/api/v4/users/me", r"/api/v4/users/email/[A-Za-z0-9%_.@+\-]+")

    def __init__(self, http, contract="candidate", expected_bot_username="servicedesk_agent"):
        self.http, self.contract = http, contract
        self.expected_bot_username = expected_bot_username

    async def bot(self):
        try:
            row = await self.http.get("/api/v4/users/me")
            if row.get("username") != self.expected_bot_username:
                raise ReadFailure("invalid", "mattermost_bot_username_mismatch")
            if type(row.get("delete_at")) is not int or row.get("is_bot") is not True:
                raise ReadFailure("invalid", "mattermost_bot_contract")
            if row["delete_at"] != 0:
                raise ReadFailure("invalid", "mattermost_bot_inactive")
            bot = MattermostBot(
                user_id=row["id"], username=row["username"], active=True, is_bot=True
            )
            return ok("mattermost", "bot", bot, self.contract)
        except Exception as exc:
            return failed("mattermost", "bot", exc)

    async def person(self, email):
        try:
            row = await self.http.get(
                "/api/v4/users/email/" + quote(email, safe=""), missing_is_not_found=True
            )
            if str(row.get("email", "")).casefold() != email.casefold():
                raise ReadFailure("invalid", "mattermost_email_mismatch")
            # Mattermost's Go User JSON omits is_bot when false.
            bot = row.get("is_bot", False)
            if type(row.get("delete_at")) is not int or type(bot) is not bool:
                raise ReadFailure("invalid", "mattermost_active_contract")
            person = MattermostPerson(
                user_id=row["id"],
                email=row["email"],
                active=row["delete_at"] == 0,
                is_bot=bot,
            )
            if not person.active or person.is_bot:
                raise ReadFailure("invalid", "mattermost_recipient_ineligible")
            return ok("mattermost", "recipient", person, self.contract)
        except Exception as exc:
            return failed("mattermost", "recipient", exc)
