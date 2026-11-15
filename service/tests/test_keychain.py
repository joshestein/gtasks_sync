"""Runs against the real login Keychain, with a throwaway service name."""

import sys
from collections.abc import Iterator

import pytest

from gtasks_sync import keychain
from gtasks_sync.keychain import KeychainError, Secrets, delete_secrets, read_secrets, save_secrets

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain")


@pytest.fixture(autouse=True)
def test_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(keychain, "SERVICE", "gtasks-sync-test")
    delete_secrets()
    yield
    delete_secrets()


def test_round_trip_and_replace() -> None:
    # Quotes and backslashes would break the `security -i` line without the base64 wrap.
    first = Secrets(client_id="id.apps.googleusercontent.com", client_secret='s"e\\c', refresh_token="1//0g-abc")
    save_secrets(first)
    assert read_secrets() == first

    second = Secrets(client_id="id2", client_secret="s2", refresh_token="1//new")
    save_secrets(second)
    assert read_secrets() == second


def test_missing() -> None:
    with pytest.raises(KeychainError, match="gtasks-sync setup"):
        read_secrets()
    assert not delete_secrets()


def test_delete() -> None:
    save_secrets(Secrets("a", "b", "c"))
    assert delete_secrets()
    assert not delete_secrets()
