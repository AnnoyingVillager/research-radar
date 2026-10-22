from __future__ import annotations

import asyncio
from typing import Any

import httpx


class RateLimitedError(RuntimeError):
    pass


async def request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = 2,
    retry_wait_seconds: float = 5,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response, retry_wait_seconds)
                if attempt >= max_retries or retry_after > 60:
                    raise RateLimitedError(f"rate limited by {response.url.host}")
                await asyncio.sleep(retry_after)
                continue
            if response.status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(retry_wait_seconds * (attempt + 1))
                continue
            if response.status_code == 304:
                return response
            if response.status_code >= 400:
                response.raise_for_status()
            return response
        except RateLimitedError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            await asyncio.sleep(retry_wait_seconds * (attempt + 1))
    raise RuntimeError(f"request failed for {url}: {last_error}")


def request_headers(
    user_agent: str,
    *,
    conditional: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if conditional:
        headers.update({key: value for key, value in conditional.items() if value})
    return headers


def _retry_after_seconds(response: httpx.Response, fallback: float) -> float:
    value = response.headers.get("Retry-After", "")
    try:
        return max(1.0, float(value))
    except ValueError:
        return max(1.0, fallback)

