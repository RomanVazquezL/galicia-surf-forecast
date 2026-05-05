import requests, json, datetime, pathlib, re
from bs4 import BeautifulSoup

# ─── Spots: name → (latitude, longitude) ───────────────────────────────
SPOTS = {
    "pantin":       (43.6413, -8.1137),
    "doninos":      (43.5183, -8.3367),
    "razo":         (43.2917, -8.7950),
    "bastiagueiro": (43.3483, -8.3000),
    "san_xurxo":    (43.5217, -8.3433),
    "caion":        (43.3151, -8.6101),
}

# ─── Wisuki id and slug for each spot, used for tide scraping ──────────
# If a spot doesn't exist on Wisuki, set to (None, None) and tides skip.
WISUKI = {
    "pantin":       (7394, "pantn"),
    "doninos":      (2775, "donios"),
    "razo":         (2782, "razo"),
    "bastiagueiro": (6759, "bastiagueiro"),
    "san_xurxo":    (2786, "san-xurxo"),
    "caion":        (6767, "cain"),
}

# ─── Open-Meteo model selection (rarely needs to change) ───────────────
WAVE_MODELS = "ewam,ncep_gfswave025,meteofrance_wave"
WIND_MODELS = "best_match,ecmwf_ifs025,gfs_seamless"

# ─── Wisuki tide scraper ───────────────────────────────────────────────
TIDE_RE = re.compile(r"([▼▲])\s*(\d{2}:\d{2})\s*([\d.]+)\s*m\s*(\d+)")

def fetch_wisuki_tides(wisuki_id, slug, n_days=7):
    """Scrape Wisuki tide page for a spot. Returns list of daily dicts."""
    url = f"https://wisuki.com/tide/{wisuki_id}/{slug}"
    html = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "surf-forecast-bot/1.0"},
        allow_redirects=True,
    ).text
    soup = BeautifulSoup(html, "html.parser")

    # Pull the reference station name (e.g. "Tide from Cedeira (4.72km from Pantín)")
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
        for cell in cells[1:5]:  # 1st through 4th tide of the day
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

# ─── Main pull loop ────────────────────────────────────────────────────
bundle = {
    "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "spots": {},
}

for name, (lat, lon) in SPOTS.items():
    # Waves (Open-Meteo marine API, multi-model)
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

    # Wind (Open-Meteo standard API, multi-model)
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

    # Tide (Wisuki HTML scrape)
    wid, slug = WISUKI.get(name, (None, None))
    if wid:
        try:
            tide = fetch_wisuki_tides(wid, slug)
        except Exception as e:
            tide = {"error": str(e)}
    else:
        tide = None

    bundle["spots"][name] = {
        "lat": lat, "lon": lon,
        "waves": waves, "wind": wind, "tide": tide,
    }

# ─── Write outputs ─────────────────────────────────────────────────────
pathlib.Path("today.json").write_text(json.dumps(bundle, indent=2))
date_str = datetime.date.today().isoformat()
pathlib.Path("archive").mkdir(exist_ok=True)
pathlib.Path(f"archive/{date_str}.json").write_text(json.dumps(bundle, indent=2))

n_total = len(bundle["spots"])
n_with_tide = sum(
    1 for s in bundle["spots"].values()
    if isinstance(s["tide"], list) and s["tide"]
)
print(f"Wrote forecast for {n_total} spots, {n_with_tide} with tide data")
