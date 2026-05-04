"""Async URL fetcher tests — SPEC-ARCH-ASYNC-001 T4."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch



def _import_fetcher():
    from mnemosyne.ingest.url_fetcher import URLFetcher
    return URLFetcher


class TestURLFetcherAsync:
    """fetch_async() behaviour."""

    def test_fetch_async_returns_path(self, tmp_path):
        URLFetcher = _import_fetcher()
        fetcher = URLFetcher()

        fake_html = "<html><head><title>Test Page</title></head><body>hello</body></html>"

        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                fetcher.fetch_async("https://example.com/page", raw_dir=tmp_path)
            )

        assert isinstance(result, Path)
        assert result.exists()
        assert result.suffix == ".md"

    def test_fetch_async_writes_frontmatter(self, tmp_path):
        URLFetcher = _import_fetcher()
        fetcher = URLFetcher()

        fake_html = "<html><head><title>My Title</title></head><body>content</body></html>"

        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            path = asyncio.run(
                fetcher.fetch_async("https://example.com/page", raw_dir=tmp_path)
            )

        content = path.read_text()
        assert "---" in content
        assert "source_url:" in content

    def test_fetch_async_multiple_concurrent(self, tmp_path):
        URLFetcher = _import_fetcher()
        fetcher = URLFetcher()

        fake_html = "<html><head><title>T</title></head><body>x</body></html>"

        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        urls = [f"https://example.com/page{i}" for i in range(5)]

        async def run():
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await asyncio.gather(
                    *[fetcher.fetch_async(u, raw_dir=tmp_path) for u in urls]
                )

        results = asyncio.run(run())
        assert len(results) == 5
        assert all(isinstance(p, Path) for p in results)

    def test_fetch_async_fallback_when_httpx_missing(self, tmp_path):
        """When httpx is not importable, falls back to sync fetch() via executor."""
        URLFetcher = _import_fetcher()
        fetcher = URLFetcher()

        fake_path = tmp_path / "fallback.md"
        fake_path.write_text("---\ntitle: fallback\n---\n")

        with patch.dict("sys.modules", {"httpx": None}):
            with patch.object(fetcher, "fetch", return_value=fake_path) as mock_sync:
                result = asyncio.run(
                    fetcher.fetch_async("https://example.com", raw_dir=tmp_path)
                )

        mock_sync.assert_called_once()
        assert result == fake_path

    def test_fetch_async_error_returns_error_doc(self, tmp_path):
        URLFetcher = _import_fetcher()
        fetcher = URLFetcher()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                fetcher.fetch_async("https://bad.example.com", raw_dir=tmp_path)
            )

        assert result.exists()
        content = result.read_text()
        assert "fetch failed" in content
