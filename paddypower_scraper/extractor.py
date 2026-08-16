"""The LLM that reads a Paddy Power page and returns structured pricing.

This is the heart of the scraper. Instead of writing brittle CSS/XPath
selectors that break every time the sportsbook changes its markup, we hand the
page's text to Claude and ask it — under a strict JSON schema — to return every
event, every market, and every selection with its odds.

Using the model this way makes the scraper resilient to layout changes and
works uniformly across sports (football coupons, race cards, outright markets)
that would otherwise each need bespoke parsing code.
"""

from __future__ import annotations

import json
import logging
from fractions import Fraction
from typing import List, Optional

from .config import ScraperConfig
from .schemas import EVENT_EXTRACTION_SCHEMA, Event, ScrapeResult, Selection

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a precise sports-betting data extractor for paddypower.com pages.

You are given the visible text of a betting page (a sport hub, a competition
coupon, or a single event). Extract EVERY event, market, and selection with its
odds that is present in the text. Rules:

- Capture all markets shown, not just the headline one (match result, over/under,
  both teams to score, handicaps, correct score, outrights, race winners, etc.).
- Preserve odds exactly as written. If odds are fractional (e.g. "5/2"), put that
  in price_fractional. If decimal (e.g. "3.50"), put it in price_decimal. "EVS" or
  "Evens" means 1/1. "SP" (starting price) has no number: leave both prices null.
- For handicap / spread / totals markets, record the line in `handicap`
  (e.g. -1.5, 2.5) and keep it out of the selection name when possible.
- Mark is_available=false for selections shown as suspended, locked, or with no
  price. Mark is_live=true for in-play events.
- Do NOT invent events, markets, prices, or start times. If a field is not shown,
  use null. Only extract what is actually present in the provided text.
- If the page contains no betting markets (e.g. a login wall, an error, or a
  block page), return an empty events array.
"""


def fractional_to_decimal(fractional: Optional[str]) -> Optional[float]:
    """Convert '5/2' -> 3.5, 'EVS' -> 2.0. Returns None if unparseable."""
    if not fractional:
        return None
    value = fractional.strip().lower()
    if value in {"evs", "evens", "even"}:
        return 2.0
    if "/" not in value:
        # Sometimes a bare decimal sneaks into the fractional field.
        try:
            return round(float(value), 4)
        except ValueError:
            return None
    try:
        frac = Fraction(value.replace(" ", ""))
        return round(float(frac) + 1.0, 4)
    except (ValueError, ZeroDivisionError):
        return None


def _normalise_prices(events: List[Event]) -> None:
    """Fill in decimal odds from fractional where the model didn't, in place."""
    for event in events:
        for market in event.markets:
            for sel in market.selections:
                if sel.price_decimal is None and sel.price_fractional:
                    sel.price_decimal = fractional_to_decimal(sel.price_fractional)


class LLMExtractor:
    """Wraps a Claude client and turns page text into :class:`Event` objects."""

    def __init__(self, config: ScraperConfig, client=None):
        self.config = config
        # Client is injectable so tests can pass a stub and callers can supply a
        # pre-configured Anthropic() (Bedrock/Vertex/etc.) instance.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def _build_user_message(self, source_url: str, content: str) -> str:
        trimmed = content[: self.config.max_content_chars]
        return (
            f"Source URL: {source_url}\n\n"
            "Extract all betting events, markets and selections from the page "
            "text below.\n\n"
            "=== PAGE TEXT START ===\n"
            f"{trimmed}\n"
            "=== PAGE TEXT END ==="
        )

    def extract(self, source_url: str, content: str) -> ScrapeResult:
        """Run the model over ``content`` and return a normalized result."""
        if not content.strip():
            return ScrapeResult(source_url=source_url, events=[])

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": self._build_user_message(source_url, content),
                }
            ],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": EVENT_EXTRACTION_SCHEMA,
                }
            },
        )

        raw = self._first_text(response)
        events = self._parse_events(raw)
        _normalise_prices(events)
        # Backfill the source URL on any event the model left urlless.
        for event in events:
            if not event.url:
                event.url = source_url
        return ScrapeResult(source_url=source_url, events=events)

    @staticmethod
    def _first_text(response) -> str:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    @staticmethod
    def _parse_events(raw: str) -> List[Event]:
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Model returned non-JSON output: %s", exc)
            return []
        events: List[Event] = []
        for item in data.get("events", []):
            try:
                events.append(Event.model_validate(item))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Skipping malformed event: %s", exc)
        return events
