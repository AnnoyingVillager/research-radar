from __future__ import annotations

import asyncio
import io
import re

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.config import Settings, SourcePolicy, Venue
from app.db import Database
from app.domain import CollectionResult
from app.normalize import clean_text, hash_text
from app.sources.http import request_headers, request_with_retry

IMPORTANT_TERMS = (
    "paper",
    "program",
    "session",
    "aeroacoustic",
    "acoustic",
    "fluid",
    "turbulence",
    "call for",
    "abstract",
    "proceedings",
    "speaker",
    "forum",
    "conference",
    "paper",
    "论文",
    "报告",
    "专题",
)


class ConferenceCollector:
    def __init__(
        self,
        settings: Settings,
        policy: SourcePolicy,
        http_options: dict[str, int | float],
        database: Database,
    ):
        self.settings = settings
        self.policy = policy
        self.timeout = float(http_options.get("timeout_seconds", 30))
        self.retry_wait = float(http_options.get("retry_wait_seconds", 5))
        self.database = database

    async def collect(self, conferences: list[Venue]) -> CollectionResult:
        result = CollectionResult()
        if not self.policy.enabled:
            return result

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            trust_env=True,
        ) as client:
            for venue in conferences:
                for page in venue.pages:
                    url = str(page.url)
                    existing = self.database.conference_source(venue.slug, url)
                    headers = request_headers(
                        self.settings.user_agent,
                        conditional={
                            "If-None-Match": existing.get("etag", "") if existing else "",
                            "If-Modified-Since": (
                                existing.get("last_modified", "") if existing else ""
                            ),
                        },
                    )
                    try:
                        response = await request_with_retry(
                            client,
                            url,
                            headers=headers,
                            max_retries=1,
                            retry_wait_seconds=self.retry_wait,
                        )
                        if response.status_code == 304:
                            self.database.touch_conference_source(venue.slug, url)
                            result.stats["conference_pages"] = (
                                result.stats.get("conference_pages", 0) + 1
                            )
                            continue
                        text, page_title = _extract_content(response)
                        text = text[: self.policy.max_text_chars]
                        text_hash = hash_text(text)
                        previous_hash = existing.get("last_hash", "") if existing else ""
                        if previous_hash and previous_hash != text_hash:
                            excerpt = _relevant_excerpt(text)
                            self.database.add_conference_update(
                                venue_slug=venue.slug,
                                venue_name=venue.name,
                                url=url,
                                label=page.label,
                                page_type=page.type,
                                title=page_title or f"{venue.name} {page.label}",
                                excerpt=excerpt,
                            )
                            result.stats["conference_updates"] = (
                                result.stats.get("conference_updates", 0) + 1
                            )
                        self.database.save_conference_snapshot(
                            venue_slug=venue.slug,
                            url=url,
                            label=page.label,
                            page_type=page.type,
                            text=text,
                            text_hash=text_hash,
                            etag=response.headers.get("ETag", ""),
                            last_modified=response.headers.get("Last-Modified", ""),
                        )
                        result.stats["conference_pages"] = (
                            result.stats.get("conference_pages", 0) + 1
                        )
                    except Exception as exc:
                        result.errors.append(f"会议页面 {venue.name} / {page.label}: {exc}")
                    await asyncio.sleep(self.policy.request_delay_seconds)
        return result


def _extract_content(response: httpx.Response) -> tuple[str, str]:
    content_type = response.headers.get("Content-Type", "").lower()
    if "application/pdf" in content_type or response.url.path.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(response.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:80])
        return clean_text(text, max_length=200000), ""

    soup = BeautifulSoup(response.text, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "", 500)
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    lines = [clean_text(line, 500) for line in text.splitlines()]
    return "\n".join(line for line in lines if line), title


def _relevant_excerpt(text: str) -> str:
    candidates: list[str] = []
    for line in text.splitlines():
        normalized = line.strip()
        if not (20 <= len(normalized) <= 500):
            continue
        lower = normalized.lower()
        if any(term in lower for term in IMPORTANT_TERMS):
            if normalized not in candidates:
                candidates.append(normalized)
        if len(candidates) >= 8:
            break
    if not candidates:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact[:800]
    return "\n".join(candidates)

