from __future__ import annotations

import httpx
import pytest

from app.service import InputReferenceError, InputResolver
from conftest import PNG


@pytest.mark.asyncio
async def test_http_reference_accepts_octet_stream_and_hashes_resolved_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://images.example/ref"
        return httpx.Response(
            200,
            content=PNG,
            headers={"content-type": "application/octet-stream"},
        )

    resolver = InputResolver(1024, 1, httpx.MockTransport(handler))
    try:
        result = await resolver.resolve("https://images.example/ref")
    finally:
        await resolver.close()
    assert result.content == PNG
    assert result.mime_type == "image/png"
    assert len(result.sha256) == 64


@pytest.mark.asyncio
async def test_declared_image_must_match_magic_bytes():
    resolver = InputResolver(1024, 1)
    try:
        with pytest.raises(InputReferenceError, match="did not contain"):
            await resolver.resolve("data:image/png;base64,bm90LWFuLWltYWdl")
    finally:
        await resolver.close()
