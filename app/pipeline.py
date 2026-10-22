from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import (
    Settings,
    get_runtime_settings,
    load_interests,
    load_sources,
    load_venues,
)
from app.db import Database
from app.llm import LLMService
from app.reporting import ReportService
from app.scoring import score_paper
from app.sources.conference import ConferenceCollector
from app.sources.crossref import CrossrefCollector
from app.sources.openalex import OpenAlexCollector
from app.sources.rss import RSSCollector

logger = logging.getLogger(__name__)


class DailyPipeline:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = get_runtime_settings(database, settings)
        self.interests = load_interests(self.settings.config_dir / "interests.yaml")
        self.venues = load_venues(self.settings.config_dir / "venues.yaml")
        self.sources = load_sources(self.settings.config_dir / "sources.yaml")
        self.venue_map = self.venues.by_slug()
        self.llm = LLMService(self.settings)

    async def run(self, *, generate_report: bool = True) -> dict[str, Any]:
        job_id = self.database.start_job("daily")
        stats: dict[str, Any] = {}
        errors: list[str] = []
        try:
            self._seed_venues()
            crossref, rss = await asyncio.gather(
                CrossrefCollector(
                    self.settings,
                    self.sources.crossref,
                    self.sources.http,
                ).collect(self.venues.journals),
                RSSCollector(
                    self.settings,
                    self.sources.rss,
                    self.sources.http,
                ).collect(self.venues.journals),
            )
            errors.extend(crossref.errors)
            errors.extend(rss.errors)
            stats["crossref_papers"] = len(crossref.papers)
            stats["rss_papers"] = len(rss.papers)

            seen_ids: set[int] = set()
            new_count = 0
            for paper in [*crossref.papers, *rss.papers]:
                paper_id, is_new = self.database.upsert_paper(paper)
                seen_ids.add(paper_id)
                new_count += int(is_new)
            stats["new_papers"] = new_count
            stats["unique_seen"] = len(seen_ids)

            recent = self.database.get_recent_papers(days=30, limit=500)
            enrich_targets = [paper for paper in recent if paper.get("doi")][
                : self.sources.openalex.enrich_limit
            ]
            openalex = OpenAlexCollector(
                self.settings,
                self.sources.openalex,
                self.sources.http,
            )
            enrichments, openalex_errors = await openalex.enrich(
                [paper["doi"] for paper in enrich_targets]
            )
            errors.extend(openalex_errors)
            for paper in enrich_targets:
                enrichment = enrichments.get((paper["doi"] or "").lower())
                if not enrichment:
                    continue
                self.database.apply_enrichment(
                    int(paper["id"]),
                    abstract=enrichment.get("abstract", ""),
                    cited_by_count=enrichment.get("cited_by_count"),
                    is_oa=enrichment.get("is_oa"),
                    pdf_url=enrichment.get("pdf_url", ""),
                )
            for paper in self.database.get_recent_papers(days=30, limit=500):
                self.database.record_citation(
                    int(paper["id"]),
                    int(paper.get("cited_by_count", 0)),
                    "openalex" if (paper.get("doi") or "").lower() in enrichments else "metadata",
                )
            stats["openalex_enriched"] = len(enrichments)

            await self._score_recent()

            summary_stats = await self._summarize_recent()
            stats.update(summary_stats)
            await self._score_recent()

            conference = await ConferenceCollector(
                self.settings,
                self.sources.conference,
                self.sources.http,
                self.database,
            ).collect(self.venues.conferences)
            errors.extend(conference.errors)
            stats.update(conference.stats)

            report_id: int | None = None
            if generate_report:
                report_id = await ReportService(
                    self.database,
                    self.settings,
                    self.venues,
                ).generate_daily(warnings=errors)
                stats["report_id"] = report_id

            status = "partial" if errors else "success"
            self.database.finish_job(job_id, status=status, stats=stats, error="\n".join(errors))
            logger.info("daily pipeline finished: %s", stats)
            return stats
        except Exception as exc:
            logger.exception("daily pipeline failed")
            self.database.finish_job(job_id, status="failed", stats=stats, error=str(exc))
            raise

    def _seed_venues(self) -> None:
        for venue in self.venues.all:
            self.database.upsert_venue(venue.model_dump(mode="json"))

    async def _score_recent(self) -> None:
        for paper in self.database.get_recent_papers(days=30, limit=500):
            venue = self.venue_map.get(paper["venue_slug"])
            if not venue:
                continue
            breakdown = score_paper(
                paper,
                self.interests,
                venue,
                feedback=self.database.feedback_score(int(paper["id"])),
            )
            self.database.update_scores(
                int(paper["id"]),
                venue=breakdown.venue,
                relevance=breakdown.relevance,
                novelty=breakdown.novelty,
                momentum=breakdown.momentum,
                openness=breakdown.openness,
                feedback=breakdown.feedback,
                final=breakdown.final,
                tags=breakdown.tags,
            )

    async def _summarize_recent(self) -> dict[str, int]:
        stats = {"summaries_complete": 0, "summaries_skipped": 0, "summaries_failed": 0}
        candidates = [
            paper
            for paper in self.database.get_recent_papers(days=14, limit=200)
            if paper.get("summary_status") in {"pending", "failed", "metadata_only"}
        ][: self.settings.summary_limit]
        for paper in candidates:
            if len((paper.get("abstract") or "").strip()) < 120:
                self.database.mark_summary_status(int(paper["id"]), "metadata_only")
                stats["summaries_skipped"] += 1
                continue
            if not self.llm.configured:
                stats["summaries_skipped"] += 1
                continue
            summary = await self.llm.summarize(paper)
            if summary:
                self.database.save_summary(int(paper["id"]), summary, self.settings.llm_model)
                stats["summaries_complete"] += 1
            else:
                self.database.mark_summary_status(int(paper["id"]), "failed")
                stats["summaries_failed"] += 1
        return stats


async def generate_weekly(database: Database, settings: Settings) -> int:
    runtime_settings = get_runtime_settings(database, settings)
    venues = load_venues(runtime_settings.config_dir / "venues.yaml")
    database.init()
    for venue in venues.all:
        database.upsert_venue(venue.model_dump(mode="json"))
    return await ReportService(database, runtime_settings, venues).generate_weekly()

