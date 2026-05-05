# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

A serverless data pipeline that pulls daily surf forecasts for 6 Galicia spots and commits the result as JSON to this repo. GitHub Actions runs it twice daily (06:30 and 12:30 UTC). No server, no build step.

The output JSON is consumed by an external Claude skill (`multi-model-surf-briefing`) that produces daily surf briefings. **The data shape is a contract with that skill** — changes to top-level keys, spot names, or the `waves`/`wind`/`tide` structure will break it.

## Architecture

`scripts/fetch.py` is the single entry point. For each spot in the `SPOTS` dict, it:

1. Calls **Open-Meteo Marine API** for 3-day hourly wave data with 3 models: `ewam` (DWD, 5 km regional — best for Galicia), `ncep_gfswave025` (global, 25 km), `meteofrance_wave` (~10 km global). No auth.
2. Calls **Open-Meteo Forecast API** for 3-day hourly wind with 3 models: `best_match`, `ecmwf_ifs025`, `gfs_seamless`.
3. Scrapes **wisuki.com** for 7 days of tides — times, heights, and tidal coefficients (Spanish/French 20–120 scale), with reference station name.
4. Has `timeout=60s` and `retries=2` on Open-Meteo (Bastiagueiro and San Xurxo intermittently time out on first attempt).
5. Sleeps 1.5 s between spots for API politeness and to avoid clustered timeouts.

Results are merged into one dict and written to `today.json` (always overwritten) and `archive/<date>.json` (immutable per-day history). The workflow commits as `forecast-bot`.

## Data shape

`today.json` top-level: `generated_at` (ISO-8601 UTC), `spots` (dict keyed by spot name). Each spot has `lat`, `lon`, `waves`, `wind`, `tide`. Wave/wind responses are raw Open-Meteo with model-suffixed field names. Tide is a list of daily objects (`date`, `reference_station`, `tides[]`).

Public bundle URL: `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json`

## Spots

`pantin`, `doninos`, `razo`, `bastiagueiro`, `san_xurxo`, `caion`. Coordinates and Wisuki IDs are at the top of `scripts/fetch.py`.

## Known quirks — do not "fix" without thinking

- **NCEP_GFSWAVE025 returns zeros for 5 of 6 spots** (only Caión gets data). Documented Open-Meteo grid-search limitation for coastal points, not a bug. Consumers should treat all-zero arrays as "no data," not "flat ocean."
- **Doniños and San Xurxo land in the same Open-Meteo wave grid cell** (both resolve to ~43.5°N, -8.4°W, 7 km apart in reality). Wave forecasts will always be identical between these two spots — only wind and tide differentiate them.
- **WISUKI slugs lost accented characters when copy-pasted** (`pantn` not `pantin`, `donios` not `doninos`, `cain` not `caion`). Wisuki redirects from these to canonical, so they work — don't "fix" them as typos.
- **Wave model names came from Open-Meteo's GitHub issues, not docs**. ECMWF WAM was dropped because we couldn't pin down its parameter string. If adding a new wave model, verify against open-meteo/open-meteo issues before assuming.

## Running locally

```bash
pip install requests beautifulsoup4
python scripts/fetch.py
```

Writes `today.json` and `archive/YYYY-MM-DD.json`. No test suite, no linter.

If Python isn't installed locally, use GitHub Actions as the test loop: edit → commit → push → `gh workflow run forecast.yml` → `gh run watch` → inspect resulting `today.json`. ~60 seconds per cycle.

## What this repo does NOT contain

The consuming skill (`multi-model-surf-briefing`) lives elsewhere. Don't add briefing logic, surf decision rules, or visualization here. This repo is data pipeline only.
