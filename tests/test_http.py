import httpx
import pytest

from app.sources.http import request_with_retry


@pytest.mark.asyncio
async def test_request_with_retry_accepts_not_modified() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(304, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await request_with_retry(client, "https://example.test/page")

    assert response.status_code == 304
