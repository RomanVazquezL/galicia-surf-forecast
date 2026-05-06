import requests, json, datetime, pathlib, re, time
from bs4 import BeautifulSoup

# ─── Spots ─────────────────────────────────────────────────────────────
SPOTS = {
    "pantin":        (43.6413, -8.1137),
    "doninos":       (43.5183, -8.3367),
    "razo":          (43.2917, -8.7950),
    "bastiagueiro":  (43.3483, -8.3000),
    "caion":         (43.3151, -8.6101),
    "larino":        (42.7800, -9.1200),
    "esteiro_xove":  (43.6694, -7.5944),
}

WISUKI = {
    "pantin":       (7394, "pantn"),
    "doninos":      (2775, "donios"),
    "razo":         (2782, "razo"),
    "bastiagueiro": (6759, "bastiagueiro"),
    "caion":        (6767, "cain"),
    "larino":       (6078, "muros"),     # Muros tide station, ~10 km away
    "esteiro_xove": (6070, "foz"),       # Foz tide station, ~20 km west
}

WAVE_MODELS = "ewam,ncep_gfswave025,meteofrance_wave"
WIND_MODELS = "best_match,ecmwf_ifs025,gfs_seamless"

# ─── Wisuki tide scraper ───────────────────────────────────────────────
TIDE_RE = re.compile(r"([▼▲])\s*(\d{2}:\d{2})\s*([\d.]+)\s*m\s*(\d+)")

def fetch_wisuki_tides(wisuki_id, slug, n_days=7):
    url = f"https://wisuki.com/tide/{wisuki_id}/{slug}"
    html = requests.get(
        url, timeout=30,
        headers={"User-Agent": "surf-forecast-bot/1.0"},
        allow_redirects=True,
    ).text
    soup = BeautifulSoup(html, "html.parser")
    ref_station = None
    for s in soup.find_all(string=re.compile(r"Tide from")):
        m = re.search(r"Tide from ([^(]+)\(", s)
        if m:
            ref_station = m.group(1).strip()
            break
    days = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        date_match = re.search(r"(\d{2}/\d{2}/\d{4})", date_text)
        if not date_match:
            continue
        day_tides = []
        for cell in cells[1:5]:
            text = cell.get_text(" ", strip=True)
            m = TIDE_RE.search(text)
            if not m:
                continue
            day_tides.append({
                "type":        "low" if m.group(1) == "▼" else "high",
                "time":        m.group(2),
                "height_m":    float(m.group(3)),
                "coefficient": int(m.group(4)),
            })
        if day_tides:
            days.append({
                "date":              date_match.group(1),
                "reference_station": ref_station,
                "tides":             day_tides,
            })
        if len(days) >= n_days:
            break
    return days

# ─── Resilient HTTP helper for Open-Meteo ──────────────────────────────
def fetch_with_retry(url, params, timeout=60, retries=2, retry_delay=5):
    """GET with retries on transient errors. Returns parsed JSON or {"error": ...}."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last_err = f"{type(e).__name__}: {e} (attempt {attempt + 1}/{retries + 1})"
            if attempt < retries:
                time.sleep(retry_delay)
    return {"error": last_err}


def _model_ok(waves_response, suffix):
    """A wave model is OK if it returned non-zero, non-null data."""
    if "error" in waves_response:
        return False
    arr = waves_response.get("hourly", {}).get(f"wave_height_{suffix}", [])
    return any(v not in (None, 0, 0.0) for v in arr)

# ─── Main pull loop ────────────────────────────────────────────────────
bundle = {
    "schema_version": 2,
    "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "spots": {},
}

for name, (lat, lon) in SPOTS.items():
    waves = fetch_with_retry(
        "https://marine-api.open-meteo.com/v1/marine",
        {
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_direction,wave_period,"
                      "swell_wave_height,swell_wave_direction,swell_wave_period",
            "models": WAVE_MODELS,
            "timezone": "Europe/Madrid",
            "forecast_days": 3,
        },
    )
    wind = fetch_with_retry(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "models": WIND_MODELS,
            "timezone": "Europe/Madrid",
            "forecast_days": 3,
        },
    )
    wid, slug = WISUKI.get(name, (None, None))
    tide, tide_error = [], None
    if wid:
        try:
            tide = fetch_wisuki_tides(wid, slug) or []
        except Exception as e:
            tide_error = f"{type(e).__name__}: {e}"
    else:
        tide_error = "no_wisuki_mapping"

    spot_entry = {
        "lat": lat, "lon": lon,
        "waves": waves, "wind": wind, "tide": tide,
    }
    if tide_error:
        spot_entry["tide_error"] = tide_error
    spot_entry["_meta"] = {
        "waves_ok":   "error" not in waves,
        "wind_ok":    "error" not in wind,
        "tide_ok":    len(tide) > 0,
        "ewam_ok":    _model_ok(waves, "ewam"),
        "gfswave_ok": _model_ok(waves, "ncep_gfswave025"),
        "mfwam_ok":   _model_ok(waves, "meteofrance_wave"),
    }
    bundle["spots"][name] = spot_entry
    # Friendly pause between spots
    time.sleep(1.5)

# ─── Write outputs ─────────────────────────────────────────────────────
pathlib.Path("today.json").write_text(json.dumps(bundle, indent=2))
date_str = datetime.date.today().isoformat()
pathlib.Path("archive").mkdir(exist_ok=True)
pathlib.Path(f"archive/{date_str}.json").write_text(json.dumps(bundle, indent=2))

n_total = len(bundle["spots"])
n_waves = sum(1 for s in bundle["spots"].values() if "error" not in s["waves"])
n_wind = sum(1 for s in bundle["spots"].values() if "error" not in s["wind"])
n_tide = sum(1 for s in bundle["spots"].values() if len(s["tide"]) > 0)
print(f"Wrote forecast for {n_total} spots: "
      f"{n_waves} with waves, {n_wind} with wind, {n_tide} with tide")
for name, s in bundle["spots"].items():
    m = s["_meta"]
    print(f"  {name}: waves={'OK' if m['waves_ok'] else 'ERR'}, "
          f"wind={'OK' if m['wind_ok'] else 'ERR'}, "
          f"tide={'OK' if m['tide_ok'] else 'MISS'}, "
          f"ewam={'OK' if m['ewam_ok'] else 'NA'}, "
          f"gfswave={'OK' if m['gfswave_ok'] else 'NA'}, "
          f"mfwam={'OK' if m['mfwam_ok'] else 'NA'}")
