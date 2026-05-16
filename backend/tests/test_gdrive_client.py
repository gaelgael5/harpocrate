"""La couche gdrive_client expose les helpers utilisés par provider + service OAuth."""

from __future__ import annotations

from app.services.remote_backup_providers import gdrive_client


def test_gdrive_client_exports() -> None:
    """Surface minimale stable."""
    assert hasattr(gdrive_client, "build_credentials")
    assert hasattr(gdrive_client, "build_drive_service")
    assert hasattr(gdrive_client, "build_flow")
    assert hasattr(gdrive_client, "fetch_user_email")
    assert hasattr(gdrive_client, "refresh")


def test_build_credentials_returns_google_credentials() -> None:
    creds = gdrive_client.build_credentials(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-fake",
        refresh_token="rt-fake",
        token_uri="https://oauth2.googleapis.com/token",
        scope="https://www.googleapis.com/auth/drive.file",
    )
    from google.oauth2.credentials import Credentials

    assert isinstance(creds, Credentials)
    assert creds.refresh_token == "rt-fake"


def test_build_flow_uses_drive_file_scope() -> None:
    flow = gdrive_client.build_flow(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-fake",
        redirect_uri="https://harpo.example.com/callback",
    )
    assert flow.oauth2session.scope == ["https://www.googleapis.com/auth/drive.file"]
