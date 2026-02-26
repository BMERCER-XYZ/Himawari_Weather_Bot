import os
import sys
import io
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from PIL import Image

# --- Config ---
ZOOM = 4
TILE_SIZE = 550
HIMAWARI_BASE = f"https://himawari8.nict.go.jp/img/D531106/{ZOOM}d/{TILE_SIZE}"

ADELAIDE_TZ = ZoneInfo("Australia/Adelaide")


def get_noon_timestamp() -> datetime:
    now_utc = datetime.now(timezone.utc)
    now_adl = now_utc.astimezone(ADELAIDE_TZ)

    noon_adl = now_adl.replace(hour=12, minute=0, second=0, microsecond=0)
    if now_adl < noon_adl:
        noon_adl -= timedelta(days=1)

    noon_utc = noon_adl.astimezone(timezone.utc)
    minute = (noon_utc.minute // 10) * 10
    noon_utc = noon_utc.replace(minute=minute, second=0, microsecond=0)

    while noon_utc > now_utc - timedelta(minutes=30):
        noon_utc -= timedelta(minutes=10)

    return noon_utc


def fetch_tile(url: str) -> Image.Image:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def build_image(timestamp: datetime) -> bytes:
    ts_str = timestamp.strftime("%Y/%m/%d/%H%M%S")

    # Only fetch the bottom 2 rows of tiles (rows 2 and 3 of a 4x4 grid)
    cols = range(ZOOM)
    rows = range(ZOOM // 2, ZOOM)

    canvas_w = ZOOM * TILE_SIZE
    canvas_h = (ZOOM // 2) * TILE_SIZE
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    print(f"Fetching {len(cols) * len(rows)} tiles for {ts_str}...")
    for ri, row in enumerate(rows):
        for ci, col in enumerate(cols):
            url = f"{HIMAWARI_BASE}/{ts_str}_{col}_{row}.png"
            tile = fetch_tile(url)
            canvas.paste(tile, (ci * TILE_SIZE, ri * TILE_SIZE))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.read()


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime):
    import json
    adl_time = timestamp.astimezone(ADELAIDE_TZ)
    time_str = (
        f"{adl_time.strftime('%Y-%m-%d %H:%M')} Adelaide time "
        f"({timestamp.strftime('%H:%M')} UTC)"
    )

    payload = {
        "username": "Himawari Satellite",
        "embeds": [
            {
                "title": "🛰️ Himawari — Southern Hemisphere",
                "description": f"☀️ Captured at noon: **{time_str}**",
                "color": 0x1a73e8,
                "image": {"url": "attachment://himawari.jpg"},
                "footer": {"text": "Source: NICT Himawari Monitor • himawari8.nict.go.jp"},
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }

    response = requests.post(
        webhook_url,
        data={"payload_json": json.dumps(payload)},
        files={"file": ("himawari.jpg", image_bytes, "image/jpeg")},
        timeout=30
    )
    response.raise_for_status()
    print("✅ Posted successfully!")


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)

    timestamp = get_noon_timestamp()
    adl_time = timestamp.astimezone(ADELAIDE_TZ)
    print(f"Target: {adl_time.strftime('%Y-%m-%d %H:%M %Z')} → {timestamp.strftime('%H:%M UTC')}")

    try:
        image_bytes = build_image(timestamp)
    except requests.HTTPError as e:
        print(f"⚠️  Tiles unavailable ({e}), trying 10 min earlier...")
        timestamp -= timedelta(minutes=10)
        image_bytes = build_image(timestamp)

    post_to_discord(webhook_url, image_bytes, timestamp)


if __name__ == "__main__":
    main()