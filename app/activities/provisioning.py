"""Privileged fixture boundary. Production credentials cannot activate this connector."""

import asyncio

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.activities.fulfillment_service import FixtureFulfillmentService
from app.connectors.secret_cipher import SecretCipher
from app.contracts.provisioning import FulfillmentReceipt
from app.policies.provisioning import FulfillmentBusy, LostFixtureResponse
from app.settings import OperationMode, WorkerRole


class ProvisioningActivities:
    def __init__(self, engine, settings, role):
        self.settings, self.role = settings, role
        self.service = None
        if settings.enable_fixture_provisioning and role == WorkerRole.MIRZA:
            self.service = FixtureFulfillmentService(
                engine, SecretCipher.from_file(settings.fixture_vault_key_file)
            )

    @activity.defn(name="advance_fixture_mirza_fulfillment")
    async def advance(self, operation_id: str, command_index: int = 0) -> FulfillmentReceipt:
        if (
            self.service is None
            or self.role != WorkerRole.MIRZA
            or self.settings.paused(self.role)
            or self.settings.mode(self.role) != OperationMode.AUTOMATIC
            or not self.settings.enable_fixture_execution
        ):
            return FulfillmentReceipt(operation_id, "blocked", "", "fixture_connector_disabled")
        try:
            return await asyncio.to_thread(self.service.advance, operation_id, command_index)
        except (LostFixtureResponse, FulfillmentBusy) as error:
            raise ApplicationError(
                "Synthetic fulfillment will reconcile", type=type(error).__name__
            ) from None
        except Exception as error:
            # Database/provider exception messages may contain private parameter values.
            raise ApplicationError(
                "Synthetic fulfillment unavailable", type=type(error).__name__, non_retryable=True
            ) from None
