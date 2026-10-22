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

