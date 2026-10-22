import pytest

from app.config import Settings
from app.llm import LLMService, parse_json_object


def test_parse_json_object_with_fence() -> None:
    result = parse_json_object(
        """```json
        {"title_zh":"测试","key_results":["结果一","结果二"],"novelty_score":0.8}
        ```"""
    )
    assert result is not None
    assert result["title_zh"] == "测试"
    assert result["key_results"] == "结果一；结果二"
    assert result["novelty_score"] == 0.8


@pytest.mark.asyncio
async def test_llm_api_key_is_never_sent_over_plain_http(monkeypatch) -> None:
    service = LLMService(
        Settings(
            llm_enabled=True,
            llm_base_url="http://llm.example.test/v1",
            llm_api_key="must-not-leak",
            llm_model="test-model",
        )
    )

    class UnexpectedClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("HTTP client must not be created for an insecure API key endpoint")

    monkeypatch.setattr("app.llm.httpx.AsyncClient", UnexpectedClient)

    result = await service.summarize(
        {
            "venue_name": "Test Journal",
            "title": "A sufficiently descriptive test paper",
            "abstract": "x" * 200,
        }
    )

    assert result is None

