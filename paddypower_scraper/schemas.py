"""Pydantic schemas describing the normalized shape of scraped Paddy Power pricing.

The whole point of this scraper is to turn messy, ever-changing sportsbook
markup into these stable objects. Everything downstream (storage, the CLI,
the FastAPI endpoint) speaks in terms of :class:`Event` / :class:`Market` /
:class:`Selection`, so the LLM extractor is asked to emit exactly this shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Selection(BaseModel):
    """A single runner / outcome you can bet on within a market."""

    name: str = Field(..., description="Selection name, e.g. 'Manchester United' or 'Over 2.5'")
    price_fractional: Optional[str] = Field(
        None, description="Odds in fractional form as shown on site, e.g. '5/2'"
    )
    price_decimal: Optional[float] = Field(
        None, description="Odds in decimal form, e.g. 3.5. Derived from fractional when missing."
    )
    handicap: Optional[float] = Field(
        None, description="Handicap / line value for spread or totals markets, e.g. -1.5"
    )
    is_available: bool = Field(
        True, description="False when the selection is suspended / price withdrawn"
    )


class Market(BaseModel):
    """A group of mutually exclusive selections, e.g. 'Match Result'."""

    name: str = Field(..., description="Market name, e.g. 'Match Result', 'Both Teams To Score'")
    market_type: Optional[str] = Field(
        None, description="Coarse machine-friendly type, e.g. '1x2', 'over_under', 'handicap'"
    )
    selections: List[Selection] = Field(default_factory=list)


class Event(BaseModel):
    """A single fixture / match / race with all of its markets."""

    name: str = Field(..., description="Event name, e.g. 'Man Utd v Liverpool'")
    sport: Optional[str] = Field(None, description="Sport, e.g. 'Football'")
    competition: Optional[str] = Field(
        None, description="Competition / league, e.g. 'Premier League'"
    )
    start_time: Optional[str] = Field(
        None, description="ISO-8601 scheduled start time if shown, else null"
    )
    is_live: bool = Field(False, description="True for in-play events")
    url: Optional[str] = Field(None, description="Canonical event URL on paddypower.com")
    markets: List[Market] = Field(default_factory=list)


class ScrapeResult(BaseModel):
    """Top-level container returned for a single scraped page/source."""

    source_url: str
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    events: List[Event] = Field(default_factory=list)

    @property
    def market_count(self) -> int:
        return sum(len(e.markets) for e in self.events)

    @property
    def selection_count(self) -> int:
        return sum(len(m.selections) for e in self.events for m in e.markets)


# --- JSON Schema handed to Claude's structured-output constraint -------------
# Kept deliberately close to the pydantic models above but trimmed to the
# subset of JSON Schema that the structured-outputs feature supports
# (no min/max, every object closed with additionalProperties: false).

EVENT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sport": {"type": ["string", "null"]},
                    "competition": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "is_live": {"type": "boolean"},
                    "url": {"type": ["string", "null"]},
                    "markets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "market_type": {"type": ["string", "null"]},
                                "selections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "price_fractional": {"type": ["string", "null"]},
                                            "price_decimal": {"type": ["number", "null"]},
                                            "handicap": {"type": ["number", "null"]},
                                            "is_available": {"type": "boolean"},
                                        },
                                        "required": [
                                            "name",
                                            "price_fractional",
                                            "price_decimal",
                                            "handicap",
                                            "is_available",
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["name", "market_type", "selections"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "name",
                    "sport",
                    "competition",
                    "start_time",
                    "is_live",
                    "url",
                    "markets",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}
