from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OperationMode(StrEnum):
    OBSERVE = "observe"
    REVIEW = "review"
    AUTOMATIC = "automatic"


class WorkerRole(StrEnum):
    DISPATCH = "dispatch"
    MIRZA = "mirza"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTIC_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    temporal_address: str = "localhost:17233"
    temporal_namespace: str = "agentic"
    dispatch_mode: OperationMode = OperationMode.OBSERVE
    mirza_mode: OperationMode = OperationMode.OBSERVE
    dispatch_paused: bool = False
    mirza_paused: bool = False
    dispatch_task_queue: str = "agentic-dispatch"
    mirza_task_queue: str = "agentic-mirza"
    log_level: str = "INFO"
    dependency_timeout_seconds: float = Field(default=5, gt=0, le=30)
    heartbeat_seconds: float = Field(default=5, gt=0, le=10)
    worker_stale_seconds: int = Field(default=30, ge=15, le=120)
    intake_token: SecretStr | None = None
    operator_token: SecretStr | None = None
    operator_principal: str = "local-operator"
    catalog_file: Path | None = None
    enable_fixture_execution: bool = False
    fixture_lose_response_once: bool = False
    servicedesk_url: str | None = None
    servicedesk_read_token: SecretStr | None = None
    servicedesk_lifecycle_creator_ids: tuple[
        Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,29}$")], ...
    ] = Field(default=(), max_length=20, repr=False)
    offboarding_database_url: SecretStr | None = None
    onboarding_database_url: SecretStr | None = None
    directory_url: str | None = None
    directory_read_token: SecretStr | None = None
    mirza_url: str | None = None
    mirza_read_token: SecretStr | None = None
    mattermost_url: str | None = None
    mattermost_read_token: SecretStr | None = None
    mattermost_bot_username: str = "servicedesk_agent"
    department_map_file: Path | None = None
    mirza_reasoning_default: Literal["none", "minimal", "low", "medium", "high", "xhigh"] = "medium"
    connector_allow_http: bool = False
    connector_timeout_seconds: float = Field(default=8, gt=0, le=15)

    @model_validator(mode="after")
    def validate_boundaries(self) -> "Settings":
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Application database must use postgresql+psycopg")
        if self.dispatch_task_queue == self.mirza_task_queue:
            raise ValueError("Dispatch and Mirza workers require different task queues")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Unsupported log level")
        if self.intake_token and self.operator_token and self.intake_token == self.operator_token:
            raise ValueError("Intake and operator credentials must differ")
        for token in (self.intake_token, self.operator_token):
            if token is not None and len(token.get_secret_value()) < 32:
                raise ValueError("API credentials require at least 32 characters")
        if self.fixture_lose_response_once and not self.enable_fixture_execution:
            raise ValueError("Fault injection requires the synthetic connector")
        if len(set(self.servicedesk_lifecycle_creator_ids)) != len(
            self.servicedesk_lifecycle_creator_ids
        ):
            raise ValueError("Lifecycle creator IDs must be unique")
        return self

    def mode(self, role: WorkerRole) -> OperationMode:
        return self.dispatch_mode if role == WorkerRole.DISPATCH else self.mirza_mode

    def paused(self, role: WorkerRole) -> bool:
        return self.dispatch_paused if role == WorkerRole.DISPATCH else self.mirza_paused

    def task_queue(self, role: WorkerRole) -> str:
        return self.dispatch_task_queue if role == WorkerRole.DISPATCH else self.mirza_task_queue
