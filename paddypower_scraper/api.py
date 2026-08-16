"""Optional FastAPI wrapper around the scraper.

Run standalone::

    uvicorn paddypower_scraper.api:app --reload

Then::

    GET  /health
    POST /scrape        {"urls": ["https://www.paddypower.com/football"], "crawl": true}
    POST /scrape/url    {"url": "https://www.paddypower.com/football"}

Requires ANTHROPIC_API_KEY in the environment for the extraction step.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from .config import ScraperConfig
from .scraper import PaddyPowerScraper
from .schemas import Event

app = FastAPI(title="Paddy Power Pricing Scraper", version="0.1.0")


class ScrapeRequest(BaseModel):
    urls: Optional[List[str]] = None
    crawl: bool = True
    backend: Optional[str] = None
    model: Optional[str] = None
    max_events_per_seed: Optional[int] = None


class ScrapeResponse(BaseModel):
    event_count: int
    market_count: int
    selection_count: int
    events: List[Event]


def _config_from(req: ScrapeRequest) -> ScraperConfig:
    config = ScraperConfig()
    if req.backend:
        config.fetch_backend = req.backend
    if req.model:
        config.model = req.model
    if req.max_events_per_seed is not None:
        config.max_events_per_seed = req.max_events_per_seed
    return config


def _respond(events: List[Event]) -> ScrapeResponse:
    return ScrapeResponse(
        event_count=len(events),
        market_count=sum(len(e.markets) for e in events),
        selection_count=sum(len(m.selections) for e in events for m in e.markets),
        events=events,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse)
def scrape(req: ScrapeRequest) -> ScrapeResponse:
    config = _config_from(req)
    with PaddyPowerScraper(config) as scraper:
        if req.crawl:
            events = scraper.scrape(req.urls)
        else:
            events: List[Event] = []
            for url in req.urls or config.seed_urls:
                events.extend(scraper.scrape_url(url).events)
            events = scraper._dedupe(events)
    return _respond(events)


@app.post("/scrape/url", response_model=ScrapeResponse)
def scrape_url(url: str) -> ScrapeResponse:
    with PaddyPowerScraper() as scraper:
        events = scraper.scrape_url(url).events
    return _respond(events)
