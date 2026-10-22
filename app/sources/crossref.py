from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings, SourcePolicy, Venue
from app.domain import CollectionResult, RawPaper
from app.normalize import (
    clean_abstract,
    clean_text,
    crossref_date,
    normalize_doi,
    stable_id,
    title_from_payload,
)
from app.sources.http import RateLimitedError, request_headers, request_with_retry


class CrossrefCollector:
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

        cutoff = (
            datetime.now(UTC).date() - timedelta(days=self.policy.lookback_days)
        ).isoformat()
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            trust_env=True,
            headers={"Accept": "application/json"},
        ) as client:
            for venue in journals:
                if not venue.issns:
                    result.errors.append(f"{venue.name}: 未配置 ISSN")
                    continue
                issn = venue.issns[0]
                url = f"https://api.crossref.org/journals/{issn}/works"
                params = {
                    "filter": f"from-created-date:{cutoff},type:journal-article",
                    "rows": self.policy.rows_per_journal,
                    "sort": "created",
                    "order": "desc",
                    "mailto": self.settings.crossref_email,
                }
                try:
                    response = await request_with_retry(
                        client,
                        url,
                        params=params,
                        headers=request_headers(self.settings.user_agent),
                        max_retries=self.policy.max_retries,
                        retry_wait_seconds=self.retry_wait,
                    )
                    items = response.json().get("message", {}).get("items", [])
                    result.papers.extend(
                        paper
                        for item in items
                        if (paper := self._parse_item(item, venue)) is not None
                    )
                    result.stats["crossref_journals"] = (
                        result.stats.get("crossref_journals", 0) + 1
                    )
                except RateLimitedError:
                    result.errors.append(
                        "Crossref 已限流，跳过剩余期刊。请设置 CROSSREF_EMAIL 或稍后重跑。"
                    )
                    break
                except Exception as exc:
                    result.errors.append(f"Crossref {venue.name}: {exc}")
                await asyncio.sleep(self.policy.request_delay_seconds)
        return result

    def _parse_item(self, item: dict, venue: Venue) -> RawPaper | None:
        title = title_from_payload(item.get("title"))
        if not title:
            return None
        doi = normalize_doi(item.get("DOI", ""))
        authors: list[str] = []
        affiliations: list[str] = []
        for author in item.get("author", []) or []:
            name = " ".join(
                part for part in (author.get("given", ""), author.get("family", "")) if part
            ).strip()
            if name:
                authors.append(name)
            for affiliation in author.get("affiliation", []) or []:
                name = clean_text(affiliation.get("name", ""), max_length=300)
                if name and name not in affiliations:
                    affiliations.append(name)

        licenses = item.get("license", []) or []
        is_oa = any(
            "creativecommons.org" in str(license_item.get("URL", "")).lower()
            for license_item in licenses
        )
        published_online = crossref_date(item.get("published-online"))
        published_print = crossref_date(item.get("published-print"))
        issued = crossref_date(item.get("issued"))
        created = crossref_date(item.get("created"))
        online_date = published_online or issued or created
        published_date = published_print or issued or online_date

        return RawPaper(
            source="crossref",
            source_id=doi or stable_id(f"{venue.slug}:{title}"),
            title=title,
            doi=doi,
            abstract=clean_abstract(item.get("abstract", "")),
            authors=authors,
            affiliations=affiliations,
            venue_slug=venue.slug,
            venue_name=venue.name,
            venue_kind=venue.kind,
            publisher=venue.publisher,
            published_date=published_date,
            online_date=online_date,
            url=f"https://doi.org/{doi}" if doi else item.get("URL", ""),
            is_oa=is_oa,
            cited_by_count=int(item.get("is-referenced-by-count", 0) or 0),
            metadata={"type": item.get("type", ""), "subject": item.get("subject", [])},
        )

