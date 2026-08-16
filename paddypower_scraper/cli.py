"""Command-line interface for the Paddy Power pricing scraper.

Examples
--------
Scrape the default sport hubs and print JSON::

    python -m paddypower_scraper.cli

Scrape specific URLs with the JS-rendering backend, save to CSV::

    python -m paddypower_scraper.cli \\
        --url https://www.paddypower.com/football \\
        --backend playwright --csv prices.csv

Extract from a saved HTML file (no network, useful for testing/replay)::

    python -m paddypower_scraper.cli --html-file page.html
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from .config import ScraperConfig
from .extractor import LLMExtractor
from .fetcher import clean_html
from .scraper import PaddyPowerScraper
from .storage import save_csv, save_json, to_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paddypower_scraper",
        description="LLM-powered odds scraper for paddypower.com",
    )
    p.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="URL to scrape (repeatable). Defaults to the configured sport hubs.",
    )
    p.add_argument(
        "--html-file",
        help="Extract from a local HTML file instead of fetching (offline mode).",
    )
    p.add_argument(
        "--backend",
        choices=["requests", "playwright"],
        help="Fetch backend. 'playwright' renders JavaScript.",
    )
    p.add_argument("--model", help="Claude model id (default: claude-opus-5).")
    p.add_argument(
        "--max-events-per-seed",
        type=int,
        help="How many event links to follow off each seed page.",
    )
    p.add_argument("--no-crawl", action="store_true", help="Only scrape the given URLs.")
    p.add_argument("--json", dest="json_path", help="Write results to this JSON file.")
    p.add_argument("--csv", dest="csv_path", help="Write results to this CSV file.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    return p


def _apply_overrides(args, config: ScraperConfig) -> None:
    if args.backend:
        config.fetch_backend = args.backend
    if args.model:
        config.model = args.model
    if args.max_events_per_seed is not None:
        config.max_events_per_seed = args.max_events_per_seed


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = ScraperConfig()
    _apply_overrides(args, config)

    # Offline mode: extract straight from a saved HTML file.
    if args.html_file:
        with open(args.html_file, "r", encoding="utf-8") as fh:
            html = fh.read()
        text = clean_html(html, config.max_content_chars)
        result = LLMExtractor(config).extract(f"file://{args.html_file}", text)
        events = result.events
    else:
        with PaddyPowerScraper(config) as scraper:
            if args.no_crawl and args.urls:
                events = []
                for url in args.urls:
                    events.extend(scraper.scrape_url(url).events)
                events = scraper._dedupe(events)
            else:
                events = scraper.scrape(args.urls)

    total_markets = sum(len(e.markets) for e in events)
    total_selections = sum(len(m.selections) for e in events for m in e.markets)
    print(
        f"Scraped {len(events)} events, {total_markets} markets, "
        f"{total_selections} selections.",
        file=sys.stderr,
    )

    if args.json_path:
        save_json(events, args.json_path)
        print(f"Wrote JSON -> {args.json_path}", file=sys.stderr)
    if args.csv_path:
        save_csv(events, args.csv_path)
        print(f"Wrote CSV -> {args.csv_path}", file=sys.stderr)
    if not args.json_path and not args.csv_path:
        print(to_json(events))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
