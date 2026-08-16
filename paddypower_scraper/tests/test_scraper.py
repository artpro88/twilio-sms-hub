"""Offline tests for the Paddy Power scraper.

No network and no real Claude calls: the model client is stubbed so the whole
pipeline (fetch -> clean -> extract -> normalize -> store) is exercised
deterministically.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from paddypower_scraper.config import SITE_PRESETS, ScraperConfig
from paddypower_scraper.extractor import LLMExtractor, fractional_to_decimal
from paddypower_scraper.fetcher import FetchResult, clean_html
from paddypower_scraper.scraper import PaddyPowerScraper, discover_links
from paddypower_scraper.schemas import Event, Market, Selection
from paddypower_scraper.storage import save_csv, to_json

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "football_coupon.html")


def _load_fixture() -> str:
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return fh.read()


# --- site presets ------------------------------------------------------------
def test_default_site_is_paddypower():
    config = ScraperConfig()
    assert config.base_url == "https://www.paddypower.com"
    assert "paddypower" in config.site_name.lower()
    assert all("paddypower.com" in url for url in config.seed_urls)


def test_betmgm_preset_targets_betmgm():
    config = ScraperConfig(site="betmgm")
    assert config.base_url == "https://sports.betmgm.co.uk"
    assert "betmgm" in config.site_name.lower()
    assert config.seed_urls  # non-empty
    assert all("betmgm.co.uk" in url for url in config.seed_urls)


def test_explicit_base_url_and_seeds_override_preset():
    config = ScraperConfig(
        site="betmgm",
        base_url="https://example.com",
        seed_urls=["https://example.com/a"],
    )
    assert config.base_url == "https://example.com"
    assert config.seed_urls == ["https://example.com/a"]


def test_extractor_prompt_reflects_site():
    pp = LLMExtractor(ScraperConfig(site="paddypower"))
    mgm = LLMExtractor(ScraperConfig(site="betmgm"))
    assert "Paddy Power" in pp.system_prompt
    assert "BetMGM" in mgm.system_prompt
    assert "paddypower" not in mgm.system_prompt.lower()


def test_known_presets_present():
    assert {"paddypower", "betmgm"} <= set(SITE_PRESETS)


# --- odds conversion ---------------------------------------------------------
@pytest.mark.parametrize(
    "frac,expected",
    [
        ("5/2", 3.5),
        ("6/4", 2.5),
        ("EVS", 2.0),
        ("evens", 2.0),
        ("1/1", 2.0),
        ("11/10", 2.1),
        ("2.5", 2.5),  # bare decimal in the fractional slot
        ("SP", None),
        (None, None),
        ("", None),
    ],
)
def test_fractional_to_decimal(frac, expected):
    assert fractional_to_decimal(frac) == expected


# --- html cleaning -----------------------------------------------------------
def test_clean_html_strips_scripts_and_styles():
    cleaned = clean_html(_load_fixture())
    assert "window.__DATA__" not in cleaned
    assert "color:red" not in cleaned
    assert "Man Utd v Liverpool" in cleaned
    assert "6/4" in cleaned


def test_clean_html_truncates():
    assert len(clean_html("<p>" + "a" * 5000 + "</p>", max_chars=100)) == 100


# --- link discovery ----------------------------------------------------------
def test_discover_links_finds_events_skips_promos():
    links = discover_links(_load_fixture(), "https://www.paddypower.com/football")
    assert any("man-utd-v-liverpool" in l for l in links)
    assert any("premier-league" in l for l in links)
    assert all("/promotions/" not in l for l in links)


def test_discover_links_absolute_and_same_host():
    html = '<a href="https://evil.example.com/event/x">x</a><a href="/event/y">y</a>'
    links = discover_links(html, "https://www.paddypower.com/football")
    assert links == ["https://www.paddypower.com/event/y"]


# --- LLM extraction (stubbed client) -----------------------------------------
class StubClient:
    """Mimics anthropic.Anthropic().messages.create returning a text block."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                text = json.dumps(outer._payload)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=text)]
                )

        self.messages = _Messages()


