import re

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.db import Database


def test_login_and_save_runtime_settings(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        cache_dir=tmp_path / "cache",
        papers_dir=tmp_path / "papers",
        admin_username="admin",
        admin_password="initial-admin-password",
        session_secret="test-session-secret",
    )
    settings.ensure_directories()
    database = Database(settings.database_path)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "database", database)

    with TestClient(main.app) as client:
        redirect = client.get("/settings", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"].startswith("/login")

        failed = client.post(
            "/login",
            data={"username": "admin", "password": "wrong", "next": "/settings"},
        )
        assert failed.status_code == 400

        logged_in = client.post(
            "/login",
            data={
                "username": "admin",
                "password": "initial-admin-password",
                "next": "/settings",
            },
            follow_redirects=True,
        )
        assert logged_in.status_code == 200
        assert "系统设置" in logged_in.text
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', logged_in.text)
        assert csrf_match

        saved = client.post(
            "/settings",
            data={
                "csrf_token": csrf_match.group(1),
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
            follow_redirects=True,
        )
        assert saved.status_code == 200
        assert "设置已保存" in saved.text

    stored = database.get_app_settings()
    assert stored["openalex_api_key"] == "openalex-secret"
    assert stored["llm_enabled"] == "true"
    assert stored["smtp_host"] == "smtp.example.edu.cn"
