import os
import sys
import io
import requests
import json
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


def fetch_weather_data() -> dict:
    """Fetch the latest weather data from BOM."""
    weather_url = "https://www.bom.gov.au/fwo/IDS60801/IDS60801.94146.json"
    try:
        r = requests.get(weather_url, timeout=10)
        r.raise_for_status()
        data = r.json()
        # Get the most recent observation (first one in the list)
        if data.get("observations") and len(data["observations"]["data"]) > 0:
            observation = data["observations"]["data"][0]
            return {
                "air_temp": observation.get("air_temp"),
                "apparent_t": observation.get("apparent_t"),
                "wind_dir": observation.get("wind_dir"),
                "wind_spd_kmh": observation.get("wind_spd_kmh"),
                "gust_kmh": observation.get("gust_kmh"),
                "local_time": observation.get("local_date_time_full"),
            }
    except Exception as e:
        print(f"⚠️  Could not fetch weather data: {e}")
    
    return None


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime, weather: dict = None):
    import json
    time_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    size_mb = len(image_bytes) / 1024 / 1024

    # Build weather text for message content
    weather_text = ""
    if weather:
        try:
            air_temp = weather.get("air_temp", "N/A")
            apparent_t = weather.get("apparent_t", "N/A")
            wind_dir = weather.get("wind_dir", "N/A")
            wind_spd = weather.get("wind_spd_kmh", "N/A")
            gust = weather.get("gust_kmh", "N/A")
            
            weather_text = (
                "🌡️ **Weather Conditions:**\n"
                f"Air Temperature: {air_temp}°C\n"
                f"Apparent Temperature: {apparent_t}°C\n"
                f"Wind Direction: {wind_dir}\n"
                f"Wind Speed: {wind_spd} km/h\n"
                f"Gust Speed: {gust} km/h\n\n"
            )
        except Exception as e:
            print(f"⚠️  Error formatting weather data: {e}")

    embeds = [
        {
            "title": "🛰️ Himawari-8/9 Satellite Image",
            "description": (
                f"Full-disk Earth view at {ZOOM*TILE_SIZE}×{ZOOM*TILE_SIZE}px\n"
                f"🕐 Approx. capture time: **{time_str}**"
            ),
            "image": {"url": "attachment://himawari.jpg"},
            "color": 0x1a73e8,
            "footer": {"text": f"Source: NICT Himawari Monitor • {size_mb:.1f}MB"},
            "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
        }
    ]

    payload = {
        "username": "Himawari Satellite",
        "avatar_url": "https://himawari8.nict.go.jp/favicon.ico",
        "content": weather_text,
        "embeds": embeds
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

    timestamp = find_valid_timestamp()
    image_bytes = build_full_disk(timestamp)
    weather = fetch_weather_data()
    post_to_discord(webhook_url, image_bytes, timestamp, weather)


if __name__ == "__main__":
    main()