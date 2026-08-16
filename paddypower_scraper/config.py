"""Configuration for the Paddy Power pricing scraper.

Everything that is likely to change — the model, rate limits, seed URLs, the
odds-server base — is centralised here and overridable from the environment so
you never have to edit code to point the scraper somewhere new.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List


# A realistic desktop browser UA. Paddy Power (like most sportsbooks) sits
# behind bot protection; a browser-shaped request gets much further than the
# python-requests default.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class ScraperConfig:
    """Runtime configuration for a scrape run."""

    # --- Target site -------------------------------------------------------
    base_url: str = os.getenv("PP_BASE_URL", "https://www.paddypower.com")

    # Seed URLs the crawler starts from. Each is a sport / coupon page whose
    # rendered HTML lists events and markets. Override via PP_SEED_URLS as a
    # comma-separated list to scrape only the sports you care about.
    seed_urls: List[str] = field(
        default_factory=lambda: _env_list(
            "PP_SEED_URLS",
            [
                "https://www.paddypower.com/football",
                "https://www.paddypower.com/horse-racing",
                "https://www.paddypower.com/tennis",
                "https://www.paddypower.com/basketball",
                "https://www.paddypower.com/golf",
                "https://www.paddypower.com/cricket",
                "https://www.paddypower.com/rugby-union",
                "https://www.paddypower.com/boxing",
            ],
        )
    )

    # --- Fetching ----------------------------------------------------------
    # "requests" is fast but easily blocked; "playwright" renders JS and gets
    # through far more bot protection (Chromium is preinstalled in this env).
    fetch_backend: str = os.getenv("PP_FETCH_BACKEND", "requests")
    user_agent: str = os.getenv("PP_USER_AGENT", DEFAULT_USER_AGENT)
    request_timeout: float = float(os.getenv("PP_REQUEST_TIMEOUT", "30"))
    # Be a polite scraper: minimum seconds between requests to the same host.
    min_request_interval: float = float(os.getenv("PP_MIN_REQUEST_INTERVAL", "2.0"))
    max_retries: int = int(os.getenv("PP_MAX_RETRIES", "3"))
    respect_robots: bool = os.getenv("PP_RESPECT_ROBOTS", "true").lower() == "true"

    # --- Crawl shape -------------------------------------------------------
    # How many event pages to follow out of the seed/coupon pages. 0 == only
    # scrape the seed pages themselves.
    max_events_per_seed: int = int(os.getenv("PP_MAX_EVENTS_PER_SEED", "25"))
    max_pages: int = int(os.getenv("PP_MAX_PAGES", "200"))

    # --- LLM extraction ----------------------------------------------------
    # Default to the most capable model. For a high-volume run you may prefer
    # a cheaper model (e.g. claude-haiku-4-5) — set PP_MODEL to override.
    model: str = os.getenv("PP_MODEL", "claude-opus-5")
    max_tokens: int = int(os.getenv("PP_MAX_TOKENS", "16000"))
    # HTML is trimmed to this many characters before being sent to the model,
    # so a huge page can't blow the context window or the bill.
    max_content_chars: int = int(os.getenv("PP_MAX_CONTENT_CHARS", "120000"))

    def request_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
