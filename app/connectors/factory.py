from pathlib import Path

from app.connectors.context import ContextReader
from app.connectors.directory import Directory
from app.connectors.http import ReadFailure, ReadOnlyHTTP, failed
from app.connectors.lifecycle import installed_lifecycle_templates
from app.connectors.mapping import DepartmentMap
from app.connectors.mattermost import Mattermost
from app.connectors.mirza import Mirza
from app.connectors.offboarding import Offboarding
from app.connectors.onboarding import Onboarding
from app.connectors.servicedesk import ServiceDesk


class Disabled:
    def __init__(self, component):
        self.component = component

    def __getattr__(self, resource):
        async def missing(*args):
            return failed(
                self.component, resource, ReadFailure("unavailable", "connector_not_configured")
            )

        return missing


class Connectors:
    def __init__(self, settings):
        self.transports = []
        components = []
        for name, cls, token, origin in (
            ("servicedesk", ServiceDesk, settings.servicedesk_read_token, settings.servicedesk_url),
            ("directory", Directory, settings.directory_read_token, settings.directory_url),
            ("mirza", Mirza, settings.mirza_read_token, settings.mirza_url),
            ("mattermost", Mattermost, settings.mattermost_read_token, settings.mattermost_url),
        ):
            if token is None or not token.get_secret_value() or not origin:
                components.append(Disabled(name))
                continue
            http = ReadOnlyHTTP(
                origin,
                token,
                cls.PATHS,
                auth_header="authtoken" if name == "servicedesk" else "Authorization",
                allow_http=settings.connector_allow_http,
                timeout=settings.connector_timeout_seconds,
            )
            self.transports.append(http)
            offboarding = None
            onboarding = None
            if name == "servicedesk" and settings.offboarding_database_url:
                if settings.offboarding_database_url.get_secret_value():
                    offboarding = Offboarding(
                        settings.offboarding_database_url,
                        timeout=settings.connector_timeout_seconds,
                    )
            if name == "servicedesk":
                if (
                    settings.onboarding_database_url
                    and settings.onboarding_database_url.get_secret_value()
                ):
                    onboarding = Onboarding(
                        settings.onboarding_database_url,
                        timeout=settings.connector_timeout_seconds,
                    )
                component = cls(
                    http, lifecycle_template_ids=installed_lifecycle_templates(),
                    offboarding=offboarding, onboarding=onboarding,
                    lifecycle_creator_ids=settings.servicedesk_lifecycle_creator_ids,
                )
            elif name == "mattermost":
                component = cls(http, expected_bot_username=settings.mattermost_bot_username)
            else:
                component = cls(http)
            components.append(component)
        mapping_path = (
            settings.department_map_file
            or Path(__file__).resolve().parents[2] / "docs" / "department-tool-team-map.json"
        )
        self.reader = ContextReader(
            *components, DepartmentMap(mapping_path), settings.mirza_reasoning_default
        )

    async def close(self):
        for transport in self.transports:
            await transport.close()
