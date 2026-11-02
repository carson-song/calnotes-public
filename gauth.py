"""Google sign-in shared by the digest (Gmail) and the approval step (Calendar).

Each component gets its own token with only its own scope (least privilege): a bug in the digest code
can't touch your calendar, and the approval step can't send mail. Tokens live in secrets/ (git-ignored).
Sign in with the SANDBOX account when the browser opens.
"""
import os
from pathlib import Path

SECRETS = Path(__file__).parent / "secrets"


def service(api: str, version: str, scopes: list, token_name: str):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise SystemExit("pip install google-api-python-client google-auth-oauthlib") from e
    client_file, token_file = SECRETS / "google_client.json", SECRETS / token_name
    creds = Credentials.from_authorized_user_file(token_file, scopes) if token_file.exists() else None
    if creds and creds.expired and creds.refresh_token:
        from google.auth.exceptions import RefreshError
        try:
            creds.refresh(Request())
        except RefreshError:
            raise SystemExit(f"{token_name} has expired or was revoked (in Testing mode tokens last 7 days). "
                             f"Delete secrets/{token_name} and run again to sign in.") from None
    if not creds or not creds.valid:
        if os.environ.get("CALNOTES_HEADLESS"):
            # A scheduled run has no one to click through a browser: opening one would hang forever.
            raise SystemExit(f"{token_name} needs a sign-in. Run the command once by hand on this machine.")
        if not client_file.exists():
            raise SystemExit(f"Missing {client_file}. See README, 'Email digest' setup.")
        creds = InstalledAppFlow.from_client_secrets_file(client_file, scopes).run_local_server(port=0)
    token_file.write_text(creds.to_json())
    os.chmod(token_file, 0o600)
    return build(api, version, credentials=creds, cache_discovery=False)
