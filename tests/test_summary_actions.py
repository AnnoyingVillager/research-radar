import re

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.db import Database
from app.domain import RawPaper

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
        llm_enabled=True,
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
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


def get_csrf_token(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def make_paper(*, source_id: str = "10.1234/summary", abstract: str = "x" * 200) -> RawPaper:
    return RawPaper(
        source="crossref",
        source_id=source_id,
        title="Aeroacoustic Test Paper",
        doi=source_id,
        abstract=abstract,
        venue_slug="jsv",
        venue_name="Journal of Sound and Vibration",
        venue_kind="journal",
        published_date="2026-10-01",
        online_date="2026-10-01",
    )


class SuccessfulLLM:
    calls: list[int] = []

    def __init__(self, settings: Settings):
        self.settings = settings
        self.configured = True

    async def summarize(self, paper: dict) -> dict:
        self.calls.append(int(paper["id"]))
        return {
            "title_zh": "更新后的中文标题",
            "problem": "更新后的问题",
            "method": "更新后的方法",
            "key_results": "更新后的结果",
            "limitations": "更新后的局限",
            "relevance": "更新后的相关性",
            "read_reason": "更新后的阅读理由",
            "novelty_score": 0.8,
        }


class FailedLLM(SuccessfulLLM):
    async def summarize(self, paper: dict) -> None:
        self.calls.append(int(paper["id"]))
        return None


def test_paper_actions_include_manual_summary_buttons(tmp_path, monkeypatch) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "LLMService", SuccessfulLLM)

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, settings)
        paper_id, _ = database.upsert_paper(make_paper())

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert f'action="/papers/{paper_id}/summary"' in dashboard.text
        assert "更新 AI 总结" in dashboard.text

        detail = client.get(f"/papers/{paper_id}")
        assert detail.status_code == 200
        assert f'action="/papers/{paper_id}/summary"' in detail.text
        assert "更新 AI 总结" in detail.text


def test_manual_summary_updates_an_existing_complete_summary(tmp_path, monkeypatch) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "LLMService", SuccessfulLLM)
    SuccessfulLLM.calls = []

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, settings)
        paper_id, _ = database.upsert_paper(make_paper())
        database.save_summary(
            paper_id,
            {
                "title_zh": "旧标题",
                "problem": "旧问题",
                "key_results": "旧结果",
            },
            "old-model",
        )
        csrf_token = get_csrf_token(client, f"/papers/{paper_id}")

        response = client.post(
            f"/papers/{paper_id}/summary",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/papers/{paper_id}?summary=updated"
        updated = database.get_paper(paper_id)
        assert updated is not None
        assert updated["title_zh"] == "更新后的中文标题"
        assert updated["summary_status"] == "complete"
        assert updated["summary_model"] == "test-model"
        assert SuccessfulLLM.calls == [paper_id]


def test_manual_summary_rejects_invalid_csrf_and_requires_login(
    tmp_path,
    monkeypatch,
) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "LLMService", SuccessfulLLM)

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, settings)
        paper_id, _ = database.upsert_paper(make_paper())

        invalid_csrf = client.post(
            f"/papers/{paper_id}/summary",
            data={"csrf_token": "invalid"},
        )
        assert invalid_csrf.status_code == 403

        client.cookies.clear()
        unauthenticated = client.post(
            f"/papers/{paper_id}/summary",
            follow_redirects=False,
        )
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == (
            f"/login?next=/papers/{paper_id}"
        )


def test_manual_summary_failure_keeps_existing_summary(tmp_path, monkeypatch) -> None:
    settings, database = make_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "LLMService", FailedLLM)

    with TestClient(main.app, base_url="https://testserver") as client:
        create_admin(client, settings)
        paper_id, _ = database.upsert_paper(make_paper())
        database.save_summary(
            paper_id,
            {
                "title_zh": "保留的旧标题",
                "problem": "保留的旧问题",
                "key_results": "保留的旧结果",
            },
            "old-model",
        )
        csrf_token = get_csrf_token(client, f"/papers/{paper_id}")

        response = client.post(
            f"/papers/{paper_id}/summary",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/papers/{paper_id}?summary=failed"
        preserved = database.get_paper(paper_id)
        assert preserved is not None
        assert preserved["title_zh"] == "保留的旧标题"
        assert preserved["summary_status"] == "complete"
        assert preserved["summary_model"] == "old-model"
