# Product Requirements Document — Galicia Surf Decision Engine

> **Scope of this document.** This is the broader product vision for the Galicia Surf Decision Engine. **This repository (`galicia-surf-forecast`) implements FR1 (forecast ingestion) only.** Other functional requirements live in separate components — the consuming skill (`multi-model-surf-briefing`) is hosted in claude.ai; the knowledge base lives partly in claude.ai project files and partly in this repo's future `spots.json`; the UI doesn't yet exist. See the Components section below for the current architecture and where each FR lives today.

## Vision

A surf decision-support product that centralizes fragmented local Galician surf knowledge, fuses it with live forecast data, and personalizes the call to the user's level, build, quiver, and goals.

The user moment it serves: the surfer at 6 AM with three forecasting websites open, trying to decide where (and whether) to drive.

## Audience evolution

- **V1 (MVP):** Founder, in Galicia. Single user. No login, no public deployment.
- **V2:** Galicia-based surfers with similar profiles — intermediate, board-aware, willing to drive 30–60 min for a better call. Approximate persona size: low thousands across A Coruña + Ferrolterra.
- **V3+:** Other regions with the same structural gap — strong local blog/forum culture, weak integrated forecasting (Asturias, Cantabria, Basque Country, Northern Portugal, Morocco).

## MVP scope

Galicia only (A Coruña + Ferrolterra core spot set as defined in the v2 Surf Spot Guide), 72-hour outlook, web-only, founder is the only user. Recommendation unit is **spot-area** with named spots surfaced inside.

### Non-goals (MVP)
Multi-user accounts, billing, native mobile app, real-time community features, computer vision on cams, coverage outside Galicia.

## Current state

Where each component stands today:

| Component | Status | Location |
|---|---|---|
| Data pipeline (FR1) | **Built and running daily** | This repo (`galicia-surf-forecast`); bundle published at `raw.githubusercontent.com/.../today.json` |
| Multi-model briefing logic (FR2) | **V1 prototype as a Claude skill** | `multi-model-surf-briefing` skill in claude.ai |
| Per-spot knowledge base (FR3) | **Narrative version exists; structured version pending** | Galicia Surf Spot Guide v2 in claude.ai project files; future `spots.json` will live in this repo |
| Daily recommendation UI (FR4) | **Not built** | TBD — likely separate frontend repo |
| Personalization (FR5) | **Hardcoded in skill** | Founder profile in claude.ai project instructions |
| Session logging (FR6) | **Partial — Strava CSV exists** | `surfing_activities.csv` in claude.ai project files |

## Strategic positioning

The current Galician surf-decision workflow is fragmented across four layers, all stitched manually:

1. **Forecast numbers** — Surfline, Windy, Surf-Forecast, Open-Meteo
2. **Spot-specific knowledge** — Namarea, Surfmarket, Mar Gruesa, Costadasondas
3. **Visual confirmation** — Camaramar webcams
4. **Personal judgment** — fit to level, board, time budget

Each source is good in isolation; the integration is manual and lives in the surfer's head. Surfers cope by building intuition over years.

**The wedge is integration:** pulling forecast inputs, spot-specific knowledge, and personalization into a single decision view that does the synthesis the surfer currently does manually.

**What this product is NOT trying to beat:**
- **Surfline** is the ceiling for raw forecast accuracy. Don't compete on numerics.
- **Local blogs** are the depth source for spot-specific knowledge. Don't replace them; cite them.

**The defensible position long-term** is the integration layer plus a session-log corpus that compounds across users — in regions Surfline treats shallowly and that no single local blog covers across the full coast.

## Components & data flow

```
        ┌────────────────────────────────────────────────┐
        │  Forecast sources (Open-Meteo, Wisuki)         │
        └────────────────────┬───────────────────────────┘
                             │
                  GitHub Actions cron (2×/day)
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  THIS REPO — galicia-surf-forecast (FR1)       │
        │  scripts/fetch.py → today.json + archive/      │
        └────────────────────┬───────────────────────────┘
                             │
                  raw.githubusercontent.com
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  CLAUDE SKILL — multi-model-surf-briefing(FR2) │
        │  Reads bundle, applies guide rules,            │
        │  picks spots, renders mobile card              │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
                  ┌────────────────────┐
                  │  Founder (V1 user) │
                  └────────────────────┘

        Future (FR4): daily recommendation UI replaces or
        augments the skill output for non-Claude.ai access.
```

## Functional requirements

### FR1 — Forecast ingestion
The system pulls 72h forecast data (wave height, period, peak direction, wind speed/direction, tide curve) for every spot-area in scope, refreshed daily.

- **Design decision:** Multi-model bundle refreshed via scheduled job — three independent wave models (DWD EWAM, NCEP GFS Wave, MeteoFrance Wave) and three wind models (best_match/ICON-EU, ECMWF IFS025, GFS seamless), plus tides scraped from Wisuki. Output is one `today.json` file plus archived per-day copies.
- **Open question:** Buoy-to-spot mapping for V2/V3 — which buoys (Cabo Vilán-Sisargas, Cabo Silleiro, Estaca de Bares, Leixões as backup) are authoritative for which spot-areas, and how that generalizes to other coasts.
- **Acceptance:** Each spot-area has a fresh forecast bundle no older than 24h.

### FR2 — Per-spot-area surf interpretation
The system converts raw forecast inputs into a per-spot-area surfability read, with named spots inside each area ranked by fit for the day.

- **Design decision:** Deterministic preprocessing layer (wind-vs-orientation, tide window, period band) feeds an LLM judgment layer (per-spot quirks, refraction, seasonal biases). Boundary documented and revisable as models improve.
- **Design decision (V1):** Implemented as a Claude skill that consumes the FR1 bundle. V2 may move logic into a hosted backend.
- **Open question:** How to surface confidence — when the deterministic and judgment layers agree, the call is high-confidence; when they disagree, the system says so rather than picking arbitrarily.
- **Acceptance:** For each spot-area, the system returns overall outlook (green/yellow/red), top 1–3 named spots inside the area with one-line reasoning, and what would change the call.

