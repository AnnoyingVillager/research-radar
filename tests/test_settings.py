import re
import sqlite3

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.db import Database

ADMIN_PASSWORD = "a-secure-admin-password"


def make_test_app(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        cache_dir=tmp_path / "cache",
        papers_dir=tmp_path / "papers",
        secrets_dir=tmp_path / "secrets",
        tls_enabled=True,
        session_https_only=True,
        tls_hostnames="research-radar.test,localhost,127.0.0.1",
    )
    settings.ensure_directories()
    database = Database(
        settings.database_path,
        settings_key_path=settings.settings_key_path,
    )
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "database", database)
    return settings, database


def create_admin(client: TestClient, settings: Settings) -> None:
    token = settings.setup_token_path.read_text(encoding="ascii").strip()
    response = client.post(
        "/setup",
        data={
            "setup_token": token,
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "confirm_password": ADMIN_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]


def get_csrf_token(client: TestClient, path: str = "/settings") -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_setup_login_and_save_runtime_settings(tmp_path, monkeypatch) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)

    with TestClient(main.app, base_url="https://testserver") as client:
        setup_page = client.get("/setup")
        assert setup_page.status_code == 200
        assert "Content-Security-Policy" in setup_page.headers
        assert setup_page.headers["Cache-Control"] == "no-store"
        assert setup_page.headers["Strict-Transport-Security"] == "max-age=31536000"
        assert "初始化令牌" in setup_page.text
        assert settings.setup_token_path.exists()

        create_admin(client, settings)
        assert not settings.setup_token_path.exists()
        assert database.has_users()

        csrf_token = get_csrf_token(client)
        saved = client.post(
            "/settings",
            data={
                "csrf_token": csrf_token,
                "openalex_api_key": "openalex-secret",
                "openurl_base": "https://library.example.edu.cn/openurl",
                "openurl_doi_param": "id=doi:",
                "llm_enabled": "on",
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "llm_model": "test-model",
                "summary_limit": "20",
                "smtp_host": "smtp.example.edu.cn",
                "smtp_port": "587",
                "smtp_starttls": "on",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303
        assert saved.headers["location"] == "/settings?saved=1"

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

    stored = database.get_app_settings()
    assert stored["openalex_api_key"] == "openalex-secret"
    assert stored["llm_enabled"] == "true"
    assert stored["smtp_host"] == "smtp.example.edu.cn"

    with sqlite3.connect(database.path) as connection:
        raw_key = connection.execute(
            "SELECT value FROM app_settings WHERE key='openalex_api_key'",
        ).fetchone()[0]
    assert raw_key.startswith("enc:v1:")
    assert "openalex-secret" not in raw_key


def test_settings_normalize_legacy_opencode_go_url(tmp_path, monkeypatch) -> None:
    _, database = make_test_app(tmp_path, monkeypatch)

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, main.settings)
        csrf_token = get_csrf_token(client)
        saved = client.post(
            "/settings",
            data={
                "csrf_token": csrf_token,
                "openurl_doi_param": "id=doi:",
                "llm_enabled": "on",
                "llm_base_url": "https://opencode.ai/zen/go/v1",
                "llm_model": "glm-5.3-flash",
                "summary_limit": "20",
                "smtp_port": "587",
                "smtp_starttls": "on",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

        settings_page = client.get("/settings")
        assert settings_page.status_code == 200
        assert "https://opencode.ai/inference/go/openai/v1" in settings_page.text

    stored = database.get_app_settings()
    assert stored["llm_base_url"] == "https://opencode.ai/inference/go/openai/v1"


def test_setup_rejects_bad_token_weak_password_and_duplicate_setup(
    tmp_path,
    monkeypatch,
) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)

    with TestClient(main.app, base_url="https://testserver") as client:
        token = settings.setup_token_path.read_text(encoding="ascii").strip()

        bad_token = client.post(
            "/setup",
            data={
                "setup_token": "wrong-token",
                "username": "admin",
                "password": ADMIN_PASSWORD,
                "confirm_password": ADMIN_PASSWORD,
            },
        )
        assert bad_token.status_code == 400
        assert "初始化令牌不正确" in bad_token.text

        weak_password = client.post(
            "/setup",
            data={
                "setup_token": token,
                "username": "admin",
                "password": "short",
                "confirm_password": "short",
            },
        )
        assert weak_password.status_code == 400
        assert "至少需要 12 个字符" in weak_password.text

        mismatch = client.post(
            "/setup",
            data={
                "setup_token": token,
                "username": "admin",
                "password": ADMIN_PASSWORD,
                "confirm_password": "different-password",
            },
        )
        assert mismatch.status_code == 400
        assert "密码不一致" in mismatch.text
        assert not database.has_users()

        create_admin(client, settings)

    with TestClient(main.app, base_url="https://testserver") as client:
        duplicate = client.get("/setup", follow_redirects=False)
        assert duplicate.status_code == 303
        assert duplicate.headers["location"] == "/login"


def test_settings_reject_plaintext_secret_transport(tmp_path, monkeypatch) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, settings)
        csrf_token = get_csrf_token(client)

        http_llm_key = client.post(
            "/settings",
            data={
                "csrf_token": csrf_token,
                "openurl_doi_param": "id=doi:",
                "llm_enabled": "on",
                "llm_base_url": "http://llm.example.test/v1",
                "llm_api_key": "must-not-cross-http",
                "llm_model": "test-model",
                "summary_limit": "20",
                "smtp_port": "587",
                "smtp_starttls": "on",
            },
        )
        assert http_llm_key.status_code == 400
        assert "接口地址必须使用 HTTPS" in http_llm_key.text

        plaintext_smtp = client.post(
            "/settings",
            data={
                "csrf_token": csrf_token,
                "openurl_doi_param": "id=doi:",
                "llm_enabled": "false",
                "llm_base_url": "",
                "llm_model": "",
                "summary_limit": "20",
                "smtp_host": "smtp.example.test",
                "smtp_port": "25",
                "smtp_username": "sender@example.test",
                "smtp_password": "must-not-cross-plaintext-smtp",
                "smtp_from": "sender@example.test",
                "smtp_to": "reader@example.test",
            },
        )
        assert plaintext_smtp.status_code == 400
        assert "必须启用 SSL 或 STARTTLS" in plaintext_smtp.text

    stored = database.get_app_settings()
    assert "llm_api_key" not in stored
    assert "smtp_password" not in stored
