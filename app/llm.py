from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

OPENCODE_GO_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
LEGACY_OPENCODE_GO_PATHS = {"/zen/go/v1"}

SYSTEM_PROMPT = """你是气动声学、计算声学和流体力学方向的研究助理。
只根据用户提供的论文标题、期刊和摘要进行总结，不得补充摘要中没有的事实。
输出严格 JSON，不要输出 Markdown。字段如下：
{
  "title_zh": "准确的中文标题",
  "problem": "研究要解决的问题，1-2句",
  "method": "使用的方法，1-2句",
  "key_results": ["关键结果1", "关键结果2"],
  "limitations": "摘要明确体现或可以合理判断的局限；无法判断时写‘摘要未说明’",
  "relevance": "与气动声学/流体/计算方法的联系",
  "read_reason": "建议阅读的一句话理由",
  "novelty_score": 0.0
}
novelty_score 取 0 到 1。不要因为论文暂时没有引用就给出低分。"""


def normalize_llm_base_url(value: str) -> str:
    """Normalize known OpenCode Go URLs without changing other providers."""
    base_url = value.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme == "https"
        and parsed.hostname == "opencode.ai"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path.rstrip("/") in LEGACY_OPENCODE_GO_PATHS
    ):
        return OPENCODE_GO_BASE_URL
    return base_url


def _chat_completions_endpoint(base_url: str) -> str:
    if urlsplit(base_url).path.rstrip("/").endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _is_opencode_go_endpoint(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    return (
        parsed.hostname == "opencode.ai"
        and (
            parsed.path.startswith("/inference/go/")
            or parsed.path.startswith("/zen/go/")
        )
    )


def _safe_error_text(value: Any, secret: str) -> str:
    text = str(value).strip() if value is not None else ""
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return " ".join(text.split())[:500]


def _response_error(response: httpx.Response, secret: str) -> str:
    details: list[str] = []
    try:
        payload = response.json()
    except ValueError:
        payload = None

    error: Any = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        for key in ("type", "code", "param", "message"):
            value = _safe_error_text(error.get(key), secret)
            if value:
                details.append(f"{key}={value}")
    elif error is not None:
        value = _safe_error_text(error, secret)
        if value:
            details.append(f"error={value}")
    elif isinstance(payload, dict):
        value = _safe_error_text(
            payload.get("detail") or payload.get("message"),
            secret,
        )
        if value:
            details.append(f"message={value}")

    request_id = response.headers.get("x-request-id") or response.headers.get(
        "request-id"
    )
    if request_id:
        details.append(f"request_id={_safe_error_text(request_id, secret)}")
    return ", ".join(details) if details else "no structured error details"


def _log_llm_failure(
    response: httpx.Response,
    *,
    base_url: str,
    model: str,
    attempt: int,
    secret: str,
) -> None:
    logger.warning(
        "LLM request failed: path=%s model=%s attempt=%d status=%d %s",
        urlsplit(base_url).path or "/",
        model,
        attempt,
        response.status_code,
        _response_error(response, secret),
    )


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.llm_enabled
            and self.settings.llm_base_url
            and self.settings.llm_model
        )

    async def summarize(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        abstract = (paper.get("abstract") or "").strip()
        if not self.configured or len(abstract) < 120:
            return None
        base_url = normalize_llm_base_url(self.settings.llm_base_url)
        parsed_endpoint = urlsplit(base_url)
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or not parsed_endpoint.hostname
            or parsed_endpoint.username
            or parsed_endpoint.password
        ):
            return None
        if self.settings.llm_api_key and parsed_endpoint.scheme != "https":
            return None

        user_prompt = (
            f"期刊：{paper.get('venue_name', '')}\n"
            f"英文标题：{paper.get('title', '')}\n"
            f"摘要：{abstract[:9000]}"
        )
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.settings.user_agent or "ResearchRadar/0.1",
        }
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        if _is_opencode_go_endpoint(base_url):
            headers["x-opencode-session"] = f"research-radar-{uuid.uuid4().hex}"
        endpoint = _chat_completions_endpoint(base_url)

        async with httpx.AsyncClient(timeout=120, trust_env=True) as client:
            try:
                attempt = 1
                response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code == 400:
                    _log_llm_failure(
                        response,
                        base_url=base_url,
                        model=self.settings.llm_model,
                        attempt=1,
                        secret=self.settings.llm_api_key,
                    )
                    payload.pop("response_format", None)
                    payload.pop("temperature", None)
                    attempt = 2
                    response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code >= 400:
                    _log_llm_failure(
                        response,
                        base_url=base_url,
                        model=self.settings.llm_model,
                        attempt=attempt,
                        secret=self.settings.llm_api_key,
                    )
                    return None
            except httpx.HTTPError as exc:
                logger.warning(
                    "LLM request failed before receiving a response: path=%s model=%s error=%s",
                    urlsplit(base_url).path or "/",
                    self.settings.llm_model,
                    type(exc).__name__,
                )
                return None
            except Exception as exc:
                logger.error(
                    "LLM request failed unexpectedly: path=%s model=%s error=%s",
                    urlsplit(base_url).path or "/",
                    self.settings.llm_model,
                    type(exc).__name__,
                )
                return None

            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError):
                logger.warning(
                    "LLM response was not a Chat Completions JSON object: "
                    "path=%s model=%s content_type=%s",
                    urlsplit(base_url).path or "/",
                    self.settings.llm_model,
                    response.headers.get("content-type", "unknown"),
                )
                return None
            if not isinstance(content, str):
                logger.warning(
                    "LLM response content was not text: path=%s model=%s",
                    urlsplit(base_url).path or "/",
                    self.settings.llm_model,
                )
                return None
            summary = parse_json_object(content)
            if summary is None:
                logger.warning(
                    "LLM response did not contain valid structured JSON: path=%s model=%s",
                    urlsplit(base_url).path or "/",
                    self.settings.llm_model,
                )
            return summary


def parse_json_object(content: str) -> dict[str, Any] | None:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    results = data.get("key_results", [])
    if isinstance(results, list):
        data["key_results"] = "；".join(str(item).strip() for item in results if item)
    else:
        data["key_results"] = str(results)
    try:
        data["novelty_score"] = max(0.0, min(1.0, float(data.get("novelty_score", 0.5))))
    except (TypeError, ValueError):
        data["novelty_score"] = 0.5
    return data

