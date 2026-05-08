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

1. Calls **Open-Meteo Marine API** for 7-day hourly wave data with 3 models: `ewam` (DWD, 5 km regional — best for Galicia), `ncep_gfswave025` (global, 25 km), `meteofrance_wave` (~10 km global). No auth.
2. Calls **Open-Meteo Forecast API** for 7-day hourly wind with 3 models: `best_match`, `ecmwf_ifs025`, `gfs_seamless`.
3. Scrapes **wisuki.com** for 7 days of tides — times, heights, and tidal coefficients (Spanish/French 20–120 scale), with reference station name.
4. Has `timeout=60s` and `retries=2` on Open-Meteo (Bastiagueiro intermittently times out on first attempt).
5. Sleeps 1.5 s between spots for API politeness and to avoid clustered timeouts.

Results are merged into one dict, then **two writes** happen with different formatting:

- `archive/<date>.json` — full Open-Meteo response, indented. Immutable per-day history; kept fat for debugging.
- `today.json` — slim copy: Open-Meteo metadata (`generationtime_ms`, `hourly_units`, `utc_offset_seconds`, `elevation`, `model_elevation`, `timezone`, `timezone_abbreviation`) stripped from `waves`/`wind` blocks; the `time` array deduped between `waves.hourly` and `wind.hourly` (kept only on `waves.hourly`); all floats rounded to 2 decimals; written single-line with `separators=(",", ":")`. Live consumers read this; size is minimized to avoid `web_fetch` truncation in claude.ai.

Before the writes, `fetch.py` runs sanity checks (assertions on the spot set and on having ≥7 forecast days) — drift causes the workflow to fail without committing. The workflow commits as `forecast-bot`.

## Schema

`today.json` top-level fields:

- `schema_version` — integer, currently `2`. Bump on any breaking change to per-spot structure.
- `generated_at` — ISO-8601 UTC timestamp.
- `spots` — dict keyed by spot name.

Each spot entry has:

- `lat`, `lon` — coordinates of the SPOT (top-level on the spot entry).
- `waves`, `wind` — Open-Meteo responses with model-suffixed field names (e.g. `wave_height_ewam`). On error, the value is `{"error": "..."}`. In the slim `today.json`, the metadata blocks listed above (`generationtime_ms`, `hourly_units`, etc.) are removed, but the inner `latitude` / `longitude` fields are **kept** — those are the model grid-cell coordinates, not duplicates of the spot's lat/lon, and they're how grid-mask issues like Esteiro de Xove's EWAM null are diagnosed. `wind.hourly.time` is dropped when it equals `waves.hourly.time`; consumers read time from `waves.hourly.time`. The archive file under `archive/<date>.json` keeps the full Open-Meteo response un-stripped.
- `tide` — **always a list** (empty `[]` when missing or unmapped). Each item: `date`, `reference_station`, `tides[]` (list of `{type, time, height_m, coefficient}`).
- `tide_error` — string, present **only** when `tide` is empty due to a problem. Values: `"no_wisuki_mapping"` (no Wisuki ID configured for the spot), `"empty_scrape"` (Wisuki returned no parseable rows — likely an upstream HTML change), or `"<ExceptionClass>: <message>"` for raised exceptions. Sibling of `tide`, not nested inside it.
- `_meta` — data-quality flags: `waves_ok`, `wind_ok`, `tide_ok`, plus per-wave-model flags `ewam_ok`, `gfswave_ok`, `mfwam_ok`. A model flag is `false` if the response errored or returned all null/zero values.

Public bundle URLs: `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json` (always-current) and per-day archive at `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/archive/{YYYY-MM-DD}.json`.

Downstream consumers should fetch the **dated archive path** for the current UTC date, not the bare `today.json`. The bare URL is cached aggressively by intermediate layers — notably claude.ai's `web_fetch`, whose TTL can persist for days inside a session and was empirically observed serving a 31h-old cached bundle in May 2026. The dated archive path changes daily, so it's a fresh cache key each day. Fall back to the bare URL only when the dated archive 404s (between 00:00 UTC and the morning cron firing, when today's archive doesn't exist yet) or when the consumer's allowlist rejects path-based dated URLs.

The earlier `?d=YYYY-MM-DD` query-string approach was abandoned: claude.ai's `<sources_in_this_project>` allowlist uses exact-string URL matching and rejects URLs with appended query strings. A path-based date avoids that.

### `today_summary.json` — derived per-window summary

`today_summary.json` (with per-day history in `archive_summary/`) is produced by `scripts/compute_summary.py` after each `fetch.py` run. Independent versioning: its own `schema_version: 1`, separate from the bundle's. Top-level keys: `generated_at`, `source_bundle_at` (the bundle's `generated_at`), `windows` (definitions of `morning`/`afternoon`/`full_day` as local-time hour ranges), `thresholds` (script constants echoed for self-describing output), and `spots`. Per spot per day, the file emits two parallel views: hourly arrays (24 model-aggregated values per field for `{mean, spread}`) AND per-window summaries that aggregate over hours within the window — same field set, plus a categorical `agreement` label (`high`/`medium`/`low`/`single_model`/`n/a`) per field derived from spread vs threshold. Wave-model selection respects `_meta` flags from the bundle (drops models flagged as zero/null on a spot-by-spot basis). Wind speed and gusts pre-converted to knots (km/h ÷ 1.852). Direction uses circular mean (atan2 of unit vectors), spread = max angular distance from circular mean, capped at 180°. Imperial conversion is NOT done in this file — that stays in the consumer.

Public summary URLs: `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json` (always-current) and per-day archive at `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/archive_summary/{YYYY-MM-DD}.json`. Same cache-busting note as `today.json` above — consumers should prefer the dated archive path.

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
pip install -r requirements.txt
python scripts/fetch.py
```

Writes `today.json` and `archive/YYYY-MM-DD.json`. No test suite, no linter.

If Python isn't installed locally, use GitHub Actions as the test loop: edit → commit → push → `gh workflow run forecast.yml` → `gh run watch` → inspect resulting `today.json`. ~60 seconds per cycle.

## What this repo does NOT contain

Briefing logic still executes in claude.ai. This repo hosts the data pipeline (`scripts/`) AND the source-of-truth for the consuming skill body (`skills/multi-model-surf-briefing/SKILL.md`), version-controlled here so the skill stays in sync with bundle-shape changes. Don't add per-spot guide knowledge, board-pick judgment, or rendering logic in `scripts/` — that's skill territory.
