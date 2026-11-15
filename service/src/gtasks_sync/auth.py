"""OAuth: the one-time browser flow, and an API client from the stored secrets."""

from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gtasks_sync.api import HttpTasksApi
from gtasks_sync.keychain import Secrets

SCOPES = ["https://www.googleapis.com/auth/tasks"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def authorize(client_secret_file: Path) -> Secrets:
    """Open the browser for consent, with a local redirect. The client must be of type Desktop app."""
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
    # prompt=consent: Google sends a refresh token only on consent, also when setup runs again.
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token or not creds.client_id or not creds.client_secret:
        raise RuntimeError("Google sent no refresh token. Check the OAuth client type (Desktop app) and retry.")
    return Secrets(client_id=creds.client_id, client_secret=creds.client_secret, refresh_token=creds.refresh_token)


def open_api(secrets: Secrets) -> HttpTasksApi:
    """The session gets an access token on the first call and refreshes it when it expires."""
    creds = Credentials(
        token=None,
        refresh_token=secrets.refresh_token,
        client_id=secrets.client_id,
        client_secret=secrets.client_secret,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    return HttpTasksApi(AuthorizedSession(creds))
