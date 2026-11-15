import json
from datetime import UTC, datetime
from typing import Any

import pytest
import requests
from google.auth import exceptions as auth_errors

from gtasks_sync.api import (
    BASE_URL,
    TIMEOUT,
    ApiError,
    AuthError,
    BadRequest,
    HttpTasksApi,
    NotFound,
    Transient,
    iso,
)
from gtasks_sync.errors import OpFailed


class FakeResponse:
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self) -> Any:
        return json.loads(self.content)


def error_body(reason: str) -> dict[str, Any]:
    return {"error": {"code": 0, "errors": [{"reason": reason}]}}


class FakeSession:
    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_insert_patch_delete_requests() -> None:
    session = FakeSession(FakeResponse(200, {"id": "t1"}), FakeResponse(200, {"id": "a/b"}), FakeResponse(204))
    api = HttpTasksApi(session)

    assert api.insert({"title": "milk"}) == {"id": "t1"}
    assert api.patch("a/b", {"title": "x"}) == {"id": "a/b"}
    assert api.delete("t1") is None

    assert session.requests == [
        ("POST", BASE_URL, {"params": None, "json": {"title": "milk"}, "timeout": TIMEOUT}),
        ("PATCH", f"{BASE_URL}/a%2Fb", {"params": None, "json": {"title": "x"}, "timeout": TIMEOUT}),
        ("DELETE", f"{BASE_URL}/t1", {"params": None, "json": None, "timeout": TIMEOUT}),
    ]


def test_list_reads_all_pages() -> None:
    session = FakeSession(
        FakeResponse(200, {"items": [{"id": "t1"}], "nextPageToken": "p2"}),
        FakeResponse(200, {}),  # The API leaves out items on an empty page.
    )
    since = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

    tasks = HttpTasksApi(session).list_completed_since(since)

    assert tasks == [{"id": "t1"}]
    first, second = (r[2]["params"] for r in session.requests)
    assert first == {
        "showCompleted": "true",
        "showHidden": "true",
        "completedMin": "2026-11-15T09:00:00.000Z",
        "maxResults": "100",
    }
    assert second == {**first, "pageToken": "p2"}


def test_list_open_and_updated_since_params() -> None:
    session = FakeSession(FakeResponse(200, {}), FakeResponse(200, {}))
    api = HttpTasksApi(session)
    api.list_open()
    api.list_updated_since(datetime(2026, 11, 15, tzinfo=UTC))
    open_params, updated_params = (r[2]["params"] for r in session.requests)
    assert open_params == {"showCompleted": "false", "maxResults": "100"}
    assert updated_params["updatedMin"] == "2026-11-15T00:00:00.000Z"
    assert "showDeleted" not in updated_params


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (FakeResponse(404, error_body("notFound")), NotFound),
        (FakeResponse(410), NotFound),
        (FakeResponse(400, error_body("invalid")), BadRequest),
        (FakeResponse(401), AuthError),
        (FakeResponse(403, error_body("accessNotConfigured")), AuthError),
        (FakeResponse(403, error_body("userRateLimitExceeded")), Transient),
        (FakeResponse(429), Transient),
        (FakeResponse(503), Transient),
        (FakeResponse(409), ApiError),
        (requests.ConnectionError("down"), Transient),
        (requests.Timeout("slow"), Transient),
        (auth_errors.TransportError("dns"), Transient),
        (auth_errors.RefreshError("invalid_grant"), AuthError),
        (auth_errors.RefreshError("503", retryable=True), Transient),
    ],
)
def test_errors(response: FakeResponse | Exception, error: type[ApiError]) -> None:
    with pytest.raises(error) as raised:
        HttpTasksApi(FakeSession(response)).patch("t1", {})
    assert type(raised.value) is error


def test_only_bad_request_makes_a_failed_op() -> None:
    assert issubclass(BadRequest, OpFailed)
    assert not any(issubclass(e, OpFailed) for e in (NotFound, Transient, AuthError))


def test_error_message_has_status_and_reason() -> None:
    with pytest.raises(AuthError, match="HTTP 403 accessNotConfigured"):
        HttpTasksApi(FakeSession(FakeResponse(403, error_body("accessNotConfigured")))).delete("t1")


def test_iso() -> None:
    assert iso(datetime(2026, 11, 15, 9, 0, 1, 500_000, tzinfo=UTC)) == "2026-11-15T09:00:01.500Z"
