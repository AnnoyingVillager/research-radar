from types import SimpleNamespace

import pytest

from app.pipeline import DailyPipeline


class StubDatabase:
    def __init__(self, papers: list[dict]):
        self.papers = papers
        self.saved: list[tuple[int, dict, str]] = []
        self.statuses: list[tuple[int, str]] = []

    def get_recent_papers(self, days: int, limit: int) -> list[dict]:
        assert days == 14
        assert limit == 200
        return self.papers

    def save_summary(self, paper_id: int, summary: dict, model: str) -> None:
        self.saved.append((paper_id, summary, model))

    def mark_summary_status(self, paper_id: int, status: str) -> None:
        self.statuses.append((paper_id, status))


class StubLLM:
    configured = True

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def summarize(self, paper: dict) -> dict:
        self.calls.append(int(paper["id"]))
        return {"title_zh": f"总结 {paper['id']}"}


@pytest.mark.asyncio
async def test_summary_limit_is_applied_before_skipping_completed_papers() -> None:
    database = StubDatabase(
        [
            {
                "id": 1,
                "summary_status": "complete",
                "abstract": "x" * 200,
            },
            {
                "id": 2,
                "summary_status": "pending",
                "abstract": "x" * 200,
            },
            {
                "id": 3,
                "summary_status": "pending",
                "abstract": "x" * 200,
            },
        ]
    )
    llm = StubLLM()
    pipeline = DailyPipeline.__new__(DailyPipeline)
    pipeline.database = database
    pipeline.settings = SimpleNamespace(summary_limit=2, llm_model="test-model")
    pipeline.llm = llm

    stats = await pipeline._summarize_recent()

    assert llm.calls == [2]
    assert [paper_id for paper_id, _, _ in database.saved] == [2]
    assert stats["summaries_complete"] == 1