def _sample_payload() -> dict:
    return {
        "events": [
            {
                "name": "Man Utd v Liverpool",
                "sport": "Football",
                "competition": "Premier League",
                "start_time": None,
                "is_live": False,
                "url": None,
                "markets": [
                    {
                        "name": "Match Result",
                        "market_type": "1x2",
                        "selections": [
                            {
                                "name": "Man Utd",
                                "price_fractional": "6/4",
                                "price_decimal": None,
                                "handicap": None,
                                "is_available": True,
                            },
                            {
                                "name": "Draw",
                                "price_fractional": "12/5",
                                "price_decimal": None,
                                "handicap": None,
                                "is_available": True,
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_extractor_parses_and_backfills_decimal_and_url():
    config = ScraperConfig()
    extractor = LLMExtractor(config, client=StubClient(_sample_payload()))
    result = extractor.extract("https://www.paddypower.com/football", "some text")

    assert len(result.events) == 1
    event = result.events[0]
    assert event.url == "https://www.paddypower.com/football"  # backfilled
    man_utd = event.markets[0].selections[0]
    assert man_utd.price_fractional == "6/4"
    assert man_utd.price_decimal == 2.5  # derived from fractional
    assert result.market_count == 1
    assert result.selection_count == 2


def test_extractor_uses_structured_output_schema():
    stub = StubClient(_sample_payload())
    LLMExtractor(ScraperConfig(), client=stub).extract("http://x", "text")
    call = stub.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["model"] == "claude-opus-5"


def test_extractor_handles_empty_content_without_calling_model():
    stub = StubClient(_sample_payload())
    result = LLMExtractor(ScraperConfig(), client=stub).extract("http://x", "   ")
    assert result.events == []
    assert stub.calls == []


def test_extractor_survives_non_json_output():
    class BadClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="not json")]
                )

    result = LLMExtractor(ScraperConfig(), client=BadClient()).extract("http://x", "t")
    assert result.events == []


# --- end-to-end with stubbed fetcher + extractor -----------------------------
class StubFetcher:
    def __init__(self, html: str):
        self._html = html
        self.fetched = []

    def fetch(self, url):
        self.fetched.append(url)
        return FetchResult(url=url, status_code=200, content=self._html, ok=True)

    def close(self):
        pass


def test_scraper_crawls_seed_then_follows_event_links():
    config = ScraperConfig(max_events_per_seed=1, max_pages=5)
    scraper = PaddyPowerScraper(
        config=config,
        fetcher=StubFetcher(_load_fixture()),
        extractor=LLMExtractor(config, client=StubClient(_sample_payload())),
    )
    events = scraper.scrape(["https://www.paddypower.com/football"])
    # Seed + one followed link both return the same event -> deduped to one.
    assert len(events) == 1
    assert events[0].name == "Man Utd v Liverpool"


def test_dedupe_keeps_event_with_more_markets():
    thin = Event(name="A v B", competition="X", markets=[Market(name="Result")])
    rich = Event(
        name="A v B",
        competition="X",
        markets=[Market(name="Result"), Market(name="BTTS")],
    )
    merged = PaddyPowerScraper._dedupe([thin, rich])
    assert len(merged) == 1
    assert len(merged[0].markets) == 2


# --- storage -----------------------------------------------------------------
def test_to_json_roundtrip():
    events = [
        Event(
            name="A v B",
            markets=[
                Market(
                    name="Result",
                    selections=[Selection(name="A", price_fractional="2/1", price_decimal=3.0)],
                )
            ],
        )
    ]
    data = json.loads(to_json(events))
    assert data[0]["markets"][0]["selections"][0]["price_decimal"] == 3.0


def test_save_csv_is_one_row_per_selection(tmp_path):
    events = [
        Event(
            name="A v B",
            sport="Football",
            markets=[
                Market(
                    name="Result",
                    selections=[
                        Selection(name="A", price_fractional="2/1"),
                        Selection(name="B", price_fractional="1/2"),
                    ],
                )
            ],
        )
    ]
    path = tmp_path / "out.csv"
    save_csv(events, str(path))
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3  # header + 2 selections
    assert "selection" in lines[0]
