"""Compute per-spot, per-day, per-window forecast summary from today.json.

Reads the raw bundle, aggregates wave data across surviving models (per `_meta`
flags), aggregates wind across all 3 wind models, converts km/h to knots,
computes hourly arrays plus three time-window summaries per day, and emits
categorical agreement labels by comparing spread vs thresholds.

Stdlib only. Run after `fetch.py` in the same workflow step.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_SCHEMA_VERSION = 1

WINDOWS = {
    "morning": (6, 12),
    "afternoon": (12, 18),
    "full_day": (6, 20),
}

THRESHOLDS = {
    "wave_height_m": 0.3,
    "wave_height_pct": 25,
    "period_s": 2,
    "wave_direction_deg": 30,
    "wind_speed_kt": 5,
    "wind_direction_deg": 30,
}

WAVE_MODELS = ["ewam", "ncep_gfswave025", "meteofrance_wave"]
WAVE_MODEL_FLAGS = {
    "ewam": "ewam_ok",
    "ncep_gfswave025": "gfswave_ok",
    "meteofrance_wave": "mfwam_ok",
}

WIND_MODELS = ["best_match", "ecmwf_ifs025", "gfs_seamless"]


def kmh_to_kt(v):
    if v is None:
        return None
    return v / 1.852


def circular_mean(degs):
    """Mean of bearings in degrees via atan2(sum sin, sum cos). Returns None if empty."""
    valid = [d for d in degs if d is not None]
    if not valid:
        return None
    rads = [math.radians(d) for d in valid]
    sin_sum = sum(math.sin(r) for r in rads)
    cos_sum = sum(math.cos(r) for r in rads)
    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return None
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360


def angular_distance(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def circular_spread(degs):
    """Max angular distance from circular mean; capped at 180."""
    valid = [d for d in degs if d is not None]
    if len(valid) < 2:
        return 0.0 if valid else None
    cm = circular_mean(valid)
    if cm is None:
        return None
    return min(180.0, max(angular_distance(d, cm) for d in valid))


def aggregate_hourly_linear(arrays):
    """Element-wise mean and max-min spread across model arrays.

    Zeros are kept; only None is excluded. Models are pre-filtered by the caller
    via _meta flags, so a real zero (dead-flat wind) is never silently dropped.
    """
    if not arrays:
        return {"mean": [], "spread": []}
    n = len(arrays[0])
    means, spreads = [], []
    for i in range(n):
        vals = [a[i] for a in arrays if i < len(a) and a[i] is not None]
        if not vals:
            means.append(None)
            spreads.append(None)
        elif len(vals) == 1:
            means.append(vals[0])
            spreads.append(0.0)
        else:
            means.append(sum(vals) / len(vals))
            spreads.append(max(vals) - min(vals))
    return {"mean": means, "spread": spreads}


def aggregate_hourly_circular(arrays):
    """Element-wise circular mean and angular spread across model arrays."""
    if not arrays:
        return {"mean": [], "spread": []}
    n = len(arrays[0])
    means, spreads = [], []
    for i in range(n):
        vals = [a[i] for a in arrays if i < len(a) and a[i] is not None]
        if not vals:
            means.append(None)
            spreads.append(None)
        elif len(vals) == 1:
            means.append(vals[0])
            spreads.append(0.0)
        else:
            means.append(circular_mean(vals))
            spreads.append(circular_spread(vals))
    return {"mean": means, "spread": spreads}


def aggregate_window_linear(hourly_field, indices):
    """Mean of hourly means within window; spread = max-min of those hourly means.

    Returns (mean, spread, n_valid). n_valid is the count of non-None hourly means
    inside the window.
    """
    means = [hourly_field["mean"][i] for i in indices if hourly_field["mean"][i] is not None]
    if not means:
        return None, None, 0
    if len(means) == 1:
        return means[0], 0.0, 1
    return sum(means) / len(means), max(means) - min(means), len(means)


def aggregate_window_circular(hourly_field, indices):
    """Circular mean and spread over hourly means within window."""
    vals = [hourly_field["mean"][i] for i in indices if hourly_field["mean"][i] is not None]
    if not vals:
        return None, None, 0
    if len(vals) == 1:
        return vals[0], 0.0, 1
    return circular_mean(vals), circular_spread(vals), len(vals)


def agreement_label(spread, threshold, n_models, mean_value=None, pct_threshold=None):
    """Categorical agreement label.

    - "n/a" if no models contributed or spread is None
    - "single_model" if only one model contributed (no triangulation)
    - "low" if spread > threshold OR (mean given and pct spread > pct_threshold)
    - "medium" if spread > 0.5 * threshold
    - "high" otherwise
    """
    if n_models == 0 or spread is None:
        return "n/a"
    if n_models == 1:
        return "single_model"
    over_abs = spread > threshold
    over_pct = (
        pct_threshold is not None
        and mean_value is not None
        and mean_value > 0
        and (spread / mean_value * 100) > pct_threshold
    )
    if over_abs or over_pct:
        return "low"
    if spread > 0.5 * threshold:
        return "medium"
    return "high"


def slice_day(time_array, target_date_iso):
    """Indices in time_array whose date prefix matches target_date_iso (YYYY-MM-DD).

    Bundle requests `timezone=Europe/Madrid`, so timestamps are local-naive ISO
    strings like "2026-05-07T00:00". A startswith match is sufficient.
    """
    return [i for i, t in enumerate(time_array) if t.startswith(target_date_iso)]


def parse_hour(time_str):
    return int(time_str[11:13])


def select_wave_models(spot_meta):
    return [m for m in WAVE_MODELS if spot_meta.get(WAVE_MODEL_FLAGS[m], False)]


def get_model_array(hourly, field, model):
    return hourly.get(f"{field}_{model}")


def yyyy_mm_dd_to_dd_mm_yyyy(s):
    return "/".join(reversed(s.split("-")))


def build_day_block(
    target_date,
    wave_time,
    wind_time,
    waves_hourly_linear,
    waves_hourly_circular,
    wind_hourly_linear,
    wind_hourly_circular,
    n_wave_models,
    n_wind_models,
    wave_models_used,
    tide_data,
):
    """Assemble the full {hourly, windows, tide} block for one date."""
    wave_indices = slice_day(wave_time, target_date) if wave_time else []
    wind_indices = slice_day(wind_time, target_date) if wind_time else []

    hourly = {"time": [], "waves": {}, "wind": {}}
    if wave_indices:
        hourly["time"] = [wave_time[i][11:16] for i in wave_indices]
    elif wind_indices:
        hourly["time"] = [wind_time[i][11:16] for i in wind_indices]

    # --- waves hourly subset ---
    wave_field_map_linear = (
        ("wave_height", "height_m"),
        ("wave_period", "period_s"),
        ("swell_wave_height", "swell_height_m"),
        ("swell_wave_period", "swell_period_s"),
    )
    for src_name, out_name in wave_field_map_linear:
        if src_name in waves_hourly_linear:
            src = waves_hourly_linear[src_name]
            hourly["waves"][out_name] = {
                "mean": [src["mean"][i] for i in wave_indices],
                "spread": [src["spread"][i] for i in wave_indices],
            }
    wave_field_map_circular = (
        ("wave_direction", "direction_deg"),
        ("swell_wave_direction", "swell_direction_deg"),
    )
    for src_name, out_name in wave_field_map_circular:
        if src_name in waves_hourly_circular:
            src = waves_hourly_circular[src_name]
            hourly["waves"][out_name] = {
                "mean": [src["mean"][i] for i in wave_indices],
                "spread": [src["spread"][i] for i in wave_indices],
            }

    # --- wind hourly subset ---
    for out_name in ("speed_kt", "gusts_kt"):
        if out_name in wind_hourly_linear:
            src = wind_hourly_linear[out_name]
            hourly["wind"][out_name] = {
                "mean": [src["mean"][i] for i in wind_indices],
                "spread": [src["spread"][i] for i in wind_indices],
            }
    if "direction_deg" in wind_hourly_circular:
        src = wind_hourly_circular["direction_deg"]
        hourly["wind"]["direction_deg"] = {
            "mean": [src["mean"][i] for i in wind_indices],
            "spread": [src["spread"][i] for i in wind_indices],
        }

    # --- per-window aggregates ---
    windows_block = {}
    for window_name, (start_h, end_h) in WINDOWS.items():
        wave_window_idx = [i for i in wave_indices if start_h <= parse_hour(wave_time[i]) < end_h]
        wind_window_idx = [i for i in wind_indices if start_h <= parse_hour(wind_time[i]) < end_h]

        # waves block
        waves_block = None
        if n_wave_models > 0:
            waves_block = {}
            if "wave_height" in waves_hourly_linear:
                m, s, _ = aggregate_window_linear(waves_hourly_linear["wave_height"], wave_window_idx)
                waves_block["height_m"] = {"mean": m, "spread": s}
            if "wave_period" in waves_hourly_linear:
                m, s, _ = aggregate_window_linear(waves_hourly_linear["wave_period"], wave_window_idx)
                waves_block["period_s"] = {"mean": m, "spread": s}
            if "wave_direction" in waves_hourly_circular:
                m, s, _ = aggregate_window_circular(waves_hourly_circular["wave_direction"], wave_window_idx)
                waves_block["direction_deg"] = {"mean_circular": m, "spread": s}
            if "swell_wave_height" in waves_hourly_linear:
                m, s, _ = aggregate_window_linear(waves_hourly_linear["swell_wave_height"], wave_window_idx)
                waves_block["swell_height_m"] = {"mean": m, "spread": s}
            if "swell_wave_period" in waves_hourly_linear:
                m, s, _ = aggregate_window_linear(waves_hourly_linear["swell_wave_period"], wave_window_idx)
                waves_block["swell_period_s"] = {"mean": m, "spread": s}
            if "swell_wave_direction" in waves_hourly_circular:
                m, s, _ = aggregate_window_circular(waves_hourly_circular["swell_wave_direction"], wave_window_idx)
                waves_block["swell_direction_deg"] = {"mean_circular": m, "spread": s}

            hgt = waves_block.get("height_m", {})
            per = waves_block.get("period_s", {})
            dir_w = waves_block.get("direction_deg", {})
            waves_block["agreement"] = {
                "height": agreement_label(
                    hgt.get("spread"),
                    THRESHOLDS["wave_height_m"],
                    n_wave_models,
                    mean_value=hgt.get("mean"),
                    pct_threshold=THRESHOLDS["wave_height_pct"],
                ),
                "period": agreement_label(per.get("spread"), THRESHOLDS["period_s"], n_wave_models),
                "direction": agreement_label(dir_w.get("spread"), THRESHOLDS["wave_direction_deg"], n_wave_models),
            }
            waves_block["models_used"] = wave_models_used
            waves_block["models_dropped"] = [m for m in WAVE_MODELS if m not in wave_models_used]
            waves_block["single_model"] = (n_wave_models == 1)

        # wind block
        wind_block = None
        if n_wind_models > 0:
            wind_block = {}
            if "speed_kt" in wind_hourly_linear:
                m, s, _ = aggregate_window_linear(wind_hourly_linear["speed_kt"], wind_window_idx)
                wind_block["speed_kt"] = {"mean": m, "spread": s}
            if "direction_deg" in wind_hourly_circular:
                m, s, _ = aggregate_window_circular(wind_hourly_circular["direction_deg"], wind_window_idx)
                wind_block["direction_deg"] = {"mean_circular": m, "spread": s}
            if "gusts_kt" in wind_hourly_linear:
                m, s, _ = aggregate_window_linear(wind_hourly_linear["gusts_kt"], wind_window_idx)
                wind_block["gusts_kt"] = {"mean": m, "spread": s}

            ws = wind_block.get("speed_kt", {})
            wd = wind_block.get("direction_deg", {})
            wind_block["agreement"] = {
                "speed": agreement_label(ws.get("spread"), THRESHOLDS["wind_speed_kt"], n_wind_models),
                "direction": agreement_label(wd.get("spread"), THRESHOLDS["wind_direction_deg"], n_wind_models),
            }
            wind_block["models_used"] = WIND_MODELS

        n_hours = max(len(wave_window_idx), len(wind_window_idx))
        windows_block[window_name] = {"waves": waves_block, "wind": wind_block, "n_hours": n_hours}

    # --- tide for the day ---
    tide_for_day = None
    if isinstance(tide_data, list):
        wanted = yyyy_mm_dd_to_dd_mm_yyyy(target_date)
        for t in tide_data:
            if t.get("date") == wanted:
                tide_for_day = {
                    "reference_station": t.get("reference_station"),
                    "events": [
                        {
                            "type": e.get("type"),
                            "time_local": e.get("time"),
                            "height_m": e.get("height_m"),
                            "coefficient": e.get("coefficient"),
                        }
                        for e in t.get("tides", [])
                    ],
                }
                break

    return {"hourly": hourly, "windows": windows_block, "tide": tide_for_day}


def process_spot(name, spot):
    """Compute the per-spot summary."""
    meta = spot.get("_meta", {}) or {}
    waves_ok = meta.get("waves_ok", False)
    wind_ok = meta.get("wind_ok", False)

    wave_models_used = select_wave_models(meta) if waves_ok else []
    n_wave_models = len(wave_models_used)

    out = {
        "lat": spot.get("lat"),
        "lon": spot.get("lon"),
        "data_quality": {
            "ewam_ok": meta.get("ewam_ok", False),
            "gfswave_ok": meta.get("gfswave_ok", False),
            "mfwam_ok": meta.get("mfwam_ok", False),
            "wind_ok": wind_ok,
            "tide_ok": meta.get("tide_ok", False),
            "n_models_waves": n_wave_models,
        },
        "days": {},
    }

    # waves: build per-field hourly aggregates across surviving models
    waves_hourly_linear = {}
    waves_hourly_circular = {}
    waves_payload = spot.get("waves") or {}
    waves_hourly = waves_payload.get("hourly") if isinstance(waves_payload, dict) else None
    wave_time = []
    if waves_hourly and wave_models_used:
        wave_time = waves_hourly.get("time", [])
        for field in ("wave_height", "wave_period", "swell_wave_height", "swell_wave_period"):
            arrays = [get_model_array(waves_hourly, field, m) for m in wave_models_used]
            arrays = [a for a in arrays if a is not None]
            if arrays:
                waves_hourly_linear[field] = aggregate_hourly_linear(arrays)
        for field in ("wave_direction", "swell_wave_direction"):
            arrays = [get_model_array(waves_hourly, field, m) for m in wave_models_used]
            arrays = [a for a in arrays if a is not None]
            if arrays:
                waves_hourly_circular[field] = aggregate_hourly_circular(arrays)

    # wind: aggregate across all 3 models if wind_ok
    wind_hourly_linear = {}
    wind_hourly_circular = {}
    wind_payload = spot.get("wind") or {}
    wind_hourly = wind_payload.get("hourly") if isinstance(wind_payload, dict) else None
    wind_time = []
    n_wind_models = 0
    if wind_hourly and wind_ok:
        wind_time = wind_hourly.get("time", [])
        for raw, out_name in (("wind_speed_10m", "speed_kt"), ("wind_gusts_10m", "gusts_kt")):
            arrays = [get_model_array(wind_hourly, raw, m) for m in WIND_MODELS]
            arrays = [a for a in arrays if a is not None]
            if arrays:
                converted = [[kmh_to_kt(v) for v in a] for a in arrays]
                wind_hourly_linear[out_name] = aggregate_hourly_linear(converted)
        dir_arrays = [get_model_array(wind_hourly, "wind_direction_10m", m) for m in WIND_MODELS]
        dir_arrays = [a for a in dir_arrays if a is not None]
        if dir_arrays:
            wind_hourly_circular["direction_deg"] = aggregate_hourly_circular(dir_arrays)
        # n_wind_models = number of model arrays that contributed (use speed as proxy)
        n_wind_models = sum(
            1 for m in WIND_MODELS if get_model_array(wind_hourly, "wind_speed_10m", m) is not None
        )

    # day enumeration: use whichever time array is available
    time_array = wave_time or wind_time
    dates_seen = []
    for t in time_array:
        d = t[:10]
        if d not in dates_seen:
            dates_seen.append(d)

    tide_data = spot.get("tide") if isinstance(spot.get("tide"), list) else []

    for date_iso in dates_seen[:3]:
        out["days"][date_iso] = build_day_block(
            date_iso,
            wave_time,
            wind_time,
            waves_hourly_linear,
            waves_hourly_circular,
            wind_hourly_linear,
            wind_hourly_circular,
            n_wave_models,
            n_wind_models,
            wave_models_used,
            tide_data,
        )

    return out


def main():
    ap = argparse.ArgumentParser(description="Compute forecast summary from today.json")
    ap.add_argument("--bundle", default="today.json", help="Path to source bundle")
    ap.add_argument("--out", default="today_summary.json", help="Path to output summary")
    ap.add_argument("--no-archive", action="store_true", help="Skip writing archive_summary/<date>.json")
    args = ap.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))

    summary = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_bundle_at": bundle.get("generated_at"),
        "windows": {
            "morning": "06:00-12:00",
            "afternoon": "12:00-18:00",
            "full_day": "06:00-20:00",
        },
        "thresholds": THRESHOLDS,
        "spots": {},
    }

    for name, spot in bundle.get("spots", {}).items():
        summary["spots"][name] = process_spot(name, spot)

    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not args.no_archive:
        archive_dir = Path("archive_summary")
        archive_dir.mkdir(exist_ok=True)
        date_str = datetime.now(timezone.utc).date().isoformat()
        (archive_dir / f"{date_str}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

    n_spots = len(summary["spots"])
    n_waves = sum(1 for s in summary["spots"].values() if s["data_quality"]["n_models_waves"] > 0)
    n_wind = sum(1 for s in summary["spots"].values() if s["data_quality"]["wind_ok"])
    print(f"Wrote {args.out}: {n_spots} spots ({n_waves} with wave data, {n_wind} with wind)")
    for name, s in summary["spots"].items():
        dq = s["data_quality"]
        print(
            f"  {name}: n_models_waves={dq['n_models_waves']}, "
            f"wind_ok={dq['wind_ok']}, tide_ok={dq['tide_ok']}"
        )


if __name__ == "__main__":
    main()
