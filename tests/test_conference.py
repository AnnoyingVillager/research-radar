from pathlib import Path

import httpx
import pytest

from app.config import Settings, SourcePolicy, Venue
from app.sources import conference as conference_module
from app.sources.conference import ConferenceCollector


class FakeDatabase:
    def __init__(self) -> None:
        self.touched: list[tuple[str, str]] = []

    def conference_source(self, venue_slug: str, url: str) -> dict[str, str]:
        return {"etag": '"abc"', "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT"}

    def touch_conference_source(self, venue_slug: str, url: str) -> None:
        self.touched.append((venue_slug, url))


@pytest.mark.asyncio
async def test_conference_304_counts_as_successful_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venue = Venue.model_validate(
        {
            "slug": "test-conference",
            "name": "Test Conference",
            "kind": "conference",
            "homepage": "https://example.test/",
            "pages": [
                {
                    "label": "Program",
                    "type": "program",
                    "url": "https://example.test/program",
                }
            ],
        }
    )
    database = FakeDatabase()

    async def fake_request_with_retry(
        client: httpx.AsyncClient,
        url: str,
        **_: object,
    ) -> httpx.Response:
        return httpx.Response(304, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        conference_module,
        "request_with_retry",
        fake_request_with_retry,
    )
    collector = ConferenceCollector(
        settings=Settings(config_dir=Path("config")),
        policy=SourcePolicy(request_delay_seconds=0),
        http_options={"timeout_seconds": 1},
        database=database,  # type: ignore[arg-type]
    )

    result = await collector.collect([venue])

    assert result.errors == []
    assert result.stats == {"conference_pages": 1}
    assert database.touched == [("test-conference", "https://example.test/program")]
