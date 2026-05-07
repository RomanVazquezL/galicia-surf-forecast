---
name: multi-model-surf-briefing
description: Default daily surf-briefing skill for the user's seven core Galicia spots — Pantín, Doniños, Razo, Bastiagueiro, Caión, Lariño, Esteiro de Xove. Uses a multi-model forecast bundle hosted on GitHub (refreshed daily by GitHub Actions cron, three independent wave models + three independent wind models per spot) instead of live HTML scraping. Trigger on "daily briefing", "morning briefing", "surf outlook", "surf check", "what's it doing today", "should I surf today", "where should I surf this morning", "run the briefing", "do the daily", "surf brief", "how's [day] looking", "what's the forecast for [date]", or any request that names a Galicia spot and asks for conditions today/this week. Falls back automatically to daily-surf-briefing when the bundle is stale, missing, or the requested spot is outside the bundled set. Galicia only — does not cover NY, trips, or wave pools.
---

# Multi-Model Surf Briefing — Galicia

Morning surf outlook for the A Coruña / Ferrolterra region, built on a multi-model forecast bundle refreshed daily on GitHub. Output mirrors the `daily-surf-briefing` card format — one mobile card per requested day, prose backup underneath.

The differentiator versus `daily-surf-briefing`: a GitHub Actions cron runs twice per day. `fetch.py` pulls forecasts from three independent wave models (DWD EWAM 5 km regional, NCEP GFS Wave ~25 km global, MeteoFrance Wave ~10 km global) plus three independent wind models (Open-Meteo `best_match`, ECMWF IFS025, GFS seamless) for seven pre-defined spots, and `compute_summary.py` then produces a derived summary file with per-spot, per-day, per-window aggregates and **categorical agreement labels** baked in. The result: real cross-model triangulation runs automatically every morning, with the deterministic arithmetic done in Python, not in this skill.

This is the default daily-briefing skill. The old `daily-surf-briefing` handles fallbacks: stale bundle, spots outside the bundle, trip planning, anywhere outside Galicia.

## When to use

Same trigger phrases as `daily-surf-briefing` — daily briefing, morning briefing, surf outlook, what's it doing today, should I surf, run the briefing, how's Thursday looking, etc. Try this skill first. If Step 1 finds the summary stale or unavailable, hand off to `daily-surf-briefing`.

If the user asks about NY, The Wave Bristol, or a trip location, redirect — neither skill covers those.

## The summary file

URL (hardcoded, easy to update if the username/repo changes):

```
https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json
```

