from __future__ import annotations

import asyncio

import feedparser
import httpx

from app.config import Settings, SourcePolicy, Venue
from app.domain import CollectionResult, RawPaper
from app.normalize import (
    clean_text,
    extract_doi_from_text,
    normalize_doi,
    rss_timestamp_to_date,
    stable_id,
)
from app.sources.http import request_headers, request_with_retry


class RSSCollector:
    def __init__(
        self,
        settings: Settings,
        policy: SourcePolicy,
        http_options: dict[str, int | float],
    ):
        self.settings = settings
        self.policy = policy
        self.timeout = float(http_options.get("timeout_seconds", 30))
        self.retry_wait = float(http_options.get("retry_wait_seconds", 5))

    async def collect(self, journals: list[Venue]) -> CollectionResult:
        result = CollectionResult()
        if not self.policy.enabled:
            return result

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            trust_env=True,
        ) as client:
            for venue in journals:
                for feed_url in venue.rss:
                    try:
                        response = await request_with_retry(
                            client,
                            str(feed_url),
                            headers=request_headers(self.settings.user_agent),
                            max_retries=2,
                            retry_wait_seconds=self.retry_wait,
                        )
                        feed = feedparser.parse(response.content)
                        for entry in feed.entries[: self.policy.max_entries_per_feed]:
                            paper = self._parse_entry(entry, venue, str(feed_url))
                            if paper:
                                result.papers.append(paper)
                        result.stats["rss_feeds"] = result.stats.get("rss_feeds", 0) + 1
                    except Exception as exc:
                        result.errors.append(f"RSS {venue.name}: {exc}")
                    await asyncio.sleep(self.policy.request_delay_seconds)
        return result

    def _parse_entry(self, entry: dict, venue: Venue, feed_url: str) -> RawPaper | None:
        title = clean_text(entry.get("title", ""), max_length=1000)
        if not title:
            return None

        link = str(entry.get("link", ""))
        identifier = " ".join(
            str(entry.get(key, ""))
            for key in ("id", "guid", "prism_doi", "dc_identifier", "summary")
        )
        doi = normalize_doi(entry.get("prism_doi", "")) or extract_doi_from_text(
            f"{identifier} {link}"
        )
        published = rss_timestamp_to_date(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )
        summary = clean_text(entry.get("summary", ""), max_length=12000)
        # ScienceDirect feeds mostly contain volume/date metadata. Do not present it as an abstract.
        abstract = summary if len(summary) >= 350 and "Publication date:" not in summary else ""
        return RawPaper(
            source="rss",
            source_id=doi or str(entry.get("id", stable_id(f"{feed_url}:{title}"))),
            title=title,
            doi=doi,
            abstract=abstract,
            authors=_parse_authors(entry),
            venue_slug=venue.slug,
            venue_name=venue.name,
            venue_kind=venue.kind,
            publisher=venue.publisher,
            published_date=published,
            online_date=published,
            url=link or (f"https://doi.org/{doi}" if doi else str(venue.homepage)),
            metadata={"feed_url": feed_url},
        )


def _parse_authors(entry: dict) -> list[str]:
    authors = entry.get("authors") or entry.get("author_detail") or []
    if isinstance(authors, dict):
        authors = [authors]
    parsed: list[str] = []
    for author in authors:
        if isinstance(author, dict):
            name = clean_text(author.get("name", ""), max_length=300)
            if name:
                parsed.append(name)
        elif isinstance(author, str):
            names = [
                clean_text(name, max_length=300)
                for name in author.split(",")
                if clean_text(name, max_length=300)
            ]
            parsed.extend(names)
    return list(dict.fromkeys(parsed))

