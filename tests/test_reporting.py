import pytest

from app.config import Settings, load_venues
from app.db import Database
from app.domain import RawPaper
from app.reporting import ReportService


@pytest.mark.asyncio
async def test_generate_daily_writes_files(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        secrets_dir=tmp_path / "secrets",
    )
    settings.ensure_directories()
    database = Database(
        settings.database_path,
        settings_key_path=settings.settings_key_path,
    )
    database.init()
    paper = RawPaper(
        source="test",
        source_id="10.5555/report",
        title="Aeroacoustic cavity noise simulation",
        abstract="A computational aeroacoustics study of cavity noise.",
        doi="10.5555/report",
        venue_slug="jsv",
        venue_name="Journal of Sound and Vibration",
        venue_kind="journal",
    )
    paper_id, _ = database.upsert_paper(paper)
    database.update_scores(
        paper_id,
        venue=1,
        relevance=0.9,
        novelty=0.5,
        momentum=0.55,
        openness=0,
        feedback=0.5,
        final=0.75,
        tags=["气动声学"],
    )
    report_id = await ReportService(database, settings, load_venues()).generate_daily(
        notify=False
    )
    report = database.get_report(report_id)
    assert report is not None
    assert "科研雷达日报" in report["title"]
    assert (settings.reports_dir / f"{report['report_date']}-daily.md").exists()