**Fetch the bare URL — do NOT append a `?d={YYYY-MM-DD}` cache-buster.** Earlier versions of this skill appended a cache-buster to defeat downstream HTTP caches (Cloudflare, web_fetch's internal cache). It was removed because claude.ai's `<sources_in_this_project>` permission layer uses **exact-string URL matching** against the project sources list — adding `?d=...` makes it a different string from the bare URL listed in project instructions, which fires `PERMISSIONS_ERROR` before the request ever reaches GitHub. Freshness is enforced by reading `source_bundle_at` inside the JSON (see Step 1), not by URL cache-busting. Worst case `web_fetch` serves a 5–15 minute stale cached copy, but `source_bundle_at` still reflects the underlying file's actual generation time, so the 24h / 30h staleness thresholds catch genuine issues.

**Pass an explicit `text_content_token_limit` on the `web_fetch` call.** The summary is ~250 KB at 7 days × 7 spots × hourly arrays + windows. The default token limit on `web_fetch` truncates mid-document — typically after 2–3 spots — leaving the rest silently dropped. Use `text_content_token_limit=300000` (or higher) to ensure the full file lands in context.

The raw bundle (`today.json`, same repo) is still available for ad-hoc inspection if you need to drill below the summary, but **do not re-aggregate it** — the summary already did the deterministic work.

Refreshed twice daily by GitHub Actions cron. Public repo, no auth needed. One file per day; older days are also archived under `archive_summary/{YYYY-MM-DD}.json` in the same repo.

### Schema (summary, `schema_version: 1`)

Top-level fields:
- `schema_version` — integer; bump indicates a breaking change to per-spot structure.
- `generated_at` — ISO timestamp from when `compute_summary.py` ran.
- `source_bundle_at` — ISO timestamp from when `fetch.py` produced the underlying raw bundle. **This is the freshness reference for the briefing.**
- `windows` — definitions: `morning` is `06:00–12:00`, `afternoon` is `12:00–18:00`, `full_day` is `06:00–20:00` (local Madrid time, end-exclusive).
- `thresholds` — the script-level constants used to derive agreement labels, echoed for self-describing output. Currently: `wave_height_m: 0.3`, `wave_height_pct: 25`, `period_s: 2`, `wave_direction_deg: 30`, `wind_speed_kt: 5`, `wind_direction_deg: 30`. Reference these in the footnote when needed instead of restating values.
- `spots` — dictionary keyed by spot slug. Seven spots: `pantin`, `doninos`, `razo`, `bastiagueiro`, `caion`, `larino`, `esteiro_xove`.

Per-spot:
- `lat`, `lon` — coordinates.
- `data_quality` — `{ewam_ok, gfswave_ok, mfwam_ok, wind_ok, tide_ok, n_models_waves}`. `n_models_waves` is the count of wave models with usable data for this spot (0–3). Use it to detect single-model spots (Esteiro de Xove) and zero-model spots (rare; full degrade).
- `days` — keyed by ISO date (`YYYY-MM-DD`). Seven days, today onward.

Per spot per day:
- `hourly` — model-aggregated hourly arrays in 24-hour blocks. Use only when the user asks about a specific hour. Fields:
  - `hourly.time` — `["00:00", "01:00", ...]` (24 entries, local time).
  - `hourly.waves.{height_m, period_s, direction_deg, swell_height_m, swell_period_s, swell_direction_deg}` each as `{mean: [...], spread: [...]}`.
  - `hourly.wind.{speed_kt, direction_deg, gusts_kt}` same shape.
- `windows` — pre-computed aggregates over `morning`, `afternoon`, `full_day`. **Use this for everything except specific-hour questions.** Per window:
  - `waves.{height_m, period_s, direction_deg, swell_height_m, swell_period_s, swell_direction_deg}` — scalars: linear fields use `{mean, spread}`; direction fields use `{mean_circular, spread}`.
  - `waves.agreement` — `{height, period, direction}` each labeled `"high"`, `"medium"`, `"low"`, `"single_model"`, or `"n/a"`.
  - `waves.models_used`, `waves.models_dropped`, `waves.single_model` — transparency about which wave models contributed.
  - `wind.{speed_kt, direction_deg, gusts_kt}` — same shape, with `wind.agreement` = `{speed, direction}`.
  - `wind.models_used` — always all three when `wind_ok`.
  - `n_hours` — number of hourly samples in the window.
- `tide` — `{reference_station, events: [{type, time_local, height_m, coefficient}, ...]}`. Already filtered to this date. May be `null` when the Wisuki scrape failed for this spot — see the bundle's `tide_error` field for cause.

**All numeric values are metric.** Wind speed and gusts are pre-converted to knots. Apply imperial conversion (m → ft, kt → km/h) at presentation time only, per the project's `<input_conventions>`. Do NOT convert at calculation time.

### Models — what to know

**Wave models:**
- **EWAM (DWD)** — 5 km regional. Highest-resolution wave model in the bundle. Best for Galicia. Treat as the primary wave reference when present in `waves.models_used`.
- **MeteoFrance Wave (MFWAM)** — ~10 km global, Atlantic-tuned. Solid secondary.
- **NCEP GFS Wave 0.25°** — global ~25 km. Coastal limitation: returns all-zero arrays at most spots; `compute_summary.py` already drops it from aggregation when `_meta.gfswave_ok=false`. In practice, only Caión receives non-zero NCEP data — and even there it's occasionally artifact-y. The summary's `models_used` and `models_dropped` lists tell you per spot, per window which models contributed.

In practice most spots have **2 useful wave models**, not 3. Esteiro de Xove has only 1 (see quirks below).

**Wind models:**
- **best_match (Open-Meteo)** — meta-model that picks the best regional model per location. For Galicia it typically routes to ICON-EU (DWD's 6.5 km regional). Treat as a third independent opinion despite being a meta-selector.
- **ECMWF IFS025** — ECMWF's flagship at ~9 km. The European reference.
- **GFS seamless (NOAA)** — global ~27 km. Lowest atmospheric resolution of the three; weakest at cape spots.

**Resolution priority for cape-spot wind disagreement:** best_match (≈ ICON-EU 6.5 km) > ECMWF IFS025 (9 km) > GFS seamless (27 km). The summary computes wind aggregates as an equal-weighted mean across all three and reports `agreement.direction` and `agreement.speed` labels. When the leading pick is at a cape spot (Pantín, Doniños) and `wind.agreement.direction` reads `"low"`, flag in the footnote that the higher-res pair (best_match + ECMWF IFS025) is structurally more trustworthy at that cape — but don't override the mean. If you want to drill into per-model values, fall back to the raw bundle.

### Bundle / summary quirks (read carefully)

- **GFS Wave zeros — already handled.** `compute_summary.py` drops NCEP from aggregation per spot via `_meta.gfswave_ok`. You'll see it in `waves.models_dropped` for affected spots. Don't try to re-handle.
- **Esteiro de Xove has no EWAM.** All EWAM arrays are null at this grid cell — DWD's regional 5 km grid masks coastal cells on Mariña Lucense. GFS Wave is also zeros there. Only MFWAM produces wave data. The summary marks this with `data_quality.n_models_waves: 1`, `waves.single_model: true`, and `agreement.{height,period,direction}: "single_model"`. Treat Esteiro as **structural ●○○** (auto, regardless of forecast-day) and explain in the footnote.
- **Lariño and Esteiro de Xove use proxy tide stations.** Lariño tide is from Muros (~10 km, same Ría de Muros e Noia — times agree to within minutes). Esteiro de Xove tide is from Foz (~20 km west, Mariña Lucense). The summary's `tide.reference_station` field reflects this honestly. Don't try to "correct" the timing for these — the offset is small enough to ignore for decision windows.
- **`best_match` is a meta-model.** It looks like a third opinion but it's a router that picks one of several models behind the scenes. Still treat as independent for agreement purposes — for Galicia it'll be ICON-EU, which genuinely is independent from ECMWF IFS and GFS — but flag this in the footnote when relevant.

## Workflow

### Step 1 — Fetch the summary and verify freshness

`web_fetch` the summary URL — the **bare** URL, no query string:

```
https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json
```

Pass `text_content_token_limit=300000` on the call so the full ~250 KB file isn't truncated. See **The summary file** section above for why both of those (bare URL and explicit token limit) matter.

**Precondition for trustworthy fetch:** the summary URL must be present in this project's custom instructions (under `<sources_in_this_project>`) so claude.ai treats it as user-provided context for `web_fetch`. Without that, fresh sessions return `PERMISSIONS_ERROR` and this skill falls back to Tier 1.5 (raw bundle) per the rules below.

Branch on the result:

**If `web_fetch` succeeds**, parse JSON. Read `source_bundle_at` (NOT `generated_at` — `generated_at` is when the summary script ran; `source_bundle_at` is when the underlying forecast was pulled, which is the actual data freshness).

**Compute freshness in UTC.** `source_bundle_at` is an ISO-8601 UTC timestamp (suffix `Z` or `+00:00`). The system clock shown to you may be in a different timezone — Madrid is UTC+1 (CET) or UTC+2 (CEST). Convert system local to UTC before subtracting, or pull `now_utc` directly. Example: a bundle generated at `2026-05-07T00:14:58Z`, queried at 06:14 Madrid local on 2026-05-07, is `06:14 − 02:00 (CEST offset) − 00:14:58 = ~4 hours` old, not ~12 hours. A common error mode is to read the system clock as if it were UTC and overestimate the age by the timezone offset; sanity-check before writing the footnote.

Three cases:

- **Within 24 hours of now** → fresh, proceed to Step 2.
- **24–30 hours old** → fresh-ish (Actions probably ran but slightly late). Proceed but note in the footnote.
- **More than 30 hours old** → stale. The cron likely failed. Tell the user briefly ("summary is stale, falling back to direct fetch"), then proceed to Tier 2 (`daily-surf-briefing` via Wisuki/AEMET). Stop running this skill.

> **Note:** with `forecast_days=7` in the bundle, a 24-hour-old summary still has 6 fresh days ahead — even if the cron missed once, day-1 through day-5 forecasts remain inside the bundle's horizon. Don't over-trigger the stale fallback for normal cron-skip cases.

**If `web_fetch` returns `PERMISSIONS_ERROR`** on the summary URL — the URL isn't in this project's allowed sources, OR you appended a query string and the exact-match permission check is rejecting it. **First, double-check you fetched the bare URL** (no `?d=...`, no other query string). If you did and it still fails, output ONE short setup-required message and proceed to Tier 1.5 (do not stop the turn):

> Multi-model summary needs one-time setup. Add `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json` to `<sources_in_this_project>` in this project's custom instructions. See `docs/SKILL_SETUP.md`. Falling back to the raw bundle for now.

This message will fire every session that hits `PERMISSIONS_ERROR` until the user adds the URL — skills don't have cross-session state, so "fires until setup is done" is the contract. It is **distinct** from per-session paste prompts (which were removed) — the user's action here is one-time and persistent.

**If `web_fetch` returns 404, network error, or JSON parse error** on the summary → fall back silently to Tier 1.5. No setup message; the URL is fine, the file is just unreachable for transient reasons.

**Tier 1.5 fallback — raw bundle (`today.json`).** When the summary is unreachable: `web_fetch` the **bare** bundle URL `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json` (no `?d=...` cache-buster — same exact-match permission rule applies). Pass `text_content_token_limit=300000` here too — the slim bundle is ~180 KB and gets truncated by default. If that succeeds, parse and run inline aggregation per Step 5b. The bundle's footnote MUST flag: "Multi-model summary unavailable; using on-the-fly bundle aggregation. Confidence labels approximated from cross-model spread; not pre-computed."

If `today.json` is also unreachable (rare — the user typically has it in project sources), or the requested date is outside the bundle's horizon (`forecast_days` from `source_bundle_at`), proceed to Tier 2.

**Tier 2 fallback — `daily-surf-briefing` (Wisuki/AEMET).** Follow `/mnt/skills/user/daily-surf-briefing/SKILL.md`. Use this when both the summary and the bundle are unreachable, or when the requested date is past the bundle's horizon (10-day Wisuki coverage helps here).

### Step 2 — Load the Galicia Surf Spot Guide

Identical to `daily-surf-briefing` Step 1. Run `view /mnt/project/` to find the guide (currently `Galicia_Surf_Spot_Guide_v2.docx`; match on the prefix). Read the relevant sub-coast sections in full — this is the per-spot translation layer between forecast numbers and conditions.

If the guide is missing, flag in the footnote and degrade per-spot reads.

### Step 3 — Read pre-computed values for the requested day(s) and window(s)

This is the step that used to do array-slicing arithmetic. **Now it's a series of dictionary reads.**

For each candidate spot in the bundle:

1. Resolve `target_date` (default: today's local date in Europe/Madrid) and `target_window` (default: `morning`; `afternoon` and `full_day` available).
2. Read `spots[name].days[target_date].windows[target_window]`. Pull `waves.height_m.mean`, `waves.height_m.spread`, `waves.period_s.mean`, etc. directly. **Do not average across models. Do not recompute spreads.** The summary already did this, respecting `_meta` flags from the bundle.
3. Read `windows[target_window].waves.agreement.{height, period, direction}` and `windows[target_window].wind.agreement.{speed, direction}` for confidence labels.
4. Read tide events from `spots[name].days[target_date].tide.events`. If `tide` is `null` for that day (Wisuki scrape failed or no Wisuki mapping), do a single `web_fetch` to Wisuki tide for one representative spot (`wisuki.com/tide/6767/cain` for south coast, `wisuki.com/tide/7394/pantn` for Ferrolterra, `wisuki.com/tide/6078/muros` for Lariño, `wisuki.com/tide/6070/foz` for Esteiro) — A Coruña and Ferrol times differ by <30 min, coefficient is the same. Note the fallback in the footnote.

For specific-hour questions ("what about 9 am?"): drill into `spots[name].days[date].hourly`. Find the index `i` such that `hourly.time[i] == "09:00"`, then read `hourly.waves.height_m.mean[i]`, `hourly.wind.speed_kt.mean[i]`, etc. Same fields as the window block, just index-addressed.

### Step 4 — Read agreement labels (do not compute them)

The summary emits categorical labels per field, derived against the thresholds in `summary.thresholds`. **Read them — don't recompute the spread vs threshold yourself.**

For each spot's selected window:

- Wave: `waves.agreement.{height, period, direction}`
- Wind: `wind.agreement.{speed, direction}`

Each label is one of:
- `"high"` — spread ≤ half the threshold; models agree closely
- `"medium"` — spread ≤ threshold; models agree modestly
- `"low"` — spread > threshold; meaningful disagreement
- `"single_model"` — only one model contributed (no triangulation possible)
- `"n/a"` — no models contributed (data unavailable)

**Light-wind direction caveat — apply BEFORE the dot-indicator mapping.** When `wind.speed_kt.mean < 6` for the relevant window, treat `wind.agreement.direction = "low"` as **informational, not decision-relevant**, and do not let it drive the dot rating. The 30° absolute threshold doesn't scale with wind speed — at 3-4 kt, models legitimately disagree on direction by 30-70° because the wind is so light it's effectively variable, and the disagreement says nothing about surf-relevant conditions. At >6 kt the same `"low"` label is a real call (it would shift wave shape) and should propagate normally. This carveout applies to direction only — `wind.agreement.speed = "low"` at any wind speed is still decision-relevant.

**Map to dot indicator per spot** for the card header (Step 7), based on the per-spot worst label across both wave and wind agreement (after applying the light-wind caveat above):

- **●●●** — every relevant agreement label reads `"high"`.
- **●●○** — at least one label reads `"medium"`; nothing reads `"low"` or `"single_model"`.
- **●○○** — any label reads `"low"` or `"single_model"`, OR `data_quality.n_models_waves == 1`, OR `data_quality.wind_ok == false`.

When the **leading-pick spot** is rated ●○○, **auto-downgrade the badge by one notch** (GO → MARGINAL, MARGINAL → SKIP). Cite the disagreeing variable and which models disagreed. The summary's `models_used` and `models_dropped` lists give you the cite directly.

**Order of operations — do not re-rank picks to preserve badge color.** Pick the leading spot by Step 6 conditions fit (wind → tide → period → size/direction → exposure), THEN apply the agreement-based badge downgrade. The downgrade exists to make the badge reflect the leading pick's confidence — it is not a tiebreaker between candidate spots. If Caión is the right call by conditions but rated ●○○, the answer is "Caión, MARGINAL," not "Razo to keep the badge GO." Re-ranking by agreement after Step 6 inverts the rule's intent and optimises for presentation over decision quality.

**Esteiro de Xove is permanently single-model for waves** (only MFWAM) — `waves.single_model: true`, agreement labels read `"single_model"`. Auto ●○○ regardless of forecast-day spread. This is structural, not a forecast-day issue. Flag it as such in the footnote rather than as a model disagreement.

### Step 5 — Resolve disagreement when models conflict

The summary's window means already aggregate equal-weighted across surviving models. So most disagreement is already "resolved" before you read it — the mean is what you report. What's left:

**Wave disagreement** — when `waves.agreement.height` (or `period`/`direction`) is `"low"`, the spread > threshold. The mean is still your best single number; cite the spread and which models contributed via `waves.models_used` (e.g., "EWAM and MFWAM disagree on height by ~0.5 m"). With only 2 models surviving, "spread" equals "absolute difference" — say so. With only 1 surviving model (Esteiro de Xove), there is no triangulation; report MFWAM's number as the only number with a confidence caveat.

**Caión NCEP-outlier sanity check.** Caión is the only spot where NCEP GFS Wave returns non-zero data — and CLAUDE.md notes it can be artifact-y. The summary aggregates all surviving models equal-weighted, so a single artifact-y NCEP value can pull the Caión mean off and inflate the spread, producing a `"low"` agreement label that's NCEP being NCEP rather than genuine model uncertainty. **When all of these hold:** (a) Caión is the leading pick, (b) `waves.models_used` contains all three (`ewam`, `meteofrance_wave`, `ncep_gfswave025`), and (c) any `waves.agreement.{height,period,direction}` reads `"low"` — drill into the raw bundle (`today.json`, Tier 1.5 read per Step 1) and pull per-model values for the same hours. If EWAM and MFWAM cluster within threshold and NCEP is the outlier, treat the EWAM+MFWAM mean as the operative number, downgrade NCEP's contribution, and note in the footnote: "NCEP GFS Wave outlier at Caión; EWAM+MFWAM consensus used." If all three actually disagree (or NCEP and one of EWAM/MFWAM cluster against the third), the summary's mean is fine and the `"low"` label is real — report it as-is. Do NOT fabricate a "real swell transition" narrative to explain away NCEP disagreement without checking the per-model values; rationalising into a story is the failure mode this rule exists to prevent.

**Wind at cape spots** (Pantín, Doniños — Cabo Prior shadow zone) — when `wind.agreement.direction` or `wind.agreement.speed` reads `"low"` at a cape spot, note in the footnote that the higher-res pair (best_match ≈ ICON-EU 6.5 km, ECMWF IFS025 9 km) is structurally more trustworthy than GFS seamless (27 km) at that cape. The summary's mean averages all three equally; the user should be aware that GFS may be pulling the mean off. If the call is genuinely close (e.g., the wind direction mean lands right at the edge of "offshore"), recommend an on-arrival check rather than overriding the mean. For per-model drill-down you'd need to re-fetch the raw bundle — usually not worth it.

**Wind at flat-coast spots** (Caión, Razo, Bastiagueiro, Lariño, Esteiro de Xove) — equal-weighted mean is fine. If `wind.agreement` reads `"low"` here, that's a real synoptic-uncertainty flag, not a resolution-artifact issue.

### Step 5b — Inline aggregation for the Tier 1.5 fallback (raw bundle)

Only used when the primary summary path fails and we fall back to `today.json` per Step 1. The arithmetic in this step is exactly what `compute_summary.py` does in Python — just done in-context here because we don't have the pre-computed file. Acceptable on this fallback path only; not a relaxation of the primary-path "do NOT re-aggregate" rule.

**Bundle shape note (slim variant, current):** live `today.json` is compact and slimmed. `wind.hourly.time` may be absent — when it is, time alignment uses `waves.hourly.time` (Open-Meteo returns aligned grids when both endpoints request the same timezone). `latitude`/`longitude` inside `waves`/`wind` blocks are model grid-cell coords — useful for diagnostics, not for spot identity (use top-level `lat`/`lon`).

For each requested spot × day × window:

1. **Locate hours.** Find indices `i` in `waves.hourly.time` where `time[i][:10] == target_date` AND the hour in `time[i][11:13]` is in `[window_start, window_end)`.
2. **Aggregate waves.**
   - For each model in `{ewam, ncep_gfswave025, meteofrance_wave}`: read `waves.hourly.wave_height_<model>[i]` for the located indices.
   - **Drop a model whose entire window-slice is null or zero** (this respects what `_meta.{ewam,gfswave,mfwam}_ok` would have flagged).
   - Compute mean and `max-min` spread across surviving models. Repeat for `wave_period_<model>` (linear), `wave_direction_<model>` (circular: take `atan2(sum sin, sum cos)` of the unit-vector means; spread = max angular distance from circular mean, capped at 180°).
   - Repeat for `swell_wave_height_<model>`, `swell_wave_period_<model>`, `swell_wave_direction_<model>`.
3. **Aggregate wind.** Use `waves.hourly.time` for time alignment (slim bundle drops the duplicate). For each model in `{best_match, ecmwf_ifs025, gfs_seamless}`: read `wind_speed_10m_<model>` and `wind_gusts_10m_<model>` (in km/h — convert to knots: ÷ 1.852), and `wind_direction_10m_<model>` (circular, same as wave direction).
4. **Derive agreement labels** by comparing each spread to the threshold (same values as the primary path: `0.3 m / 25 %` for wave height, `2 s` period, `5 kt` wind speed, `30°` direction). `high` if spread ≤ 0.5×threshold, `medium` if ≤ threshold, `low` if > threshold. `single_model` if only one model survived. `n/a` if zero.
5. **Render the card normally**, with the Tier 1.5 footnote flag from Step 1 included so the user knows the aggregation is approximate.

### Step 6 — Apply decision logic per spot

For each candidate spot, walk the project's standard order: **wind → tide → period → size/direction → exposure → board.** Use the Galicia guide as the rule lookup.

Concrete loop:

1. List candidate spots — the 7 bundled spots, plus any guide spots accessed via the proxy map below.
2. For each, look up its rules in the guide: required swell direction & minimum size, offshore wind direction, tide window, hazards.
3. Compare the summary's window means (and tide events for the day) against those rules.
4. Score each spot: green (all match), amber (one mismatch), red (multiple mismatches).
5. Apply the agreement rating from Step 4 — the more uncertain the data, the less confident the call.

**Anti-patterns** carry over from `daily-surf-briefing`:

- Don't extrapolate one coast to another. The summary gives data for each spot directly; use it.
- Don't use offshore size as nearshore size. Summary wave heights derive from Open-Meteo's wave model output at the coastal grid cell — nearshore-open-water. On exposed open beaches, breaking surf is ≈ 10–25% smaller than the model number (1.0 m model → ~2.5–3 ft breaking). For ría spots, use the guide's per-spot operating window thresholds.

### Step 7 — Pick spots and apply the proxy map

Pick three ranked spots (A / B / C). The summary covers 7 spots directly; for guide spots beyond the 7, use the proxy mapping below. When a proxy is used, name it in the spot pick reasoning ("Caión data, applied to Sabón's E/NE wind tolerance and tide window").

#### Proxy map — Galicia guide spot → bundled proxy

**A Coruña / south coast / Costa da Morte:**
- Caión → `caion` (direct)
- Sabón / Barrañán / Repibelo / O Reiro / Valcobo → `caion` (~5–7 km, same wind/tide window — apply per-spot exposure adjustments from the guide)
- Razo → `razo` (direct)
- Baldaio → `razo` (adjacent, same beach system)
- Malpica / Area Maior / Seaia → `razo` (~10 km west)
- Soesto / Traba → `razo` (~25 km west; flag as "approximate proxy")
- Nemiña / Lires / O Rostro → `razo` (far-west, 80–100 km; flag prominently as "rough proxy — local conditions may diverge")
- Lariño → `larino` (direct)
- Orzán / Matadeiro / Riazor → `caion` (~8 km, NW-facing open coast — apply Orzán's specific tide and exposure rules)

**Ría:**
- Bastiagueiro → `bastiagueiro` (direct)
- Boi de Canto → `bastiagueiro` (~1 km, same ría conditions)
- Santa Cristina → `bastiagueiro`
- Perbes → `bastiagueiro` (Ría de Betanzos, similar wrap window — but use guide's high-threshold rules)
- Pedrido / Ondalonga → `bastiagueiro` (very rare wave; lean on guide's threshold rules)

**Ferrolterra:**
- Doniños → `doninos` (direct)
- San Xurxo → `doninos` (~7 km south, same Ferrolterra exposure; differentiate via guide's per-spot rules — San Xurxo wants S wind primary, low tide, ≥2 m swell, while Doniños wants NE primary and is per-peak tide-dependent)
- Esmelle / A Fragata / Covas-O Vilar → `doninos` (~2–3 km cluster)
- Santa Comba → `doninos` (~5 km)
- Ponzos → `pantin` (~5 km)
- Campelo → `pantin` (~3 km)
- A Frouxeira / Lago / Meirás / Cristina / Percebeira → `pantin` (~2–3 km, same Valdoviño coast)
- Pantín → `pantin` (direct)
- Baleo → `pantin` (~5 km east)
- Vilarrube → `pantin` (~5 km north into Ría de Cedeira)

**Mariña Lucense:**
- Esteiro de Xove → `esteiro_xove` (direct, single-model wave — only MFWAM produces wave data, EWAM is null at this grid cell. Auto ●○○ confidence per Step 4. ~150 km from Sada — day-mission distance.)

#### On surfacing less-familiar spots

The user has explicitly asked to expand range. Don't default to whichever spots they've surfed most. Surface a less-surfed-but-suitable option in the C slot when conditions warrant — Soesto, Lariño, Boi de Canto, Esmelle, Vilarrube, Sabón Dique on a clean NE day. The proxy map makes these accessible from summary data; use them.

#### Board selection

Spain quiver only:
- **6'6"** (35.6 L round-tail thruster) — performance shortboard for clean head-high days
- **6'0"** (38.2 L 5-box squash) — wider, more forgiving; small clean is its sweet spot
- **6'10"** (45.6 L round-tail thruster) — step-up for proper size and longer-period faster waves

Reason from conditions, not labels. Don't reach for the 6'10" unless the summary's wave-height mean lands at head-high+ (≈1.5 m model height ≈ chest-to-head-high breaking on exposed beach). Don't reach for the 6'6" on a 2 ft mushy small-clean day — the 6'0" is the right call.

#### Badge calibration

Same values as `daily-surf-briefing`: `GO — DAWN PATROL`, `GO`, `MARGINAL`, `SKIP`.

The auto-downgrade rule is now driven by model agreement directly, not heuristics:

- **All ●●● picks** → no downgrade. Multi-model agreement is a positive confidence signal, not just absence of flags.
- **Leading pick rated ●●○** → no auto-downgrade by default. Flag the uncertain variable in the footnote.
- **Leading pick rated ●○○** → auto-downgrade by one notch. Cite the disagreeing variable and which models disagreed (or, for Esteiro de Xove, cite the structural single-model limitation).

The downgrade applies AFTER the leading pick is selected on conditions (Step 6). Do NOT swap the leading pick to a higher-agreement spot just to keep the badge color — see "Order of operations" in Step 4.

The "small but glassy" rule still applies — light wind plus tiny swell is MARGINAL, not GO, regardless of agreement.

The triangulation-required heuristics from `daily-surf-briefing` (threshold-sensitive call, day 5+, active synoptic pattern) are now obsolete — they were proxies for "models might disagree." Now the summary measures disagreement directly and exposes it as a label.

### Step 8 — Render the visualization

Same card structure and visual tokens as `daily-surf-briefing` Step 5. Single mandatory output per skill run. Path priority:

1. `visualize:show_widget` (preferred)
2. HTML at `/mnt/user-data/outputs/{YYYY-MM-DD}_briefing.html` + `present_files`
3. Tight prose card if neither widget nor file output is available

#### Card structure — what's different versus `daily-surf-briefing`

Identical card shape (header / TL;DR / 2×2 conditions / timing / picks / footer / footnote). Three additions:

1. **Agreement dot indicator** on each spot pick — `●●●`, `●●○`, or `●○○` — placed at the right of the spot tile, alongside the existing tag (`primary`, `backup`, etc.). Use light-gray dots for neutral, amber for ●○○. Read directly from the summary's `agreement` labels per Step 4.

2. **Conditions tile spread display.** When the relevant `agreement` label reads `"low"`, show the spread instead of a single number:
   - Agree (label `"high"` or `"medium"`): `1.0 m / 3 ft` with sub-line `<n> models agree` where `<n>` = `len(models_used)`
   - Disagree (label `"low"`): `~1.0 m ±0.2 m / ~3 ft ±0.5 ft` (use mean and spread/2 for the band) with sub-line `<n>-model spread`. Or render as `(mean − spread/2) – (mean + spread/2)` if you prefer an explicit range. The summary doesn't emit min/max, but mean ± spread/2 is a sufficient approximation.
   - Single-model (label `"single_model"`): show the single value with sub-line `single model — <model name>` from `waves.models_used[0]`.

3. **Footnote** replaces the sub-coast pull statement with multi-model summary. Required content:
    - **Bundle age.** Compute as `now_utc − source_bundle_at` (NOT `generated_at` — that's when the summary script ran; the underlying forecast freshness is `source_bundle_at`). **Both timestamps are UTC** — convert the system clock to UTC before subtracting (Madrid is UTC+1/+2; NY is UTC−4/−5). Reading the system clock as if it were UTC will overestimate the age by the timezone offset, producing wrong values like "12h old" when the bundle is actually 4h old. Express in the freshest accurate unit: `Xm ago` if <1h, `Xh ago` if <24h, `Xd ago` otherwise. Format: `Bundle gen 2026-05-06 19:39 UTC · 3h ago`. Sanity check: the cron runs twice daily, so a healthy bundle is 0–12h old. If your computed age is ≥24h, recheck your arithmetic before writing it — that age implies cron failure and you should already be falling back to `daily-surf-briefing`. Do not confuse bundle age with the offset between today and the briefing day — a bundle generated today at 19:39 UTC for a Thursday briefing is a few hours old, not "24h old", regardless of which day Thursday is.
    - **Models that returned valid data per spot** — read from `data_quality.n_models_waves` and the per-window `models_used`/`models_dropped`. Cite GFS Wave gaps and Esteiro's EWAM-null structural limitation explicitly when they affect leading picks.
    - **Agreement summary** — which agreement labels read `"low"` for the leading pick, on which variable, and the spread value.
    - **Tide source** — from summary if present; else `Wisuki tide fallback (summary didn't include tide)`.
    - **Galicia guide status** — `guide v[date] applied per-spot` or `guide unavailable`.
    - **Forecast horizon caveat** scales with day. Day offsets are counted from today's local date in Europe/Madrid — `Day +0` = today, `Day +1` = tomorrow, etc. The bundle's horizon is `forecast_days = 7`, so days +0 through +6 are addressable.
       - Day +0 (today): no caveat needed.
       - Day +1 (tomorrow): no caveat needed.
       - Days +2 through +4: ±15–20% on wave height; ±10° on wind direction.
       - Days +5 through +6: ±25–30%, plus a synoptic-uncertainty flag — at this range the model can be reading "this storm forms" rather than "this storm exists." Recommend a re-check the day before.

The `Less coverage / look at` footer line still applies — name 1–2 less-covered or less-modeled spots that may still work if conditions on arrival differ from forecast. The proxy map gives access to many such spots without an extra fetch.

### Step 9 — Prose backup

Same template as `daily-surf-briefing` Step 6. Add one extra line in the data note: the model-agreement summary (e.g. "EWAM and MeteoFrance agree within 10 cm; ICON-EU and ECMWF IFS agree on wind, GFS seamless reads 4 kts lower — the summary's mean averages all three equally, so trust ICON-EU+ECMWF for cape-spot direction"). Read agreement labels from the summary; do not recompute spreads in your head.

## What this skill does NOT do

- Doesn't recommend trips, charge sessions, or push marginal conditions.
- Doesn't analyze the surf log — separate question type.
- Doesn't answer technique or fitness questions.
- Doesn't cover NY, The Wave Bristol, or trip locations — Galicia only.
- Doesn't run when the summary is stale or unavailable — falls back to `daily-surf-briefing`.
- Doesn't pretend GFS Wave's all-zero arrays are "flat ocean" — they're no-data, and the summary already drops them per `_meta.gfswave_ok`.
- Doesn't pretend Esteiro de Xove has 3-model wave triangulation — it's structurally single-model (MFWAM only). Flag confidence accordingly.
- Doesn't apply bias correction in V1. Per-spot, per-season biases (e.g. "GFS Wave overforecasts Pantín by 15%") become available when the archive directory has months of data and the user has logged felt-vs-forecast sessions. V2 scope.
- **Doesn't re-aggregate.** Do NOT average across models, recompute spreads, slice hourly arrays for window aggregates, or convert km/h → kt at calculation time. The summary file did all of that deterministically in Python. Read the pre-computed `mean`, `spread`, and `agreement` fields directly. Imperial conversion (m → ft, kt → km/h) happens at presentation time only.

## Edge cases

- **Summary URL changes** (user renames the repo): edit the URL constant near the top of this skill. The rest of the workflow is URL-agnostic.
- **Tide `null` for a spot** (Wisuki scrape failed or no Wisuki mapping): fetch tide from Wisuki tide page or tide-forecast.com instead. Note in footnote.
- **A wave model dropped at one spot** (already represented in `models_dropped` per window): use surviving models' mean (the summary already computed that). Note the gap in the footnote if it affects the leading pick.
- **All wave models return no usable data for a spot** (rare; `n_models_waves == 0`): the summary's wave block reads agreement labels of `"n/a"`. Degrade that spot's pick to low-confidence; do not give a confident size call.
- **Wind unavailable for a spot** (`data_quality.wind_ok == false`, rare): same — `wind.agreement` reads `"n/a"`, degrade the call.
- **User asks about a spot that proxies far** (e.g. Nemiña at ~80 km from Razo): include in picks if conditions clearly warrant but flag prominently as approximate proxy — local conditions may diverge meaningfully.
- **Esteiro de Xove single-model rating:** always ●○○ for waves regardless of forecast-day spread. This is structural (EWAM grid cell mask), not a daily forecast-quality issue. Note it that way in the footnote so the user understands it won't "improve" tomorrow.
- **Multi-day requests:** one card per day, each with its own agreement labels read from `days[date].windows[window]`. Forecast horizon caveat applies to days 2+ regardless of agreement quality.
- **Active synoptic pattern + day 2+** (formerly a triangulation-required case in `daily-surf-briefing`): now handled by the agreement labels directly. If models disagree on a fast-developing system, the spread is bigger and `agreement` will read `"medium"` or `"low"`. No separate heuristic needed.
- **Spot `tide.reference_station` is far from the spot** (e.g. Pantín tide referenced to Cedeira ~5 km away; Lariño from Muros ~10 km; Esteiro from Foz ~20 km): the timing offset is small enough to ignore for coarse windows. For tight tide windows, capture the offset and adjust by a few minutes if it matters.
- **First skill run on a brand-new repo:** the URL may 404 if no successful Actions run has happened yet. Fall back to `daily-surf-briefing` and tell the user once. After the first successful cron, this skill takes over.
- **Do NOT add a `?d=...` cache-buster.** Earlier versions of this skill appended one to defeat downstream caches. It was removed because claude.ai's `<sources_in_this_project>` permission layer uses exact-string URL matching — appending a query string fires `PERMISSIONS_ERROR` before the request reaches GitHub, even though the URL host+path matches. Freshness is enforced by reading `source_bundle_at` inside the JSON; that's unaffected by web_fetch's cache (which has a 5–15 min TTL — much smaller than the 24h staleness threshold).
- **Default `text_content_token_limit` truncates mid-document.** Always pass an explicit `text_content_token_limit=300000` (or higher) on the `web_fetch` call. Without this, the response is clamped after ~2–3 spots and the rest of the file is silently dropped — you won't see Lariño or Esteiro de Xove.
- **Specific-hour question:** drill into `hourly` arrays per Step 3, last bullet. The summary preserves 24-hour-per-day arrays so this works without re-fetching the raw bundle.

## Compaction rules

Same as `daily-surf-briefing`:

- Flat or blown out: still produce the full card with SKIP badge and three "if forced" picks.
- One sub-coast clearly better: lead from that sub-coast; don't artificially balance.
- Very similar to yesterday: still produce the full structure.
- Multi-day: one card per day, chronological, stacked.

## V2 hooks (not implemented in V1)

For future revision, after the archive has months of data and the user has been logging felt-vs-forecast sessions:

- **Bias correction layer.** Compute per-spot, per-season multiplicative bias factors from forecast-vs-reality history. Apply at briefing time. Note in footnote that the call is bias-corrected and which factor was applied. Implementation home: `compute_summary.py` could read a `bias_factors.json` and pre-apply, or apply at skill render time. Decide based on whether bias correction affects more than one consumer.
- **Pattern-recognition diagnostics.** When today's synoptic pattern matches an archived day, surface that day's actual outcome as a confidence anchor. Implementation home: separate script that joins `archive/` with the felt-conditions log.
- **Auto-spotting trend changes.** If a model has been systematically wrong at a spot for the last N days, flag the model as drifting and weight it less. Useful for catching seasonal sand-bar shifts that the model can't see. Implementation home: `compute_summary.py` could read trailing-N-day archive data, but this is invasive — start with a separate analysis script.
- **Felt-conditions logger.** Add a brief end-of-briefing prompt for the user to log how the session actually went, committed to a `felt_log.json` in the repo for V2's bias-correction loop.
