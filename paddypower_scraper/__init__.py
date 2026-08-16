"""LLM-powered pricing scraper for paddypower.com.

Public API::

    from paddypower_scraper import PaddyPowerScraper, ScraperConfig

    with PaddyPowerScraper(ScraperConfig(fetch_backend="playwright")) as scraper:
        events = scraper.scrape()
"""

from .config import SITE_PRESETS, ScraperConfig
from .extractor import LLMExtractor, fractional_to_decimal
from .fetcher import Fetcher, clean_html
from .scraper import PaddyPowerScraper, discover_links
from .schemas import Event, Market, ScrapeResult, Selection

__all__ = [
    "ScraperConfig",
    "SITE_PRESETS",
    "PaddyPowerScraper",
    "LLMExtractor",
    "Fetcher",
    "clean_html",
    "discover_links",
    "fractional_to_decimal",
    "Event",
    "Market",
    "Selection",
    "ScrapeResult",
]

__version__ = "0.1.0"
