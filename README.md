# Himawari Weather Bot

This Python script builds a full-disk image from the Himawari-8/9 satellite
and posts it to a Discord webhook along with current weather information from
Adelaide Airport (BOM), plus a short forecast pulled from OpenWeatherMap.

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

3. Obtain a (free) API key from https://openweathermap.org/ and store it in a
   secret named `OPENWEATHER_API_KEY`. Locally you can export the variable:

   ```sh
   export OPENWEATHER_API_KEY="your_api_key_here"
   ```

   On GitHub Actions or other CI systems, add `OPENWEATHER_API_KEY` as a
   repository secret so it isn't exposed in logs.

4. Run the script:

   ```sh
   python post_himawari.py
   ```

The bot will find the most recent Himawari tile set, stitch the image,
  fetch the weather and forecast, generate a small line graph of the
  5‑day/3‑hour forecast, and post everything to Discord (image + graph).

  The embed description only includes forecasts for the remainder of the day
  the message is sent, with times in 12‑hour format.  The attached graph shows
  five separate stacked line plots (one per day) spanning the full forecast
  range.
- The BOM JSON feed blocks requests without a browser-like user-agent; the
  script sets one automatically.
- Forecasts are fetched using the free OpenWeatherMap Current Weather and
  Forecasts API (`/forecast` endpoint) which returns 3‑hourly data for the
  next five days. If the forecast request fails the bot will still post the
  satellite image and current observation.

Happy meteorology! 🌤️
