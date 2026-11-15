"""The Google Tasks API calls the service makes, on the default task list."""

import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import requests
from google.auth import exceptions as auth_errors

from gtasks_sync.errors import OpFailed

log = logging.getLogger(__name__)

# A Tasks API task resource, as JSON.
Task = dict[str, Any]

BASE_URL = "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"
TIMEOUT = 30
PAGE_SIZE = 100
# 403 reasons that mean "slow down", not "no access".
_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded", "limitExceeded"}


class ApiError(Exception):
    """An error with no special handling: it stops the round."""


class NotFound(ApiError):
    """404 or 410: the task was deleted elsewhere."""


class BadRequest(ApiError, OpFailed):
    """400: the request can never succeed."""


class Transient(ApiError):
    """Network error, timeout, 429, 5xx, or a rate limit. Retry later."""


class AuthError(ApiError):
    """The refresh token is revoked or expired, access is denied, or Keychain cannot be read. Run setup."""


class TasksApi(Protocol):
    """The calls apply needs."""

    def insert(self, body: Task) -> Task: ...

    def patch(self, task_id: str, body: Task) -> None:
        """No effect on a task deleted elsewhere."""
        ...

    def delete(self, task_id: str) -> None:
        """No effect on a task deleted elsewhere."""
        ...

    def list_updated_since(self, since: datetime) -> list[Task]:
        """Tasks updated at or after since, completed and hidden ones too. Never deleted ones."""
        ...


class Session(Protocol):
    """The part of requests.Session (and google-auth's AuthorizedSession) that HttpTasksApi uses."""

    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


def iso(dt: datetime) -> str:
    """RFC 3339 in UTC with milliseconds, the same format as JS Date.toISOString()."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def due_to_api(day: str) -> str:
    """YYYY-MM-DD to the API's form. The API keeps only the date part.

    Never build this from local midnight in UTC: that moves the date by one day east of UTC.
    """
    return f"{day}T00:00:00.000Z"


def due_from_api(value: str | None) -> str | None:
    return value[:10] if value else None


def task_fields(task: Task) -> tuple[str, str, str | None]:
    """(title, notes, due) with the defaults for fields the API leaves out."""
    return task.get("title", ""), task.get("notes", ""), due_from_api(task.get("due"))


def patch_body(fields: dict[str, str | None]) -> Task:
    """Op fields (due as YYYY-MM-DD or None) in the API's form."""
    return {
        name: (due_to_api(value) if value else None) if name == "due" else value
        for name, value in fields.items()
    }


def insert_body(fields: dict[str, str | None]) -> Task:
    # Title is never empty. Empty notes and no due date are left out.
    return {name: value for name, value in patch_body(fields).items() if value}


def _reason(response: Any) -> str:
    try:
        error = response.json()["error"]
        return error["errors"][0]["reason"] if error.get("errors") else error.get("status", "")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return ""


def _error(response: Any) -> ApiError:
    status: int = response.status_code
    reason = _reason(response)
    message = f"HTTP {status} {reason}".strip()
    if status in (404, 410):
        return NotFound(message)
    if status == 400:
        return BadRequest(message)
    if status == 429 or status >= 500 or (status == 403 and reason in _RATE_LIMIT_REASONS):
        return Transient(message)
    if status in (401, 403):
        return AuthError(message)
    return ApiError(message)


class HttpTasksApi:
    def __init__(self, session: Session) -> None:
        self._session = session

    def call(
        self, method: str, task_id: str | None = None, *, params: dict[str, str] | None = None, body: Task | None = None
    ) -> Any:
        """One request. Raise the matching ApiError on failure. Return the JSON body, or None if empty."""
        url = BASE_URL if task_id is None else f"{BASE_URL}/{quote(task_id, safe='')}"
        try:
            response = self._session.request(method, url, params=params, json=body, timeout=TIMEOUT)
        except auth_errors.RefreshError as e:
            raise (Transient if e.retryable else AuthError)(f"token refresh: {e}") from e
        except (requests.RequestException, auth_errors.TransportError, auth_errors.TimeoutError) as e:
            raise Transient(f"{type(e).__name__}: {e}") from e
        if response.status_code >= 300:
            raise _error(response)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as e:
            # For example a captive portal that answers 200 with HTML.
            raise Transient(f"response is not JSON: {e}") from e

    def insert(self, body: Task) -> Task:
        return self.call("POST", body=body)

    def patch(self, task_id: str, body: Task) -> None:
        # Google reports a gone task as a 404, or as a 200 with deleted: true. Both mean the task stays gone.
        try:
            task = self.call("PATCH", task_id, body=body)
        except NotFound:
            task = {"deleted": True}
        if task and task.get("deleted"):
            log.info("patch had no effect: task %s was deleted elsewhere", task_id)

    def delete(self, task_id: str) -> None:
        # A second delete succeeds. A purged task gives 404.
        try:
            self.call("DELETE", task_id)
        except NotFound:
            pass

    def _list(self, params: dict[str, str]) -> list[Task]:
        """All pages. Without showDeleted, the API never returns deleted tasks."""
        tasks: list[Task] = []
        page_token = None
        while True:
            page_params = {**params, "maxResults": str(PAGE_SIZE)}
            if page_token:
                page_params["pageToken"] = page_token
            page = self.call("GET", params=page_params)
            if not isinstance(page, dict):
                raise Transient("empty list response")
            tasks.extend(page.get("items", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                return tasks

    def list_updated_since(self, since: datetime) -> list[Task]:
        return self._list({"updatedMin": iso(since), "showCompleted": "true", "showHidden": "true"})

    def list_open(self) -> list[Task]:
        return self._list({"showCompleted": "false"})

    def list_completed_since(self, since: datetime) -> list[Task]:
        # showHidden: a task completed in a Google app is hidden, and the API skips it without this flag.
        return self._list({"showCompleted": "true", "showHidden": "true", "completedMin": iso(since)})
