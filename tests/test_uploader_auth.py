import json

from src.uploader import _write_credentials_from_environment


def test_write_credentials_from_environment_overwrites_stale_file(monkeypatch, tmp_path):
    credential_path = tmp_path / "credentials.json"
    credential_path.write_text(json.dumps({"old": "token"}), encoding="utf-8")

    fresh_credentials = {"installed": {"client_id": "new-client", "client_secret": "new-secret"}}
    monkeypatch.setenv("YOUTUBE_CREDENTIALS_FILE", str(credential_path))
    monkeypatch.setenv("YOUTUBE_CREDENTIALS_JSON", json.dumps(fresh_credentials))

    _write_credentials_from_environment()

    assert json.loads(credential_path.read_text(encoding="utf-8")) == fresh_credentials
