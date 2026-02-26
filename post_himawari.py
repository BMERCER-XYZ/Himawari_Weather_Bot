import os
import sys
import requests
from datetime import datetime, timezone, timedelta

HIMAWARI_BASE = "https://himawari8.nict.go.jp/img/D531106/1d/550"

def get_timestamp_url(dt: datetime) -> str:
    minute = (dt.minute // 10) * 10
    ts = dt.strftime(f"%Y/%m/%d/%H{minute:02d}00")
    return f"{HIMAWARI_BASE}/{ts}_0_0.png"

def get_latest_image_url():
    """Try up to 6 ten-minute slots back until we find a valid image."""
    base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    
    for i in range(6):
        candidate = base_time - timedelta(minutes=10 * i)
        url = get_timestamp_url(candidate)
        head = requests.head(url, timeout=10)
        if head.status_code == 200:
            print(f"✅ Found valid image: {url}")
            return url, candidate
        print(f"⚠️  Not available: {url}")

    raise RuntimeError("Could not find a valid Himawari image in the last hour.")

def post_to_discord(webhook_url: str, image_url: str, timestamp: datetime):
    time_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "username": "Himawari Satellite",
        "avatar_url": "https://himawari8.nict.go.jp/favicon.ico",
        "embeds": [
            {
                "title": "🛰️ Himawari-8/9 Satellite Image",
                "description": f"Latest full-disk Earth view\n🕐 Approx. capture time: **{time_str}**",
                "image": {"url": image_url},
                "color": 0x1a73e8,
                "footer": {"text": "Source: NICT Himawari Monitor • himawari8.nict.go.jp"},
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }
    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()
    print(f"✅ Posted successfully!")

def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL environment variable not set.")
        sys.exit(1)

    image_url, timestamp = get_latest_image_url()
    post_to_discord(webhook_url, image_url, timestamp)

if __name__ == "__main__":
    main()