from app.config import load_interests, load_venues
from app.normalize import age_days
from app.scoring import citation_momentum, score_paper


def test_relevant_aeroacoustics_paper_scores_higher() -> None:
    interests = load_interests()
    venues = load_venues()
    venue = venues.by_slug()["jsv"]
    relevant = {
        "title": "Trailing-edge noise and boundary-layer turbulence",
        "abstract": "A high-order computational aeroacoustics method is used for jet noise.",
        "cited_by_count": 0,
        "online_date": "2026-10-20",
        "is_oa": True,
    }
    unrelated = {
        "title": "A book review about academic publishing",
        "abstract": "Editorial and correction notice.",
        "cited_by_count": 0,
        "online_date": "2026-10-20",
        "is_oa": False,
    }
    relevant_score = score_paper(relevant, interests, venue)
    unrelated_score = score_paper(unrelated, interests, venue)
    assert relevant_score.final > unrelated_score.final
    assert "气动声学" in relevant_score.tags


def test_young_paper_is_not_penalized_for_zero_citations() -> None:
    assert citation_momentum(0, 3) == 0.55
    assert age_days("2999-01-01") == 0

