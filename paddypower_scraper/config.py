"""Configuration for the sportsbook pricing scraper.

Although the package is named after Paddy Power (its first target), the scraper
is site-agnostic: pick a target with ``PP_SITE`` (or ``ScraperConfig(site=...)``),
or point it anywhere with ``PP_BASE_URL`` / ``PP_SEED_URLS``. Everything likely
to change — the site, model, rate limits, seed URLs — is centralised here and
overridable from the environment so you never edit code to retarget it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# A realistic desktop browser UA. Sportsbooks sit behind bot protection; a
# browser-shaped request gets much further than the python-requests default.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


# --- Site presets ------------------------------------------------------------
# Each preset supplies a human label (used in the extractor prompt), a base URL,
# and seed pages to crawl. Seed paths are best-effort starting points — they
# change as sites reorganise, so override PP_SEED_URLS for a precise run.
SITE_PRESETS: Dict[str, Dict[str, object]] = {
    "paddypower": {
        "site_name": "Paddy Power (paddypower.com)",
        "base_url": "https://www.paddypower.com",
        "seed_urls": [
            "https://www.paddypower.com/football",
            "https://www.paddypower.com/horse-racing",
            "https://www.paddypower.com/tennis",
            "https://www.paddypower.com/basketball",
            "https://www.paddypower.com/golf",
            "https://www.paddypower.com/cricket",
            "https://www.paddypower.com/rugby-union",
            "https://www.paddypower.com/boxing",
        ],
    },
    "betmgm": {
        "site_name": "BetMGM UK (sports.betmgm.co.uk)",
        "base_url": "https://sports.betmgm.co.uk",
        # BetMGM UK runs on the Entain platform; sport categories carry a numeric
        # id suffix (e.g. football-4). Verify/adjust these against the live nav.
        "seed_urls": [
            "https://sports.betmgm.co.uk/en/sports/football-4",
            "https://sports.betmgm.co.uk/en/sports/horse-racing-21",
            "https://sports.betmgm.co.uk/en/sports/tennis-5",
            "https://sports.betmgm.co.uk/en/sports/basketball-7",
            "https://sports.betmgm.co.uk/en/sports/golf-13",
            "https://sports.betmgm.co.uk/en/sports/cricket-3",
            "https://sports.betmgm.co.uk/en/sports/rugby-union-19",
            "https://sports.betmgm.co.uk/en/sports/boxing-6",
        ],
    },
}

DEFAULT_SITE = os.getenv("PP_SITE", "paddypower")


def _env_list(name: str) -> Optional[List[str]]:
    raw = os.getenv(name)
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class ScraperConfig:
    """Runtime configuration for a scrape run.

    Precedence for site fields: an explicit constructor value or the matching
    ``PP_*`` env var wins; otherwise the ``site`` preset supplies the default.
    """

    # --- Target site -------------------------------------------------------
    site: str = DEFAULT_SITE
    site_name: Optional[str] = None
    base_url: Optional[str] = None
    seed_urls: Optional[List[str]] = None

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

    def __post_init__(self) -> None:
        preset = SITE_PRESETS.get(self.site, {})
        if not preset and (self.base_url is None or self.seed_urls is None):
            # Unknown site with no explicit base/seeds — fall back to the default
            # preset so we always have something coherent to target.
            preset = SITE_PRESETS[DEFAULT_SITE] if DEFAULT_SITE in SITE_PRESETS else {}

        # Precedence: explicit value > env var > preset > generic fallback.
        if self.site_name is None:
            self.site_name = preset.get("site_name", self.site)
        if self.base_url is None:
            self.base_url = os.getenv("PP_BASE_URL") or preset.get("base_url")
        if self.seed_urls is None:
            self.seed_urls = _env_list("PP_SEED_URLS") or list(
                preset.get("seed_urls", [])
            )

    def request_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
