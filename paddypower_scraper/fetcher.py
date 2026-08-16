"""Fetching layer: pull raw HTML/JSON from paddypower.com politely and robustly.

Two backends are supported:

* ``requests`` — fast, cheap, but easily blocked by the bot protection in
  front of most sportsbooks.
* ``playwright`` — drives a real headless Chromium (preinstalled in this
  environment), executing the page's JavaScript so the odds are actually in
  the DOM before we read it. Imported lazily so ``requests`` users don't need
  it installed.

The fetcher also:

* honours ``robots.txt`` (can be disabled for authorised testing),
* rate-limits per host with a configurable minimum interval, and
* retries transient failures with exponential backoff.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .config import ScraperConfig

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: str
    ok: bool
    error: Optional[str] = None


class Fetcher:
    """Rate-limited, robots-aware fetcher with pluggable backend."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._last_request_at: Dict[str, float] = {}
        self._robots: Dict[str, Optional[RobotFileParser]] = {}
        self._session = requests.Session()
        self._session.headers.update(config.request_headers())
        self._playwright_ctx = None  # lazily created (browser, context)

    # -- politeness ---------------------------------------------------------
    def _host(self, url: str) -> str:
        return urlparse(url).netloc

    def _throttle(self, url: str) -> None:
        host = self._host(url)
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            wait = self.config.min_request_interval - elapsed
            if wait > 0:
                # Small jitter so we don't hammer on an exact cadence.
                time.sleep(wait + random.uniform(0, 0.4))
        self._last_request_at[host] = time.monotonic()

    def _robots_for(self, url: str) -> Optional[RobotFileParser]:
        host = self._host(url)
        if host in self._robots:
            return self._robots[host]
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        parser = RobotFileParser()
        try:
            resp = self._session.get(robots_url, timeout=self.config.request_timeout)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                parser = None  # no usable robots.txt -> allow
        except requests.RequestException as exc:  # pragma: no cover - network
            logger.warning("Could not fetch robots.txt for %s: %s", host, exc)
            parser = None
        self._robots[host] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.config.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.config.user_agent, url)

    # -- backends -----------------------------------------------------------
    def _fetch_requests(self, url: str) -> FetchResult:
        resp = self._session.get(url, timeout=self.config.request_timeout)
        return FetchResult(
            url=url,
            status_code=resp.status_code,
            content=resp.text,
            ok=resp.ok,
            error=None if resp.ok else f"HTTP {resp.status_code}",
        )

    def _ensure_playwright(self):
        if self._playwright_ctx is not None:
            return self._playwright_ctx
        # Imported lazily; only needed for the playwright backend.
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=self.config.user_agent)
        self._playwright_ctx = (pw, browser, context)
        return self._playwright_ctx

    def _fetch_playwright(self, url: str) -> FetchResult:
        _, _, context = self._ensure_playwright()
        page = context.new_page()
        try:
            resp = page.goto(
                url,
                timeout=int(self.config.request_timeout * 1000),
                wait_until="networkidle",
            )
            status = resp.status if resp else 0
            content = page.content()
            return FetchResult(
                url=url,
                status_code=status,
                content=content,
                ok=bool(resp and resp.ok),
                error=None if (resp and resp.ok) else f"HTTP {status}",
            )
        finally:
            page.close()

    # -- public API ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        """Fetch a URL, respecting robots + rate limits, with retries."""
        if not self.allowed(url):
            return FetchResult(
                url=url,
                status_code=0,
                content="",
                ok=False,
                error="Blocked by robots.txt",
            )

        backend = (
            self._fetch_playwright
            if self.config.fetch_backend == "playwright"
            else self._fetch_requests
        )

        last_error = "unknown error"
        for attempt in range(1, self.config.max_retries + 1):
            self._throttle(url)
            try:
                result = backend(url)
                if result.ok:
                    return result
                last_error = result.error or f"HTTP {result.status_code}"
                # 4xx (other than 429) won't fix themselves on retry.
                if 400 <= result.status_code < 500 and result.status_code != 429:
                    return result
            except Exception as exc:  # pragma: no cover - network variability
                last_error = str(exc)
                logger.warning("Fetch attempt %d for %s failed: %s", attempt, url, exc)

            if attempt < self.config.max_retries:
                backoff = 2 ** attempt + random.uniform(0, 1)
                logger.info("Retrying %s in %.1fs", url, backoff)
                time.sleep(backoff)

        return FetchResult(
            url=url, status_code=0, content="", ok=False, error=last_error
        )

    def close(self) -> None:
        self._session.close()
        if self._playwright_ctx is not None:  # pragma: no cover - network
            pw, browser, _ = self._playwright_ctx
            browser.close()
            pw.stop()
            self._playwright_ctx = None

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --- HTML cleaning -----------------------------------------------------------
# The LLM extractor works best (and cheapest) on the visible, price-bearing
# text of a page rather than raw markup. We strip scripts/styles and collapse
# whitespace, keeping enough structure (tag boundaries as spaces) for the model
# to associate selections with prices.

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


def clean_html(html: str, max_chars: Optional[int] = None) -> str:
    """Reduce a page to readable text suitable for LLM extraction."""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub("\n", text)
    # Collapse HTML entities we commonly see on odds pages.
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _MULTINEWLINE_RE.sub("\n\n", text).strip()
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text
