from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class RawPaper:
    source: str
    source_id: str
    title: str
    venue_slug: str
    venue_name: str
    venue_kind: str = "journal"
    doi: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    publisher: str = ""
    published_date: str = ""
    online_date: str = ""
    url: str = ""
    pdf_url: str = ""
    is_oa: bool = False
    cited_by_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectionResult:
    papers: list[RawPaper] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def merge(self, other: CollectionResult) -> None:
        self.papers.extend(other.papers)
        self.errors.extend(other.errors)
        for key, value in other.stats.items():
            self.stats[key] = self.stats.get(key, 0) + value


@dataclass(slots=True)
class ScoreBreakdown:
    venue: float
    relevance: float
    momentum: float
    novelty: float
    openness: float
    feedback: float
    final: float
    tags: list[str]


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)

