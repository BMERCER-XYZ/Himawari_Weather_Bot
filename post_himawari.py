import os
import sys
import io
import requests
from datetime import datetime, timezone, timedelta
from PIL import Image

# --- Config ---
# 20d = 20x20 grid of 550px tiles = 11,000x11,000px full disk
# That's extremely large; 8d (4400x4400px) is a practical maximum for Discord
ZOOM = 8
TILE_SIZE = 550
HIMAWARI_BASE = f"https://himawari8.nict.go.jp/img/D531106/{ZOOM}d/{TILE_SIZE}"

# Discord's max file upload is 8MB — we'll JPEG compress to fit
DISCORD_MAX_BYTES = 7 * 1024 * 1024  # 7MB to be safe

# Weather endpoint for the nearest station (Australian BOM JSON)
WEATHER_URL = "https://www.bom.gov.au/fwo/IDS60801/IDS60801.94146.json"

# OpenWeatherMap endpoints
# - free "Current weather and forecasts" API for 3‑hourly 5‑day forecasts
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# environment variable name used for storing the OWM API key; in a repo
# this should be set as a secret named this value (e.g. in GitHub Actions).
OPENWEATHER_KEY_ENV = "OPENWEATHER_API_KEY"


def fetch_weather(url: str) -> dict:
    """Retrieve the latest observation and pull out the fields we care about.

    The BOM site blocks automated clients unless a browser-like user-agent is
    supplied, so we include a simple header here. The JSON structure contains a
    list under ``observations.data``; we take the first entry.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, timeout=10, headers=headers)
    r.raise_for_status()
    data = r.json()
    obs_list = data.get("observations", {}).get("data", [])
    if not obs_list:
        raise RuntimeError("No observations found in weather data")
    obs = obs_list[0]

    return {
        "air_temp": obs.get("air_temp"),
        "apparent_t": obs.get("apparent_t"),
        "wind_dir": obs.get("wind_dir"),
        "wind_spd_kmh": obs.get("wind_spd_kmh"),
        "gust_kmh": obs.get("gust_kmh"),
        "rel_hum": obs.get("rel_hum"),
        "press": obs.get("press"),
        "weather": obs.get("weather"),
        "cloud": obs.get("cloud"),
        "lat": obs.get("lat"),
        "lon": obs.get("lon"),
    }


def get_timestamp_url(dt: datetime, col: int, row: int) -> str:
    minute = (dt.minute // 10) * 10
    ts = dt.strftime(f"%Y/%m/%d/%H{minute:02d}00")
    return f"{HIMAWARI_BASE}/{ts}_{col}_{row}.png"


def find_valid_timestamp() -> datetime:
    """Step back in 10-min increments until tile (0,0) exists."""
    base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    for i in range(12):
        candidate = base_time - timedelta(minutes=10 * i)
        url = get_timestamp_url(candidate, 0, 0)
        r = requests.head(url, timeout=10)
        if r.status_code == 200:
            print(f"✅ Found valid timestamp: {url}")
            return candidate
        print(f"⚠️  Not available: {url}")
    raise RuntimeError("Could not find a valid Himawari image in the last 2 hours.")


def fetch_tile(url: str) -> Image.Image:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def build_full_disk(timestamp: datetime) -> bytes:
    full_size = ZOOM * TILE_SIZE  # e.g. 4400px for ZOOM=8
    canvas = Image.new("RGB", (full_size, full_size))

    total = ZOOM * ZOOM
    print(f"Fetching {total} tiles ({ZOOM}x{ZOOM} grid = {full_size}x{full_size}px)...")

    for row in range(ZOOM):
        for col in range(ZOOM):
            url = get_timestamp_url(timestamp, col, row)
            tile = fetch_tile(url)
            canvas.paste(tile, (col * TILE_SIZE, row * TILE_SIZE))
            done = row * ZOOM + col + 1
            print(f"  Tile {done}/{total} ({col},{row})", end="\r")

    print()  # newline after progress

    # Compress to fit Discord's 8MB limit, reducing quality if needed
    for quality in [95, 85, 75, 60]:
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=quality, optimize=True)
        size = buf.tell()
        print(f"  JPEG quality {quality}: {size / 1024 / 1024:.1f}MB")
        if size <= DISCORD_MAX_BYTES:
            buf.seek(0)
            return buf.read()

    raise RuntimeError("Could not compress image small enough for Discord.")


def fetch_forecast(api_key: str, lat: float, lon: float) -> dict:
    """Call the free forecast endpoint and return a few upcoming entries.

    The forecast API returns a list of 3‑hourly blocks for the next 5 days; we
    extract the first three blocks so the Discord embed isn't overly long.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        # we only need the 3‑hour list, not city metadata
    }
    r = requests.get(OPENWEATHER_FORECAST_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    lst = data.get("list", [])
    if not lst:
        raise RuntimeError("no forecast data returned from OpenWeatherMap")

    # take up to the first three entries (9 hours ahead)
    entries = []
    for item in lst[:3]:
        dt_txt = item.get("dt_txt", "")
        main = item.get("main", {})
        temp = main.get("temp")
        desc = ""
        if item.get("weather"):
            desc = item["weather"][0].get("description", "")
        entries.append((dt_txt, temp, desc))

    return {"entries": entries}


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime, owm_key: str):
    import json
    time_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    size_mb = len(image_bytes) / 1024 / 1024

    # grab weather information; if it fails we'll let the exception bubble up
    weather = fetch_weather(WEATHER_URL)

    # also try to obtain a short forecast from OpenWeatherMap; it's okay if the
    # request fails, we can just omit that part of the message
    forecast_str = ""
    try:
        if owm_key:
            fc = fetch_forecast(owm_key, weather.get("lat"), weather.get("lon"))
            if fc and fc.get("entries"):
                parts = []
                for dt_txt, temp, desc in fc["entries"]:
                    # only show hour and description
                    when = dt_txt.split(" ")[1] if dt_txt else ""
                    parts.append(f"{when}: {desc} {temp}°C")
                forecast_str = "\n🔮 Upcoming: " + "; ".join(parts)
    except Exception as e:
        # don't crash the whole bot for a forecast hiccup; print for diagnostics
        print(f"⚠️  Forecast lookup failed: {e}")

    # build a short human-readable block for the description; use .get() to
    # avoid KeyError if any field is missing
    weather_str = (
        f"🌡️ Air: {weather.get('air_temp','-')}°C (feels like {weather.get('apparent_t','-')}°C)\n"
        f"💧 Humidity: {weather.get('rel_hum','-')}%  Pressure: {weather.get('press','-')} hPa\n"
        f"☁️ Sky: {weather.get('cloud','-')} — {weather.get('weather','-')}\n"
        f"💨 Wind: {weather.get('wind_dir','-')} at {weather.get('wind_spd_kmh','-')} km/h, "
        f"gusts {weather.get('gust_kmh','-')} km/h"
    )

    payload = {
        "username": "Himawari Weather Bot 🌐",
        "avatar_url": "https://himawari8.nict.go.jp/favicon.ico",
        "embeds": [
            {
                "title": "Himawari Weather Bot 🌐",
                "description": (
                    f"{weather_str}{forecast_str}"
                ),
                "image": {"url": "attachment://himawari.jpg"},
                "color": 0x1a73e8,
                "footer": {"text": f"Source: NICT Himawari Monitor • {size_mb:.1f}MB"},
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }

    response = requests.post(
        webhook_url,
        data={"payload_json": json.dumps(payload)},
        files={"file": ("himawari.jpg", image_bytes, "image/jpeg")},
        timeout=60
    )
    response.raise_for_status()
    print(f"✅ Posted successfully! ({size_mb:.1f}MB)")


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL environment variable not set.")
        sys.exit(1)

    owm_key = os.environ.get(OPENWEATHER_KEY_ENV)
    if not owm_key:
        # don't treat this as a fatal error; the bot will still post the image
        # and current observation but omit the OpenWeatherMap forecast.  When
        # running in GitHub Actions you must map the repo secret yourself,
        # e.g. ``env: OPENWEATHER_API_KEY: ${{ secrets.OPENWEATHER_API_KEY }}``.
        print(f"⚠️  Warning: {OPENWEATHER_KEY_ENV} environment variable not set; "
              "forecast will be skipped.")
        owm_key = ""

    timestamp = find_valid_timestamp()
    image_bytes = build_full_disk(timestamp)
    post_to_discord(webhook_url, image_bytes, timestamp, owm_key)


if __name__ == "__main__":
    main()