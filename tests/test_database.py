from app.auth import hash_password, verify_password
from app.db import Database
from app.domain import RawPaper


def make_paper(source: str = "crossref", abstract: str = "") -> RawPaper:
    return RawPaper(
        source=source,
        source_id="10.1234/test",
        title="Aeroacoustic Test Paper",
        doi="10.1234/test",
        abstract=abstract,
        venue_slug="jsv",
        venue_name="Journal of Sound and Vibration",
        venue_kind="journal",
        published_date="2026-10-01",
        online_date="2026-10-01",
    )


def test_upsert_deduplicates_by_doi(tmp_path) -> None:
    database = Database(tmp_path / "radar.db")
    database.init()
    first_id, first_new = database.upsert_paper(make_paper())
    second_id, second_new = database.upsert_paper(
        make_paper(source="rss", abstract="Newly available abstract")
    )
    assert first_id == second_id
    assert first_new is True
    assert second_new is False
    paper = database.get_paper(first_id)
    assert paper is not None
    assert paper["abstract"] == "Newly available abstract"


def test_feedback_is_persisted(tmp_path) -> None:
    database = Database(tmp_path / "radar.db")
    database.init()
    paper_id, _ = database.upsert_paper(make_paper())
    database.set_feedback(paper_id, "important")
    assert database.feedback_score(paper_id) == 1.0
    database.set_feedback(paper_id, "ignore")
    assert database.feedback_score(paper_id) == -1.0


def test_runtime_settings_and_admin_are_persisted(tmp_path) -> None:
    database = Database(tmp_path / "radar.db")
    database.init()
    database.set_app_settings(
        {
            "smtp_host": "smtp.example.edu.cn",
            "llm_enabled": "true",
            "summary_limit": "12",
        }
    )
    encoded = hash_password("a-long-admin-password")
    database.ensure_initial_admin("admin", encoded)
    database.ensure_initial_admin("admin", hash_password("must-not-replace"))
    database.ensure_initial_admin("second-admin", hash_password("must-not-create"))

    assert database.get_app_settings()["smtp_host"] == "smtp.example.edu.cn"
    user = database.get_user("ADMIN")
    assert user is not None
    assert verify_password("a-long-admin-password", user["password_hash"])
    assert not verify_password("must-not-replace", user["password_hash"])
    assert database.get_user("second-admin") is None

