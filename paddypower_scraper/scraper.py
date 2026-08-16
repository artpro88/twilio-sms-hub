"""Orchestrator: crawl paddypower.com and extract all events & markets.

Flow:

1. Start from the seed URLs (sport hubs / coupons).
2. Fetch each, extract events+markets from the rendered text via the LLM.
3. Discover deeper event/competition links on those pages and follow them
   (bounded by ``max_events_per_seed`` and ``max_pages``) so per-event markets
   that only show on the event page are captured too.
4. Aggregate everything, de-duplicating events by (name, competition).
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse

from .config import ScraperConfig
from .extractor import LLMExtractor
from .fetcher import Fetcher, clean_html
from .schemas import Event, ScrapeResult

logger = logging.getLogger(__name__)

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# Path fragments that look like drill-down betting pages worth following.
_EVENT_HINTS = (
    "/event/",
    "/events/",
    "/match/",
    "/competition/",
    "/tournament/",
    "/race/",
    "/racecard",
    "/outright",
    "/betting/",
)

# Path fragments that are never betting content.
_SKIP_HINTS = (
    "/help", "/promotions", "/promo", "/login", "/register", "/account",
    "/responsible-gambling", "/terms", "/privacy", "/cookie", "/app",
    "/casino", "/games", "/bingo", "/poker", "/lotto", "/vegas",
    "javascript:", "mailto:", "tel:", "#",
)


def discover_links(html: str, base_url: str, same_host_only: bool = True) -> List[str]:
    """Pull candidate event/competition betting links out of a page."""
    host = urlparse(base_url).netloc
    found: List[str] = []
    seen: Set[str] = set()
    for match in _HREF_RE.findall(html):
        href = match.strip()
        if not href or href.startswith(_SKIP_HINTS):
            continue
        absolute = urljoin(base_url, href)
        absolute = absolute.split("#")[0].rstrip("/")
        if absolute in seen:
            continue
        if same_host_only and urlparse(absolute).netloc != host:
            continue
        if any(hint in absolute.lower() for hint in _SKIP_HINTS):
            continue
        if any(hint in absolute.lower() for hint in _EVENT_HINTS):
            seen.add(absolute)
            found.append(absolute)
    return found


class PaddyPowerScraper:
    """High-level entry point: give it seeds, get back events & markets."""

    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        fetcher: Optional[Fetcher] = None,
        extractor: Optional[LLMExtractor] = None,
    ):
        self.config = config or ScraperConfig()
        self.fetcher = fetcher or Fetcher(self.config)
        self.extractor = extractor or LLMExtractor(self.config)
        self._pages_scraped = 0

    def scrape_url(self, url: str) -> ScrapeResult:
        """Fetch a single URL and extract its events/markets (no crawling)."""
        result, _html = self._scrape_page(url)
        return result

    def scrape(self, seed_urls: Optional[Iterable[str]] = None) -> List[Event]:
        """Crawl from the seeds and return all discovered events."""
        seeds = list(seed_urls) if seed_urls is not None else self.config.seed_urls
        all_events: List[Event] = []
        visited: Set[str] = set()

        for seed in seeds:
            if self._pages_scraped >= self.config.max_pages:
                break
            if seed in visited:
                continue
            visited.add(seed)

            result, html = self._scrape_page(seed)
            all_events.extend(result.events)

            # Follow a bounded number of event links off this seed page.
            links = discover_links(html, seed)
            followed = 0
            for link in links:
                if followed >= self.config.max_events_per_seed:
                    break
                if self._pages_scraped >= self.config.max_pages:
                    break
                if link in visited:
                    continue
                visited.add(link)
                sub_result, _ = self._scrape_page(link)
                all_events.extend(sub_result.events)
                followed += 1

        return self._dedupe(all_events)

    def _scrape_page(self, url: str):
        """Fetch + extract one page, returning (ScrapeResult, raw_html)."""
        fetched = self.fetcher.fetch(url)
        if not fetched.ok:
            logger.warning("Fetch failed for %s: %s", url, fetched.error)
            return ScrapeResult(source_url=url, events=[]), ""
        self._pages_scraped += 1
        text = clean_html(fetched.content, self.config.max_content_chars)
        result = self.extractor.extract(url, text)
        logger.info(
            "%s -> %d events, %d markets, %d selections",
            url,
            len(result.events),
            result.market_count,
            result.selection_count,
        )
        return result, fetched.content

    @staticmethod
    def _dedupe(events: List[Event]) -> List[Event]:
        """Merge events seen on multiple pages, keeping the richest markets."""
        by_key = {}
        for event in events:
            key = (event.name.strip().lower(), (event.competition or "").strip().lower())
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = event
                continue
            # Keep whichever copy has more markets; that's usually the event page.
            if len(event.markets) > len(existing.markets):
                by_key[key] = event
        return list(by_key.values())

    def close(self) -> None:
        self.fetcher.close()

    def __enter__(self) -> "PaddyPowerScraper":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
