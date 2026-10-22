from __future__ import annotations

import calendar
import hashlib
import html
import re
from datetime import UTC, date, datetime
from typing import Any

from bs4 import BeautifulSoup

DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?，。；：！？])")
TITLE_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().lower()
    for prefix in DOI_PREFIXES:
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.rstrip(" .;,")


def normalize_title(value: str) -> str:
    return " ".join(TITLE_RE.findall((value or "").lower()))


def stable_id(value: str) -> str:
    return hashlib.sha1((value or "").encode("utf-8")).hexdigest()[:20]


def clean_text(value: str, max_length: int = 12000) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = SPACE_RE.sub(" ", text).strip()
    text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text[:max_length]


def clean_abstract(value: str, max_length: int = 12000) -> str:
    text = clean_text(value, max_length=max_length)
    for prefix in ("Abstract ", "ABSTRACT ", "摘要 "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


def crossref_date(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    parts = payload.get("date-parts")
    if not parts or not parts[0]:
        return ""
    values = [int(value) for value in parts[0] if value is not None]
    if not values:
        return ""
    year = values[0]
    month = values[1] if len(values) > 1 else 1
    day = values[2] if len(values) > 2 else 1
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def timestamp_to_date(value: Any) -> str:
    if not value:
        return ""
    try:
        parsed = calendar.timegm(value)
        return datetime.fromtimestamp(parsed, UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def rss_timestamp_to_date(value: Any) -> str:
    return timestamp_to_date(value)


def title_from_payload(payload: Any, fallback: str = "") -> str:
    if isinstance(payload, list) and payload:
        return clean_text(str(payload[0]), max_length=1000)
    if isinstance(payload, str):
        return clean_text(payload, max_length=1000)
    return fallback


def extract_doi_from_text(value: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", value or "", re.IGNORECASE)
    return normalize_doi(match.group(0)) if match else ""


def age_days(paper_date: str, fallback_date: str = "") -> int:
    value = paper_date or fallback_date
    if not value:
        return 365
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return 365
    return max(0, (datetime.now(UTC).date() - parsed).days)


def hash_text(value: str) -> str:
    normalized = SPACE_RE.sub(" ", value).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

