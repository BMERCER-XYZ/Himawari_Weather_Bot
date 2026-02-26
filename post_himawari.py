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

# Australia crop fractions
CROP_LEFT   = 0.01
CROP_TOP    = 0.55
CROP_RIGHT  = 0.01
CROP_BOTTOM = 0.01


def get_noon_timestamp() -> datetime:
    """
    Get the most recent noon (Adelaide time) that has passed,
    rounded to the nearest available 10-minute Himawari interval.
    Himawari images have ~30 min delay, so we allow for that.
    """
    now_utc = datetime.now(timezone.utc)
    now_adl = now_utc.astimezone(ADELAIDE_TZ)

    # Start with today's noon in Adelaide
    noon_adl = now_adl.replace(hour=12, minute=0, second=0, microsecond=0)

    # If today's noon hasn't happened yet, use yesterday's
    if now_adl < noon_adl:
        noon_adl -= timedelta(days=1)

    # Convert to UTC
    noon_utc = noon_adl.astimezone(timezone.utc)

    # Round to nearest 10-minute Himawari slot
    minute = (noon_utc.minute // 10) * 10
    noon_utc = noon_utc.replace(minute=minute, second=0, microsecond=0)

    # Sanity check: if the slot is somehow in the future (edge case), step back
    while noon_utc > now_utc - timedelta(minutes=30):
        noon_utc -= timedelta(minutes=10)

    return noon_utc


def fetch_tile(url: str) -> Image.Image:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def build_australia_image(timestamp: datetime) -> bytes:
    ts_str = timestamp.strftime("%Y/%m/%d/%H%M%S")

    col_start = int(CROP_LEFT * ZOOM)
    col_end   = min(int(CROP_RIGHT * ZOOM) + 1, ZOOM)
    row_start = int(CROP_TOP * ZOOM)
    row_end   = min(int(CROP_BOTTOM * ZOOM) + 1, ZOOM)

    cols = range(col_start, col_end)
    rows = range(row_start, row_end)

    canvas_w = len(cols) * TILE_SIZE
    canvas_h = len(rows) * TILE_SIZE
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    print(f"Fetching {len(cols) * len(rows)} tiles for {ts_str}...")
    for ri, row in enumerate(rows):
        for ci, col in enumerate(cols):
            url = f"{HIMAWARI_BASE}/{ts_str}_{col}_{row}.png"
            tile = fetch_tile(url)
            canvas.paste(tile, (ci * TILE_SIZE, ri * TILE_SIZE))

    full_size = ZOOM * TILE_SIZE
    left   = int(CROP_LEFT   * full_size) - col_start * TILE_SIZE
    top    = int(CROP_TOP    * full_size) - row_start * TILE_SIZE
    right  = int(CROP_RIGHT  * full_size) - col_start * TILE_SIZE
    bottom = int(CROP_BOTTOM * full_size) - row_start * TILE_SIZE

    cropped = canvas.crop((left, top, right, bottom))

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.read()


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime):
    # Show both UTC and Adelaide local time in the embed
    adl_time = timestamp.astimezone(ADELAIDE_TZ)
    time_str = (
        f"{adl_time.strftime('%Y-%m-%d %H:%M')} Adelaide time "
        f"({timestamp.strftime('%H:%M')} UTC)"
    )

    import json
    payload = {
        "username": "Himawari Satellite",
        "embeds": [
            {
                "title": "🛰️ Himawari — Australia & Oceania",
                "description": f"☀️ Captured at noon: **{time_str}**",
                "color": 0x1a73e8,
                "image": {"url": "attachment://himawari_australia.jpg"},
                "footer": {"text": "Source: NICT Himawari Monitor • himawari8.nict.go.jp"},
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }

    response = requests.post(
        webhook_url,
        data={"payload_json": json.dumps(payload)},
        files={"file": ("himawari_australia.jpg", image_bytes, "image/jpeg")},
        timeout=30
    )
    response.raise_for_status()
    print(f"✅ Posted successfully!")


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)

    timestamp = get_noon_timestamp()
    adl_time = timestamp.astimezone(ADELAIDE_TZ)
    print(f"Target: noon Adelaide = {adl_time.strftime('%Y-%m-%d %H:%M %Z')} → {timestamp.strftime('%H:%M UTC')}")

    try:
        image_bytes = build_australia_image(timestamp)
    except requests.HTTPError as e:
        print(f"⚠️  Tiles unavailable ({e}), trying 10 min earlier...")
        timestamp -= timedelta(minutes=10)
        image_bytes = build_australia_image(timestamp)

    post_to_discord(webhook_url, image_bytes, timestamp)


if __name__ == "__main__":
    main()