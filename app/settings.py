from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    enable_fixture_provisioning: bool = False
    fixture_vault_key_file: Path | None = None
    servicedesk_url: str | None = None
    servicedesk_read_token: SecretStr | None = None
    servicedesk_lifecycle_creator_ids: tuple[
        Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,29}$")], ...
    ] = Field(default=(), max_length=20, repr=False)
    servicedesk_lifecycle_creator_coverage_confirmed: bool = False
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
    observation_listener_enabled: bool = False
    observation_poll_seconds: int = Field(default=60, ge=30, le=3600)
    observation_batch_size: int = Field(default=4, ge=1, le=20)
    inference_enabled: bool = False
    # API reports the shared Compose switch without receiving the inference secret.
    worker_inference_enabled: bool = False
    inference_url: str | None = None
    inference_token: SecretStr | None = None
    inference_model: str = "local-qwen3.8"
    inference_timeout_seconds: float = Field(default=30, gt=0, le=60)
    inference_request_limit: int = Field(default=3, ge=1, le=4)
    inference_tool_limit: int = Field(default=2, ge=0, le=4)
    inference_input_token_limit: int = Field(default=20000, ge=100, le=50000)
    inference_output_token_limit: int = Field(default=2000, ge=100, le=4000)
    inference_max_cost_usd: float = Field(default=0.25, gt=0, le=2, allow_inf_nan=False)
    inference_daily_budget_usd: float = Field(default=2, gt=0, le=100, allow_inf_nan=False)
    inference_input_usd_per_million: float | None = Field(
        default=None, gt=0, le=1000, allow_inf_nan=False
    )
    inference_output_usd_per_million: float | None = Field(
        default=None, gt=0, le=1000, allow_inf_nan=False
    )

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
        if self.enable_fixture_provisioning:
            from urllib.parse import urlsplit

            database = urlsplit(self.database_url.get_secret_value())
            if (not self.enable_fixture_execution or self.mirza_mode != OperationMode.AUTOMATIC
                    or self.fixture_vault_key_file is None
                    or database.hostname not in {"postgres", "localhost", "127.0.0.1", "::1"}
                    or database.path != "/agentic" or self.temporal_namespace != "agentic"
                    or self.inference_enabled or self.worker_inference_enabled
                    or self.observation_listener_enabled):
                raise ValueError("Provisioning simulation requires the local fixture setup")
        if len(set(self.servicedesk_lifecycle_creator_ids)) != len(
            self.servicedesk_lifecycle_creator_ids
        ):
            raise ValueError("Lifecycle creator IDs must be unique")
        if self.servicedesk_lifecycle_creator_coverage_confirmed and len(
            self.servicedesk_lifecycle_creator_ids
        ) != 1:
            raise ValueError("Historical lifecycle creator coverage requires exactly one account")
        if self.observation_listener_enabled and (
            self.dispatch_mode != OperationMode.OBSERVE or self.mirza_mode != OperationMode.OBSERVE
        ):
            raise ValueError("Observation listener requires observation modes")
        if self.inference_enabled:
            if self.inference_model != "local-qwen3.8":
                raise ValueError("Agent inference requires the local-qwen3.8 model")
            if (
                not self.inference_url or not self.inference_token
                or not self.inference_token.get_secret_value()
                or self.inference_input_usd_per_million is None
                or self.inference_output_usd_per_million is None
            ):
                raise ValueError("Inference requires endpoint/token/model and declared rates")
            from urllib.parse import urlsplit

            url = urlsplit(self.inference_url)
            if (
                url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment
                or url.path not in {"", "/", "/v1", "/v1/", "/api/v1", "/api/v1/"}
            ):
                raise ValueError("Inference requires a fixed HTTPS compatible API endpoint")
            if self.inference_token in (
                self.servicedesk_read_token, self.mirza_read_token, self.directory_read_token,
                self.mattermost_read_token, self.intake_token, self.operator_token,
            ):
                raise ValueError("Inference and connector credentials must differ")
        if self.inference_max_cost_usd > self.inference_daily_budget_usd:
            raise ValueError("Per-stage inference cap exceeds daily budget")
        return self

    @field_validator("inference_input_usd_per_million", "inference_output_usd_per_million",
                     mode="before")
    @classmethod
    def optional_rates(cls, value):
        return None if value == "" else value

    def mode(self, role: WorkerRole) -> OperationMode:
        return self.dispatch_mode if role == WorkerRole.DISPATCH else self.mirza_mode

    def paused(self, role: WorkerRole) -> bool:
        return self.dispatch_paused if role == WorkerRole.DISPATCH else self.mirza_paused

    def task_queue(self, role: WorkerRole) -> str:
        return self.dispatch_task_queue if role == WorkerRole.DISPATCH else self.mirza_task_queue