### FR3 — Per-spot-area knowledge base
The system maintains a structured + narrative knowledge base per spot-area and per named spot, populated from web research and refinable over time.

- **Design decision:** Schema combines machine-structured fields (ideal swell direction/size/period range, wind preference vector, tide windows, hazards, board-fit hints, confidence per field) with human-language nuance kept as a narrative block the LLM consumes alongside the structured fields. The v2 Surf Spot Guide is the prototype of this hybrid.
- **Design decision:** Storage — markdown + JSON in repo for MVP, versioned with git. Reconsider when the corpus or contributor count grows.
- **Open question:** Deep-research automation pipeline for adding new spot-areas — prompt + tool design that produces both the structured fields and the narrative block in one pass with confidence labels per field.
- **Open question:** Attribution and trust — when knowledge comes from a specific local blog, the source is preserved and surfaced in the UI rather than absorbed silently.
- **Acceptance:** Adding a new spot-area is a documented workflow that produces both structured + narrative outputs; founder can complete it in <2 hours per spot-area.

### FR4 — Daily recommendation UI
The system exposes a clean, mobile-friendly daily decision view.

- **Primary user story:** "I'm in Sada, I have 8–10am tomorrow, I have a shortboard and a longboard. Show me the morning outlook across my reachable spot-areas, ranked by fit, with the named spots inside each."
- **Design decision:** Spot-area as the top-level unit of the UI; named spots are progressive disclosure inside each area card.
- **Design decision:** Stack — static frontend + scheduled job refreshing forecast bundles + lightweight serverless backend for personalization. Hosted cheaply (Vercel / Cloudflare Pages / similar).
- **Open question:** Whether the V1 UI is a separate web app, or whether the claude.ai skill remains the primary interface for V1 (with the dedicated UI deferred to V2 alongside multi-user).
- **Acceptance:** From cold page load, the founder can answer the user story above in <30 seconds.

### FR5 — Personalization
Recommendations are conditioned on the user profile (level, build, quiver, wetsuit, goals, risk posture, location, time budget).

- **MVP simplification:** Founder profile is hardcoded in claude.ai project instructions. No login, no multi-user.
- **V2 design decision:** Lightweight profile capture for additional users — minimal fields up front, enriched over time.
- **Open question:** How to keep recommendations flexible to one-off context the user hasn't volunteered (borrowed board, willing to drive farther today, recovery day) — likely a per-session prompt at the top of the UI rather than rigid stored preferences.

### FR6 — Session logging (deferred schema, immediate capture)
The system captures founder session logs from day one to seed the long-term spot-knowledge corpus, even before the schema and weighting model are fully designed.

- **MVP simplification:** Ingest existing Strava exports (already in project) plus simple manual or voice-memo log per session. Store raw; defer normalization.
- **Design decision (deferred to V2):** Reconciliation model when multiple users log the same spot on the same day with conflicting reads — trust weighting (locals vs. visitors), confidence intervals, integration with the knowledge base.
- **Open question (deferred to V3):** How session-log signal updates the knowledge base over time — does the LLM read raw logs, or is there an aggregation layer that produces structured updates?
- **Acceptance:** Every founder session is captured in a queryable form; no requirement yet that the logs influence recommendations.

## Future scope (explicitly post-MVP)

- LLM-generated natural-language forecast description vs. user voice memo, as a forecast-accuracy feedback signal.
- Multi-user accounts and lightweight community features (live session feed, "who's out where now").
- Per-spot local-expert reputation system, seeded by deep research and curated interviews.
- Cam integration where free feeds exist (Camaramar already public).
- New regions (Asturias, Cantabria, Northern Portugal, Morocco) — each gated on the new-region workflow being mature in Galicia.

## Success metrics

### V1 (founder use, 0–6 months)
- Founder uses the tool for >80% of surf-decision moments in Galicia over a 3-month window.
- Founder reports the tool changed their spot pick (vs. their default) ≥1×/week and was right more often than wrong.
- ≥10 spot-areas with full structured + narrative knowledge base entries.
- Adding a new spot-area takes <2 hours of human time end-to-end.

### V2 (other Galicia surfers, 6–18 months)
- ≥20 weekly active users in Galicia, retained week-over-week.
- Qualitative: at least 5 users report the tool replaced their previous workflow of stitching together Namarea + Surfmarket + Surfline.
- Session-log corpus has data from >5 distinct users on >3 spot-areas.

## Glossary

- **Spot-area** — A geographic cluster of named surf spots that share forecast inputs and broad wind/tide/swell windows (e.g. "Costa da Morte west" containing Razo, Baldaio, Malpica). The recommendation unit in the UI.
- **Named spot** — A specific break inside a spot-area (e.g. Razo's "Cordobés" peak). Surfaced as progressive disclosure inside the spot-area card.
- **Bundle** — The daily JSON file produced by FR1 containing forecast data for every monitored spot.
- **Knowledge base** — The structured + narrative per-spot information that the interpretation layer (FR2) consumes alongside the bundle.
- **Cape spot** — A surf spot near a headland (e.g. Pantín, Doniños, San Xurxo near Cabo Prior; San Xurxo is not currently in the bundle) where wind direction/strength can differ meaningfully from coarse model output. Higher-resolution wind models matter more here.
- **Deterministic preprocessing** — Code that turns numeric forecast inputs into binary or categorical signals (wind-offshore? tide-in-window? size-in-range?) before they reach the LLM judgment layer.
