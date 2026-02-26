import os
import sys
import requests
from datetime import datetime, timezone, timedelta

HIMAWARI_BASE = "https://himawari8.nict.go.jp/img/D531106/15d/550"

def get_latest_image_url():
    """Get the most recent Himawari full-disk image URL."""
    # Himawari images are available every 10 minutes, ~30 min delay
    now = datetime.now(timezone.utc) - timedelta(minutes=30)
    # Round down to nearest 10 minutes
    minute = (now.minute // 10) * 10
    timestamp = now.strftime(f"%Y/%m/%d/%H{minute:02d}00")
    url = f"{HIMAWARI_BASE}/{timestamp}_0_0.png"
    return url, now

def post_to_discord(webhook_url: str, image_url: str, timestamp: datetime):
    """Post the satellite image to Discord via webhook."""
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
                "footer": {
                    "text": "Source: NICT Himawari Monitor • himawari8.nict.go.jp"
                },
                "url": "https://himawari8.nict.go.jp/en/himawari8-image.htm"
            }
        ]
    }

    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()
    print(f"✅ Posted successfully! Image URL: {image_url}")

def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL environment variable not set.")
        sys.exit(1)

    image_url, timestamp = get_latest_image_url()
    
    # Verify image exists
    head = requests.head(image_url, timeout=10)
    if head.status_code != 200:
        # Try one step back (10 more minutes)
        timestamp -= timedelta(minutes=10)
        minute = (timestamp.minute // 10) * 10
        ts = timestamp.strftime(f"%Y/%m/%d/%H{minute:02d}00")
        image_url = f"{HIMAWARI_BASE}/{ts}_0_0.png"
        print(f"⚠️  Primary URL unavailable, trying fallback: {image_url}")

    post_to_discord(webhook_url, image_url, timestamp)

if __name__ == "__main__":
    main()