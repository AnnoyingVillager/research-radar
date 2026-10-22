import json
import logging

import httpx
import pytest

from app.config import Settings
from app.llm import LLMService, normalize_llm_base_url, parse_json_object


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


def test_normalize_legacy_opencode_go_url() -> None:
    assert normalize_llm_base_url("https://opencode.ai/zen/go/v1/") == (
        "https://opencode.ai/inference/go/openai/v1"
    )
    assert normalize_llm_base_url("https://llm.example.test/v1/") == (
        "https://llm.example.test/v1"
    )


@pytest.mark.asyncio
async def test_llm_retries_without_optional_parameters_and_redacts_errors(
    monkeypatch,
    caplog,
) -> None:
    requests: list[tuple[str, dict[str, str], dict]] = []
    api_key = "must-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append((str(request.url), dict(request.headers), payload))
        if len(requests) == 1:
            return httpx.Response(
                400,
                headers={"x-request-id": "req_safe_123"},
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "code": "unsupported_parameter",
                        "param": "response_format",
                        "message": f"response_format is not supported for {api_key}",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title_zh":"测试论文",'
                                '"key_results":["结果一","结果二"],'
                                '"novelty_score":0.7}'
                            )
                        }
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr("app.llm.httpx.AsyncClient", mock_client)
    caplog.set_level(logging.WARNING, logger="app.llm")
    service = LLMService(
        Settings(
            llm_enabled=True,
            llm_base_url="https://opencode.ai/zen/go/v1",
            llm_api_key=api_key,
            llm_model="test-model",
            user_agent="ResearchRadar-Test/1.0",
        )
    )

    result = await service.summarize(
        {
            "venue_name": "Test Journal",
            "title": "A sufficiently descriptive test paper",
            "abstract": "x" * 200,
        }
    )

    assert result is not None
    assert result["title_zh"] == "测试论文"
    assert len(requests) == 2
    assert requests[0][0] == (
        "https://opencode.ai/inference/go/openai/v1/chat/completions"
    )
    assert requests[0][1]["user-agent"] == "ResearchRadar-Test/1.0"
    assert requests[0][1]["x-opencode-session"].startswith("research-radar-")
    assert "temperature" in requests[0][2]
    assert "response_format" in requests[0][2]
    assert "temperature" not in requests[1][2]
    assert "response_format" not in requests[1][2]
    assert "status=400" in caplog.text
    assert "type=invalid_request_error" in caplog.text
    assert "code=unsupported_parameter" in caplog.text
    assert "request_id=req_safe_123" in caplog.text
    assert api_key not in caplog.text
    assert "[REDACTED]" in caplog.text


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

