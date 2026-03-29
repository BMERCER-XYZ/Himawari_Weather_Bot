# Himawari Weather Bot

This Python script builds a full-disk image from the Himawari-8/9 satellite
and posts it to a Discord webhook along with current weather information from
Adelaide Airport (BOM), plus a 7-day forecast pulled from the BOM API.

## Setup

1. Clone the repo and install dependencies (Pillow, requests, matplotlib):

   ```sh
   python -m pip install --upgrade pillow requests matplotlib
   ```

2. Create a Discord webhook and add its URL to the `DISCORD_WEBHOOK_URL`
   environment variable. For example:

   ```sh
   export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
   ```

3. Run the script:

   ```sh
   python post_himawari.py
   ```

The bot will find the most recent Himawari tile set, stitch the image,
  fetch the weather and forecast, generate a shaded line graph of the
  7-day forecast, and post everything to Discord (image + graph).

- The BOM feeds block requests without a browser-like user-agent; the
  script sets one automatically.
- Forecasts are fetched directly from the local BOM XML feeds. If the 
  forecast request fails the bot will still post the satellite image and
  current observation.

Happy meteorology! 🌤️
