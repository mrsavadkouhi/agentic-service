"""Privileged fixture boundary. Production credentials cannot activate this connector."""

import asyncio

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.activities.fulfillment_service import FixtureFulfillmentService
from app.activities.lifecycle_service import LifecycleService
from app.connectors.secret_cipher import SecretCipher
from app.contracts.lifecycle import LifecycleReceipt
from app.contracts.provisioning import FulfillmentReceipt
from app.policies.provisioning import FulfillmentBusy, LostFixtureResponse
from app.settings import OperationMode, WorkerRole
from app.storage.provisioning import FulfillmentRecord


class ProvisioningActivities:
    def __init__(self, engine, settings, role):
        self.settings, self.role = settings, role
        self.service = None
        if settings.enable_fixture_provisioning and role == WorkerRole.MIRZA:
            self.service = FixtureFulfillmentService(
                engine, SecretCipher.from_file(settings.fixture_vault_key_file)
            )

    def enabled(self):
        return (
            self.service is not None
            and self.role == WorkerRole.MIRZA
            and not self.settings.paused(self.role)
            and self.settings.mode(self.role) == OperationMode.AUTOMATIC
            and self.settings.enable_fixture_execution
        )

    def advance_checked(self, operation_id, command_index, expiry_owned):
        with Session(self.service.engine) as session, session.begin():
            record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
            job = (
                record.payload.get("event", {}).get("proposal", {}).get("job", {}) if record else {}
            )
            if job.get("expires_at") and not expiry_owned:
                if (
                    record.state not in {"completed", "cancelled"}
                    and record.reason_code != "managed_expiry_workflow_required"
                ):
                    record.state, record.reason_code = "blocked", "managed_expiry_workflow_required"
                    record.payload = {
                        **record.payload,
                        "lifecycle_revision": record.payload.get("lifecycle_revision", 0) + 1,
                    }
                return FulfillmentReceipt(
                    operation_id, "blocked", "", "managed_expiry_workflow_required"
                )
        return self.service.advance(operation_id, command_index)

    @activity.defn(name="reconcile_fixture_lifecycle")
    async def lifecycle(self, operation_id: str) -> LifecycleReceipt:
        if not self.enabled():
            return LifecycleReceipt(operation_id, "blocked", "fixture_connector_disabled")
        try:
            service = LifecycleService(self.service.engine, self.service)
            return await asyncio.to_thread(service.reconcile, operation_id)
        except Exception as error:
            raise ApplicationError(
                "Synthetic lifecycle unavailable", type=type(error).__name__, non_retryable=True
            ) from None

    @activity.defn(name="resume_fixture_fulfillment")
    async def resume(self, command_id: str) -> LifecycleReceipt:
        if not self.enabled():
            return LifecycleReceipt("", "blocked", "fixture_connector_disabled")
        try:
            service = LifecycleService(self.service.engine, self.service)
            return await asyncio.to_thread(service.apply_resume, command_id)
        except Exception as error:
            raise ApplicationError(
                "Synthetic recovery unavailable", type=type(error).__name__, non_retryable=True
            ) from None

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
            expiry_owned = (
                activity.in_activity()
                and activity.info().workflow_type == "MirzaFixtureLifecycleWorkflow"
            )
            return await asyncio.to_thread(
                self.advance_checked, operation_id, command_index, expiry_owned
            )
        except (LostFixtureResponse, FulfillmentBusy) as error:
            raise ApplicationError(
                "Synthetic fulfillment will reconcile", type=type(error).__name__
            ) from None
        except Exception as error:
            # Database/provider exception messages may contain private parameter values.
            raise ApplicationError(
                "Synthetic fulfillment unavailable", type=type(error).__name__, non_retryable=True
            ) from None
