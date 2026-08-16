"""Persist scraped events to JSON or a flat CSV of prices."""

from __future__ import annotations

import csv
import json
from typing import List

from .schemas import Event


def to_json(events: List[Event], indent: int = 2) -> str:
    return json.dumps([e.model_dump(mode="json") for e in events], indent=indent)


def save_json(events: List[Event], path: str, indent: int = 2) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_json(events, indent=indent))


def save_csv(events: List[Event], path: str) -> None:
    """One row per selection — the natural shape for odds analysis."""
    fieldnames = [
        "sport",
        "competition",
        "event",
        "start_time",
        "is_live",
        "market",
        "market_type",
        "selection",
        "handicap",
        "price_fractional",
        "price_decimal",
        "is_available",
        "url",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            for market in event.markets:
                for sel in market.selections:
                    writer.writerow(
                        {
                            "sport": event.sport,
                            "competition": event.competition,
                            "event": event.name,
                            "start_time": event.start_time,
                            "is_live": event.is_live,
                            "market": market.name,
                            "market_type": market.market_type,
                            "selection": sel.name,
                            "handicap": sel.handicap,
                            "price_fractional": sel.price_fractional,
                            "price_decimal": sel.price_decimal,
                            "is_available": sel.is_available,
                            "url": event.url,
                        }
                    )
