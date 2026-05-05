import requests, json, datetime, pathlib

SPOTS = {
    "pantin":       (43.6413, -8.1137),
    "doninos":      (43.5183, -8.3367),
    "razo":         (43.2917, -8.7950),
    "bastiagueiro": (43.3483, -8.3000),
    "san_xurxo":    (43.5217, -8.3433),
    "caion":        (43.3151, -8.6101),
}

WAVE_MODELS = "ecmwf_wam,gfs_wave025,dwd_ewam,meteofrance_wave"
WIND_MODELS = "best_match,ecmwf_ifs025,gfs_seamless"

bundle = {
    "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "spots": {},
}

for name, (lat, lon) in SPOTS.items():
    try:
        waves = requests.get("https://marine-api.open-meteo.com/v1/marine", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_direction,wave_period,"
                      "swell_wave_height,swell_wave_direction,swell_wave_period",
            "models": WAVE_MODELS,
            "timezone": "Europe/Madrid",
            "forecast_days": 3,
        }, timeout=30).json()
    except Exception as e:
        waves = {"error": str(e)}

    try:
        wind = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "models": WIND_MODELS,
            "timezone": "Europe/Madrid",
            "forecast_days": 3,
        }, timeout=30).json()
    except Exception as e:
        wind = {"error": str(e)}

    bundle["spots"][name] = {"lat": lat, "lon": lon, "waves": waves, "wind": wind}

pathlib.Path("today.json").write_text(json.dumps(bundle, indent=2))
date_str = datetime.date.today().isoformat()
pathlib.Path("archive").mkdir(exist_ok=True)
pathlib.Path(f"archive/{date_str}.json").write_text(json.dumps(bundle, indent=2))
print(f"Wrote forecast for {len(bundle['spots'])} spots")
