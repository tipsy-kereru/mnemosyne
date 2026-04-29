"""URL fetcher for mnemosyne ingestion pipeline."""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; MnemosyneIngest/0.3; +https://github.com/mnemosyne)"
)
_MAX_TEXT_LEN = 50_000


# @MX:ANCHOR: [AUTO] URLFetcher is a public ingestion entry point.
# @MX:REASON: Called by ingester._add_url() and CLI; expected fan_in >= 3 across pipeline.
class URLFetcher:
    """Fetch URLs and persist them as Markdown under raw_dir."""

    def __init__(self, user_agent: str = _DEFAULT_USER_AGENT, timeout: int = 30) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(
        self,
        url: str,
        domain: str = "daily",
        raw_dir: Optional[Path] = None,
    ) -> Path:
        """Fetch ``url`` and save to ``raw_dir`` as a markdown file.

        Returns the path of the saved file.
        """
        target_dir = raw_dir if raw_dir is not None else (
            Path.home() / "mnemosyne" / "raw" / domain
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        slug = self._slugify(url)
        out_path = target_dir / f"{slug}.md"

        if "arxiv.org/abs/" in url:
            content = self._fetch_arxiv(url)
        elif self._looks_like_pdf(url):
            content = self._fetch_pdf(url)
        else:
            content = self._fetch_webpage(url)

        out_path.write_text(content, encoding="utf-8")
        logger.info("Fetched %s -> %s", url, out_path)
        return out_path

    @staticmethod
    def _slugify(url: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", url.lower())[:60].strip("_") or "url"

    def _open(self, url: str) -> urllib.response.addinfourl:  # type: ignore[name-defined]
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        return urllib.request.urlopen(req, timeout=self.timeout)  # noqa: S310

    def _looks_like_pdf(self, url: str) -> bool:
        if url.lower().endswith(".pdf"):
            return True
        try:
            with self._open(url) as resp:
                ctype = resp.headers.get("Content-Type", "").lower()
                return "application/pdf" in ctype
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            logger.warning("Could not HEAD-check %s: %s", url, exc)
            return False

    def _fetch_webpage(self, url: str) -> str:
        try:
            with self._open(url) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            logger.error("Failed to fetch webpage %s: %s", url, exc)
            return self._wrap_frontmatter(url, "(fetch failed)", str(exc))

        text = self._strip_html(raw)[:_MAX_TEXT_LEN]
        title = self._extract_title(raw) or url
        return self._wrap_frontmatter(url, title, text)

    def _fetch_arxiv(self, url: str) -> str:
        try:
            with self._open(url) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            logger.error("Failed to fetch arxiv %s: %s", url, exc)
            return self._wrap_frontmatter(url, "arxiv (fetch failed)", str(exc))

        title = self._extract_arxiv_title(raw) or url
        abstract = self._extract_arxiv_abstract(raw)
        authors = self._extract_arxiv_authors(raw)

        body_lines = [f"# {title}"]
        if authors:
            body_lines.append("")
            body_lines.append(f"**Authors:** {authors}")
        body_lines.append("")
        body_lines.append("## Abstract")
        body_lines.append("")
        body_lines.append(abstract or "(no abstract found)")
        body = "\n".join(body_lines)
        return self._wrap_frontmatter(url, title, body, prebuilt=True)

    def _fetch_pdf(self, url: str) -> str:
        try:
            with self._open(url) as resp:
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            logger.error("Failed to fetch pdf %s: %s", url, exc)
            return self._wrap_frontmatter(url, "pdf (fetch failed)", str(exc))

        text = self._extract_pdf_text(data)
        title = url.rsplit("/", 1)[-1]
        return self._wrap_frontmatter(url, title, text)

    @staticmethod
    def _extract_pdf_text(data: bytes) -> str:
        # @MX:NOTE: [AUTO] Optional PDF backends; fallback gracefully when missing.
        try:
            import pypdf  # type: ignore
            from io import BytesIO

            reader = pypdf.PdfReader(BytesIO(data))
            chunks: list[str] = []
            for page in reader.pages:
                try:
                    chunks.append(page.extract_text() or "")
                except (ValueError, KeyError, AttributeError) as exc:  # noqa: PERF203
                    logger.debug("pypdf page extract failed: %s", exc)
            return ("\n\n".join(chunks))[:_MAX_TEXT_LEN]
        except ImportError:
            pass

        try:
            from io import BytesIO
            from pdfminer.high_level import extract_text  # type: ignore

            return (extract_text(BytesIO(data)) or "")[:_MAX_TEXT_LEN]
        except ImportError:
            pass

        return (
            "(PDF text extraction requires pypdf: pip install pypdf)\n"
            f"(downloaded {len(data)} bytes)"
        )

    @staticmethod
    def _strip_html(raw: str) -> str:
        no_script = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", no_script)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#39;", "'", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _extract_title(raw: str) -> Optional[str]:
        match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.DOTALL | re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
        return None

    @staticmethod
    def _extract_arxiv_title(raw: str) -> Optional[str]:
        match = re.search(
            r'<h1[^>]*class="title[^"]*"[^>]*>(.*?)</h1>',
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            return URLFetcher._strip_html(match.group(1)).replace("Title:", "").strip()
        return URLFetcher._extract_title(raw)

    @staticmethod
    def _extract_arxiv_abstract(raw: str) -> str:
        match = re.search(
            r'<blockquote[^>]*class="abstract[^"]*"[^>]*>(.*?)</blockquote>',
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return ""
        return URLFetcher._strip_html(match.group(1)).replace("Abstract:", "").strip()

    @staticmethod
    def _extract_arxiv_authors(raw: str) -> str:
        match = re.search(
            r'<div[^>]*class="authors"[^>]*>(.*?)</div>',
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return ""
        return URLFetcher._strip_html(match.group(1)).replace("Authors:", "").strip()

    @staticmethod
    def _wrap_frontmatter(
        url: str, title: str, body: str, prebuilt: bool = False
    ) -> str:
        captured = datetime.now(timezone.utc).isoformat() + "Z"
        # Escape title for YAML by quoting if it contains a colon
        safe_title = title.replace('"', "'")
        frontmatter = (
            "---\n"
            f'title: "{safe_title}"\n'
            f"source_url: {url}\n"
            f"captured_at: {captured}\n"
            "---\n"
        )
        if prebuilt:
            return frontmatter + body + "\n"
        return frontmatter + f"# {title}\n\n{body}\n"
