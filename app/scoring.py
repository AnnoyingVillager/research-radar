from __future__ import annotations

import math
from typing import Any

from app.config import InterestsConfig, Venue
from app.domain import ScoreBreakdown
from app.normalize import age_days

VENUE_TIER_SCORE = {1: 1.0, 2: 0.75, 3: 0.55}


def score_paper(
    paper: dict[str, Any],
    interests: InterestsConfig,
    venue: Venue,
    *,
    feedback: float = 0.0,
) -> ScoreBreakdown:
    haystack = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    matched_tags: list[str] = []
    relevance_parts: list[float] = []

    for group in interests.groups:
        matches = sum(1 for keyword in group.keywords if keyword.lower() in haystack)
        if matches:
            matched_tags.append(group.label)
            relevance_parts.append(group.weight * min(1.0, matches / 3))

    max_weight = sum(group.weight for group in interests.groups) or 1.0
    relevance = min(1.0, sum(relevance_parts) / max(1.0, max_weight * 0.45))

    negative_hits = sum(
        1 for keyword in interests.negative_keywords if keyword.lower() in haystack
    )
    if negative_hits:
        relevance = max(0.0, relevance - min(0.8, negative_hits * 0.4))

    venue_score = VENUE_TIER_SCORE.get(venue.tier, 0.55)
    novelty = _bounded(paper.get("novelty_score", 0.5))
    momentum = citation_momentum(
        paper.get("cited_by_count", 0),
        age_days(paper.get("online_date", ""), paper.get("published_date", "")),
    )
    openness = 1.0 if paper.get("is_oa") else 0.0
    feedback = _bounded((feedback + 1) / 2)

    final = (
        0.25 * venue_score
        + 0.25 * relevance
        + 0.20 * momentum
        + 0.15 * novelty
        + 0.10 * openness
        + 0.05 * feedback
    )
    return ScoreBreakdown(
        venue=round(venue_score, 4),
        relevance=round(relevance, 4),
        momentum=round(momentum, 4),
        novelty=round(novelty, 4),
        openness=round(openness, 4),
        feedback=round(feedback, 4),
        final=round(final, 4),
        tags=matched_tags,
    )


def citation_momentum(cited_by_count: int, age: int) -> float:
    if age <= 14:
        return 0.55
    citations = max(0, int(cited_by_count or 0))
    rate = citations / max(age, 1)
    # Around two citations per ten days reaches a strong momentum score.
    return round(min(1.0, 0.25 + math.log1p(rate * 20) / 3), 4)


def _bounded(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

