"""The Google Tasks API calls the service makes."""

from datetime import datetime
from typing import Any, Protocol

from gtasks_sync.errors import OpFailed

# A Tasks API task resource, as JSON.
Task = dict[str, Any]


class ApiError(Exception):
    pass


class NotFound(ApiError):
    """404: the task was deleted elsewhere."""


class BadRequest(ApiError, OpFailed):
    """400: the request can never succeed."""


class Transient(ApiError):
    """Network error, timeout, 429, or 5xx. Retry later."""


class AuthError(ApiError):
    """The refresh token is revoked or expired, or Keychain cannot be read."""


class TasksApi(Protocol):
    """Calls on the default task list."""

    def insert(self, body: Task) -> Task: ...

    def patch(self, task_id: str, body: Task) -> Task: ...

    def delete(self, task_id: str) -> None: ...

    def list_updated_since(self, since: datetime) -> list[Task]:
        """Tasks updated at or after since, completed and hidden ones too. Never deleted ones."""
        ...


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
