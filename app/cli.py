from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_runtime_settings, get_settings, load_interests, load_venues
from app.db import Database
from app.domain import RawPaper
from app.pipeline import DailyPipeline, generate_weekly
from app.reporting import ReportService
from app.scheduler import run_scheduler
from app.scoring import score_paper


def main() -> None:
    parser = argparse.ArgumentParser(description="Venue-first research radar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Initialize database and venue registry")
    run_parser = subparsers.add_parser("run-daily", help="Collect, score, summarize, and report")
    run_parser.add_argument("--no-report", action="store_true")
    subparsers.add_parser("report-daily", help="Regenerate a daily report from stored papers")
    subparsers.add_parser("report-weekly", help="Generate a weekly report")
    subparsers.add_parser("seed-demo", help="Insert clearly labelled demo records")
    subparsers.add_parser("scheduler", help="Run the foreground scheduler")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.logs_dir / "radar.log", encoding="utf-8"),
        ],
    )
    database = Database(settings.database_path)
    database.init()

    if args.command == "init-db":
        _seed_venues(database)
        print(f"数据库已初始化：{settings.database_path}")
    elif args.command == "run-daily":
        asyncio.run(DailyPipeline(database, settings).run(generate_report=not args.no_report))
    elif args.command == "report-daily":
        venues = load_venues()
        runtime_settings = get_runtime_settings(database, settings)
        asyncio.run(
            ReportService(database, runtime_settings, venues).generate_daily(notify=False)
        )
    elif args.command == "report-weekly":
        asyncio.run(generate_weekly(database, settings))
    elif args.command == "seed-demo":
        _seed_demo(database, settings)
    elif args.command == "scheduler":
        asyncio.run(run_scheduler(database, settings))


def _seed_venues(database: Database) -> None:
    for venue in load_venues().all:
        database.upsert_venue(venue.model_dump(mode="json"))


def _seed_demo(database: Database, settings) -> None:
    _seed_venues(database)
    venues = load_venues().by_slug()
    interests = load_interests()
    now = datetime.now(ZoneInfo(settings.app_timezone)).date().isoformat()
    samples = [
        RawPaper(
            source="demo",
            source_id="demo-jsv",
            title="[示例] High-order simulation of trailing-edge noise in a low-speed airfoil flow",
            abstract=(
                "This is a local demonstration record, not a real publication. "
                "The example uses a high-order flow solver and acoustic analogy to study "
                "trailing-edge noise, turbulence, and boundary-layer effects."
            ),
            authors=["Demo Author A", "Demo Author B"],
            affiliations=["Local Demonstration Dataset"],
            venue_slug="jsv",
            venue_name=venues["jsv"].name,
            venue_kind="journal",
            publisher=venues["jsv"].publisher,
            published_date=now,
            online_date=now,
            url="https://example.invalid/demo-jsv",
            is_oa=True,
        ),
        RawPaper(
            source="demo",
            source_id="demo-jfm",
            title="[示例] Data-driven modal analysis of a turbulent cavity flow",
            abstract=(
                "This is a demonstration record. It describes a reduced-order model "
                "for turbulent cavity flow and flow instability using simulation data."
            ),
            authors=["Demo Author C"],
            venue_slug="jfm",
            venue_name=venues["jfm"].name,
            venue_kind="journal",
            publisher=venues["jfm"].publisher,
            published_date=now,
            online_date=now,
            url="https://example.invalid/demo-jfm",
        ),
    ]
    ids: list[int] = []
    for sample in samples:
        paper_id, _ = database.upsert_paper(sample)
        ids.append(paper_id)
    for paper_id in ids:
        paper = database.get_paper(paper_id)
        if not paper:
            continue
        breakdown = score_paper(paper, interests, venues[paper["venue_slug"]])
        database.update_scores(
            paper_id,
            venue=breakdown.venue,
            relevance=breakdown.relevance,
            novelty=breakdown.novelty,
            momentum=breakdown.momentum,
            openness=breakdown.openness,
            feedback=breakdown.feedback,
            final=breakdown.final,
            tags=breakdown.tags,
        )
        database.mark_summary_status(paper_id, "metadata_only")
    print("已插入 2 条明确标注的本地演示数据。")


if __name__ == "__main__":
    main()

