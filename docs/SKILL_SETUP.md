# Skill setup — `multi-model-surf-briefing` in claude.ai

One-time setup so the skill can fetch its data sources without prompting.

## 1. Add the URLs to your project's allowed sources

In claude.ai, open your Galicia surf project → custom instructions → find the `<sources_in_this_project>` block. Add (or replace the existing forecast-bundle entry with) these two URLs:

**Primary (required):**
```
https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json
```

**Tier 1.5 fallback (recommended):**
```
https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json
```

Without the primary URL in project sources, claude.ai's `web_fetch` returns `PERMISSIONS_ERROR` on every fresh session and the skill falls back to the raw bundle (Tier 1.5) — slightly less reliable. With both URLs in sources, the primary path works directly.

A clean copy-pasteable form for the `<sources_in_this_project>` block (replace the old `today.json` line):

> - **Forecast summary** — `https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today_summary.json`. Pre-computed per-spot, per-day, per-window aggregates with model-agreement labels. **Read this; do not re-aggregate.** The raw bundle (`https://raw.githubusercontent.com/RomanVazquezL/galicia-surf-forecast/main/today.json`, same repo) is a Tier 1.5 fallback for ad-hoc inspection or when the summary is unreachable.

## 2. Add the reading-protocol step to `<reasoning_protocol>`

Same file, find the `<reasoning_protocol>` block. Insert this between current steps 3 and 4:

> For Galicia forecast questions: pull the **forecast summary** and read the pre-computed `mean`, `spread`, and `agreement` fields directly. Do not average across models, recompute spreads, or convert km/h → kt in your head — the summary has already done the deterministic work in metric units. Imperial conversion happens at presentation time per `<input_conventions>`.

## 3. Verify

Start a **fresh chat** in this project (a fresh chat is required because URL provenance is per-session). Run the skill:

```
/multi-model-surf-briefing
run the briefing for tomorrow
```

If the briefing card appears with no setup-required line in the footnote, you're set. If you see `Multi-model summary needs one-time setup. Add ... to <sources_in_this_project>`, the URL didn't take — re-check step 1, save again in claude.ai, and start another fresh chat.

## What each URL is for

| URL | Purpose | Size |
|---|---|---|
| `today_summary.json` | Primary — pre-computed window aggregates with agreement labels | ~110–150 KB |
| `today.json` | Tier 1.5 fallback — raw multi-model bundle, skill aggregates inline | ~150–250 KB (slim) |

Both are committed twice daily by GitHub Actions cron (05:27 and 13:47 UTC). Both have a `?d={YYYY-MM-DD}` cache-buster appended by the skill at fetch time so downstream caches don't serve stale copies.

If you rename the repo, edit the URL constants at the top of `skills/multi-model-surf-briefing/SKILL.md` and re-paste both into your project sources here.
