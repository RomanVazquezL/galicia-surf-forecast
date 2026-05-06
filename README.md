# galicia-surf-forecast

Daily multi-model surf forecast bundle for 7 Galicia spots. A GitHub Actions cron pulls Open-Meteo wave + wind data and Wisuki tides twice a day, writes them to `today.json`, and commits the result back to this repo. No server, no build step.

This is the data-pipeline component (FR1) of the **Galicia Surf Decision Engine**. See [docs/PRD.md](docs/PRD.md) for the broader product vision.

## The bundle

Public URL: <https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json>

- **Refreshed:** twice daily (early morning + afternoon UTC) by GitHub Actions.
- **Contents:** per-spot 72-hour wave forecasts from 3 wave models, 72-hour wind from 3 wind models, and 7 days of tides (times, heights, coefficients).
- **Schema:** versioned (`schema_version: 2`); each spot has `lat`, `lon`, `waves`, `wind`, `tide`, plus `_meta` quality flags and an optional `tide_error`. The full shape is a contract with the consuming `multi-model-surf-briefing` Claude skill — see [CLAUDE.md](CLAUDE.md#schema) before changing it.

Per-day immutable copies live in `archive/YYYY-MM-DD.json`.

## Spots

`pantin`, `doninos`, `razo`, `bastiagueiro`, `caion`, `larino`, `esteiro_xove`.

Coordinates and Wisuki IDs are at the top of `scripts/fetch.py`.

## Run locally

```bash
pip install -r requirements.txt
python scripts/fetch.py
```

Writes `today.json` and `archive/YYYY-MM-DD.json` to the current directory.

## More

- Working in this repo? Read [CLAUDE.md](CLAUDE.md) — architecture, data shape, and known quirks.
- Where this fits in the larger product? Read [docs/PRD.md](docs/PRD.md).

## Status

MVP, single user, Galicia only. Implements FR1 of the broader product roadmap.
