# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

A serverless data pipeline that pulls daily surf forecasts for 7 Galicia spots and commits the result as JSON to this repo. GitHub Actions runs it twice daily (05:27 and 13:47 UTC). No server, no build step.

The output JSON is consumed by an external Claude skill (`multi-model-surf-briefing`) that produces daily surf briefings. **The data shape is a contract with that skill** — changes to top-level keys, spot names, or the `waves`/`wind`/`tide` structure will break it.

## Broader context

This repo implements **FR1 (forecast ingestion) only** of a larger product vision — the Galicia Surf Decision Engine. Other functional requirements (briefing logic, knowledge base, UI, personalization, session logging) live in separate components. See [docs/PRD.md](docs/PRD.md) for the full product vision, component map, and where each FR lives today.

When making changes here, stay within the FR1 scope: forecast ingestion, archival, and the JSON contract. Briefing logic, surf decision rules, and UI belong elsewhere.

## Architecture

`scripts/fetch.py` is the single entry point. For each spot in the `SPOTS` dict, it:

1. Calls **Open-Meteo Marine API** for 3-day hourly wave data with 3 models: `ewam` (DWD, 5 km regional — best for Galicia), `ncep_gfswave025` (global, 25 km), `meteofrance_wave` (~10 km global). No auth.
2. Calls **Open-Meteo Forecast API** for 3-day hourly wind with 3 models: `best_match`, `ecmwf_ifs025`, `gfs_seamless`.
3. Scrapes **wisuki.com** for 7 days of tides — times, heights, and tidal coefficients (Spanish/French 20–120 scale), with reference station name.
4. Has `timeout=60s` and `retries=2` on Open-Meteo (Bastiagueiro intermittently times out on first attempt).
5. Sleeps 1.5 s between spots for API politeness and to avoid clustered timeouts.

Results are merged into one dict and written to `today.json` (always overwritten) and `archive/<date>.json` (immutable per-day history). The workflow commits as `forecast-bot`.

## Schema

`today.json` top-level fields:

- `schema_version` — integer, currently `2`. Bump on any breaking change to per-spot structure.
- `generated_at` — ISO-8601 UTC timestamp.
- `spots` — dict keyed by spot name.

Each spot entry has:

- `lat`, `lon` — coordinates.
- `waves`, `wind` — raw Open-Meteo responses with model-suffixed field names (e.g. `wave_height_ewam`). On error, the value is `{"error": "..."}`.
- `tide` — **always a list** (empty `[]` when missing or unmapped). Each item: `date`, `reference_station`, `tides[]` (list of `{type, time, height_m, coefficient}`).
- `tide_error` — string, present **only** when tide retrieval failed or the spot has no Wisuki mapping (`"no_wisuki_mapping"`). Sibling of `tide`, not nested inside it.
- `_meta` — data-quality flags: `waves_ok`, `wind_ok`, `tide_ok`, plus per-wave-model flags `ewam_ok`, `gfswave_ok`, `mfwam_ok`. A model flag is `false` if the response errored or returned all null/zero values.

Public bundle URL: `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json`

Downstream consumers append a daily cache-buster query string (e.g. `?d=2026-05-06`) to bypass aggressive caching layers. GitHub ignores the query string and serves the same file; the suffix just acts as a cache key for any CDN or HTTP cache between the consumer and `raw.githubusercontent.com`.

## Spots

`pantin`, `doninos`, `razo`, `bastiagueiro`, `caion`, `larino`, `esteiro_xove`. Coordinates and Wisuki IDs are at the top of `scripts/fetch.py`.

## Known quirks — do not "fix" without thinking

- **NCEP_GFSWAVE025 returns zeros for 6 of 7 spots** (only Caión gets data). Documented Open-Meteo grid-search limitation for coastal points, not a bug. Consumers should treat all-zero arrays as "no data," not "flat ocean." The `_meta.gfswave_ok` flag will be `false` for those spots.
- **Esteiro de Xove returns null arrays for EWAM** (DWD's regional grid masks that cell). Only MFWAM produces wave data there; treat as single-model. NCEP GFS Wave is also zeros, as above. The `_meta.ewam_ok` flag will be `false`.
- **Lariño and Esteiro de Xove use proxy tide stations.** Lariño → Muros (~10 km away, same Ría de Muros e Noia). Esteiro de Xove → Foz (~20 km west, Mariña Lucense). The bundle's `reference_station` field will reflect this honestly — don't normalize it back to the spot name.
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
