import os
import sys
import io
import requests
from datetime import datetime, timezone, timedelta
from PIL import Image

# --- Config ---
ZOOM = 4          # Grid size: 4 = 2200px full disk, 8 = 4400px, 20 = 11000px
TILE_SIZE = 550   # Each tile is 550x550px
HIMAWARI_BASE = f"https://himawari8.nict.go.jp/img/D531106/{ZOOM}d/{TILE_SIZE}"

# Australia crop: fraction of the full stitched image (tweak if needed)
# Himawari is centered ~140.7°E, full disk covers ~±60° lat/lon
CROP_LEFT   = 0.62
CROP_TOP    = 0.52
CROP_RIGHT  = 0.82
CROP_BOTTOM = 0.80


def get_timestamp():
    now = datetime.now(timezone.utc) - timedelta(minutes=30)
    minute = (now.minute // 10) * 10
    return now.replace(minute=minute, second=0, microsecond=0)


def fetch_tile(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def build_australia_image(timestamp: datetime) -> bytes:
    ts_str = timestamp.strftime("%Y/%m/%d/%H%M%S")

    # Determine which tiles overlap the Australia crop region
    col_start = int(CROP_LEFT * ZOOM)
    col_end   = min(int(CROP_RIGHT * ZOOM) + 1, ZOOM)
    row_start = int(CROP_TOP * ZOOM)
    row_end   = min(int(CROP_BOTTOM * ZOOM) + 1, ZOOM)

    cols = range(col_start, col_end)
    rows = range(row_start, row_end)

    # Stitch the relevant tiles
    canvas_w = len(cols) * TILE_SIZE
    canvas_h = len(rows) * TILE_SIZE
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    print(f"Fetching {len(cols) * len(rows)} tiles...")
    for ri, row in enumerate(rows):
        for ci, col in enumerate(cols):
            url = f"{HIMAWARI_BASE}/{ts_str}_{col}_{row}.png"
            tile = fetch_tile(url)
            canvas.paste(tile, (ci * TILE_SIZE, ri * TILE_SIZE))

    # Crop to Australia within the stitched canvas
    full_size = ZOOM * TILE_SIZE
    left   = int(CROP_LEFT   * full_size) - col_start * TILE_SIZE
    top    = int(CROP_TOP    * full_size) - row_start * TILE_SIZE
    right  = int(CROP_RIGHT  * full_size) - col_start * TILE_SIZE
    bottom = int(CROP_BOTTOM * full_size) - row_start * TILE_SIZE

    cropped = canvas.crop((left, top, right, bottom))

    # Save to bytes as JPEG (Discord has 8MB limit)
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.read()


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime):
    time_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "username": "Himawari Satellite",
        "embeds": [
            {
                "title": "🛰️ Himawari — Australia & Oceania",
                "description": f"🕐 Approx. capture time: **{time_str}**",
                "color": 0x1a73e8,
                "image": {"url": "attachment://himawari_australia.jpg"},
                "footer": {"text": "Source: NICT Himawari Monitor • himawari8.nict.go.jp"},
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }

    response = requests.post(
        webhook_url,
        data={"payload_json": str(payload).replace("'", '"')},
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

    timestamp = get_timestamp()
    print(f"Fetching image for: {timestamp.strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        image_bytes = build_australia_image(timestamp)
    except requests.HTTPError:
        print("⚠️  Latest tiles unavailable, trying 10 min earlier...")
        timestamp -= timedelta(minutes=10)
        image_bytes = build_australia_image(timestamp)

    post_to_discord(webhook_url, image_bytes, timestamp)


if __name__ == "__main__":
    main()