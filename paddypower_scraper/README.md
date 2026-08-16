# 🎯 Sportsbook Pricing Scraper (LLM-powered)

An LLM-driven scraper that extracts **all events, markets and selections with
their prices** from a sportsbook. It ships with presets for **Paddy Power** and
**BetMGM UK**, and can be pointed at any site via config.

Instead of hand-written CSS/XPath selectors that break every time the
sportsbook tweaks its markup, this tool hands each page's text to **Claude**
and asks it — under a strict JSON schema — to return structured odds. That
makes it resilient to layout changes and lets one code path handle football
coupons, race cards, outrights and in-play alike.

```
┌──────────┐   fetch      ┌──────────┐   clean text   ┌─────────────┐   JSON
│  Fetcher │─────────────▶│   HTML   │───────────────▶│  LLMExtractor│──────────▶ Events
│ requests │  (robots +   │ cleaning │  (scripts out) │   (Claude)   │ (schema)   Markets
│ or PW    │   throttle)  └──────────┘                └─────────────┘            Selections
└──────────┘                                                                      + prices
```

## Why "an LLM that scrapes"

The extractor (`extractor.py`) is the LLM. It receives the visible text of a
page and returns every event → market → selection → price, normalized into the
`schemas.py` pydantic models via Claude's **structured outputs** (guaranteed
JSON matching a schema). Fractional odds are converted to decimal
automatically. No per-sport parsing code to maintain.

## Install

```bash
pip install -r paddypower_scraper/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # or `ant auth login`
```

Chromium for the JS-rendering backend is preinstalled in Claude Code on the
web; elsewhere run `playwright install chromium` once.

## Targeting a site

Pick a built-in preset with `--site` (or `PP_SITE`), or point it anywhere with
`--base-url` / `PP_SEED_URLS`:

```bash
# BetMGM UK
python -m paddypower_scraper.cli --site betmgm --backend playwright -v --csv betmgm.csv

# Paddy Power (default)
python -m paddypower_scraper.cli --site paddypower --backend playwright -v

# Any site: give your own base URL + seeds
PP_SEED_URLS="https://book.example/football,https://book.example/tennis" \
    python -m paddypower_scraper.cli --base-url https://book.example --backend playwright
```

Presets live in `SITE_PRESETS` (`config.py`). Seed paths are best-effort
starting points — sites reorganise, so verify them against the live nav or pass
`--url` / `PP_SEED_URLS` for a precise run.

## Usage — CLI

```bash
# Scrape the preset's sport hubs, follow event links, print JSON
python -m paddypower_scraper.cli --site betmgm -v

# Specific pages, JS-rendered, save a flat CSV of every price
python -m paddypower_scraper.cli \
    --url https://sports.betmgm.co.uk/en/sports/football-4 \
    --backend playwright --csv prices.csv

# Offline: extract from a saved HTML file (no fetching, no bot-protection)
python -m paddypower_scraper.cli --html-file page.html
```

## Usage — Python

```python
from paddypower_scraper import PaddyPowerScraper, ScraperConfig

config = ScraperConfig(site="betmgm", fetch_backend="playwright", max_events_per_seed=30)
with PaddyPowerScraper(config) as scraper:
    events = scraper.scrape()               # crawl the preset's sport hubs

for event in events:
    print(event.sport, event.competition, event.name)
    for market in event.markets:
        for sel in market.selections:
            print(f"   {market.name}: {sel.name} {sel.price_fractional} "
                  f"({sel.price_decimal})")
```

## Usage — HTTP API (optional)

```bash
uvicorn paddypower_scraper.api:app --port 8100
curl -X POST localhost:8100/scrape -H 'content-type: application/json' \
     -d '{"urls":["https://www.paddypower.com/football"],"crawl":true}'
```

## Configuration

All settings live in `config.py` and are overridable via environment variables:

| Env var | Default | Purpose |
|---|---|---|
| `PP_SITE` | `paddypower` | Preset to target: `paddypower`, `betmgm`, … |
| `PP_BASE_URL` | preset's base | Override the target base URL |
| `PP_SEED_URLS` | preset's seeds | Comma-separated pages to start from |
| `PP_FETCH_BACKEND` | `requests` | `requests` or `playwright` (JS rendering) |
| `PP_MODEL` | `claude-opus-5` | Claude model. Use `claude-haiku-4-5` to cut cost on big runs |
| `PP_MIN_REQUEST_INTERVAL` | `2.0` | Min seconds between requests to a host |
| `PP_MAX_EVENTS_PER_SEED` | `25` | Event links followed off each seed page |
| `PP_MAX_PAGES` | `200` | Hard cap on pages per run |
| `PP_RESPECT_ROBOTS` | `true` | Honour robots.txt |
| `PP_MAX_CONTENT_CHARS` | `120000` | Page text sent to the model (context/cost guard) |

## Getting through bot protection

Paddy Power sits behind bot protection and renders odds with JavaScript, so the
plain `requests` backend will often be blocked or return an empty shell. For
real runs use `--backend playwright`, which drives a headless Chromium and
executes the page's JS before the text is read. If you reverse-engineer the
site's internal JSON odds API, point `PP_SEED_URLS` at those endpoints — the
LLM extractor happily reads JSON as well as HTML.

## Tests

Fully offline (Claude client and network are stubbed):

```bash
python -m pytest paddypower_scraper/tests/ -q
```

## ⚠️ Legal / responsible use

- Scraping may be **restricted by the target site's Terms of Service** (Paddy
  Power, BetMGM, etc.). Review them and get authorisation before scraping at
  scale. This tool honours `robots.txt` by default (`PP_RESPECT_ROBOTS=true`)
  and rate-limits requests.
- Odds and availability change constantly; scraped data is a **point-in-time
  snapshot** and must not be treated as a live/official price feed. For
  guaranteed real-time data, use an official odds/affiliate data API.
- You are responsible for complying with applicable gambling-data, copyright,
  and computer-misuse laws in your jurisdiction. Keep request volumes modest.
```
