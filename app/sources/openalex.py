from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings, SourcePolicy
from app.normalize import normalize_doi
from app.sources.http import RateLimitedError, request_headers, request_with_retry


class OpenAlexCollector:
    def __init__(
        self,
        settings: Settings,
        policy: SourcePolicy,
        http_options: dict[str, int | float],
    ):
        self.settings = settings
        self.policy = policy
        self.timeout = float(http_options.get("timeout_seconds", 30))
        self.retry_wait = float(http_options.get("retry_wait_seconds", 5))
        self.disabled_for_run = False

    async def enrich(self, dois: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        enrichments: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        if not self.policy.enabled or self.disabled_for_run:
            return enrichments, errors

        normalized = list(
            dict.fromkeys(normalize_doi(doi) for doi in dois if normalize_doi(doi))
        )[: self.policy.enrich_limit]
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            trust_env=True,
            headers={"Accept": "application/json"},
        ) as client:
            for start in range(0, len(normalized), self.policy.batch_size):
                batch = normalized[start : start + self.policy.batch_size]
                filter_value = "|".join(f"https://doi.org/{doi}" for doi in batch)
                params: dict[str, Any] = {
                    "filter": f"doi:{filter_value}",
                    "per-page": len(batch),
                    "mailto": self.settings.openalex_mailto,
                    "select": (
                        "doi,abstract_inverted_index,cited_by_count,open_access,"
                        "best_oa_location,primary_location"
                    ),
                }
                if self.settings.openalex_api_key:
                    params["api_key"] = self.settings.openalex_api_key
                try:
                    response = await request_with_retry(
                        client,
                        "https://api.openalex.org/works",
                        params=params,
                        headers=request_headers(self.settings.user_agent),
                        max_retries=1,
                        retry_wait_seconds=self.retry_wait,
                    )
                    for item in response.json().get("results", []):
                        doi = normalize_doi(item.get("doi", ""))
                        if doi:
                            enrichments[doi] = {
                                "abstract": reconstruct_abstract(
                                    item.get("abstract_inverted_index")
                                ),
                                "cited_by_count": int(item.get("cited_by_count", 0) or 0),
                                "is_oa": bool(
                                    item.get("open_access", {}).get("is_oa", False)
                                ),
                                "pdf_url": _pdf_url(item),
                            }
                except RateLimitedError:
                    errors.append(
                        "OpenAlex 已限流，本次运行将跳过后续增强。"
                        "可配置免费的 OPENALEX_API_KEY 提高额度。"
                    )
                    self.disabled_for_run = True
                    break
                except Exception as exc:
                    errors.append(f"OpenAlex 批次 {start // self.policy.batch_size + 1}: {exc}")
                await asyncio.sleep(self.policy.request_delay_seconds)
        return enrichments, errors


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        positions.extend((int(index), word) for index in indexes)
    positions.sort()
    return " ".join(word for _, word in positions)


def _pdf_url(item: dict[str, Any]) -> str:
    best = item.get("best_oa_location") or {}
    return str(best.get("pdf_url") or item.get("open_access", {}).get("oa_url") or "")

