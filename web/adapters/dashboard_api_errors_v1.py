"""Presentation-only mapping for stable dashboard API failures; no HTTP calls."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardAPIErrorPresentation:
    state: str
    message_key: str
    action: str
    automatic_retry: bool = False
    reuse_stale_data: bool = False


def classify_dashboard_api_failure(http_status: int | None, code: str | None) -> DashboardAPIErrorPresentation:
    """Map only stable status/code pairs; never return backend exception text."""
    if http_status is None:
        return DashboardAPIErrorPresentation("API_UNAVAILABLE", "dashboard.api_unavailable", "manual_retry")
    if type(http_status) is not int:
        return DashboardAPIErrorPresentation("API_UNAVAILABLE", "dashboard.api_unavailable", "manual_retry")
    if http_status == 401 and code == "API_UNAUTHORIZED":
        return DashboardAPIErrorPresentation("AUTH_REQUIRED", "dashboard.login_required", "use_existing_login")
    if http_status == 403 and code in {"API_FORBIDDEN", "API_SOURCE_NOT_ALLOWED"}:
        return DashboardAPIErrorPresentation("ACCESS_DENIED", "dashboard.access_denied", "keep_session_show_denied")
    if http_status == 400 and code == "API_INVALID_REQUEST":
        return DashboardAPIErrorPresentation("REQUEST_REJECTED", "dashboard.request_rejected", "do_not_retry")
    if http_status in {500, 502, 503, 504} and code in {
            "API_INTERNAL_ERROR", "API_PROVIDER_UNAVAILABLE", "API_TIMEOUT",
            "API_AUDIT_UNAVAILABLE", "API_DATA_UNAVAILABLE"}:
        return DashboardAPIErrorPresentation("API_UNAVAILABLE", "dashboard.temporarily_unavailable", "manual_retry")
    return DashboardAPIErrorPresentation("API_UNAVAILABLE", "dashboard.api_unavailable", "manual_retry")
