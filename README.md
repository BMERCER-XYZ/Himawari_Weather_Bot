# Himawari Weather Bot

This Python script builds a full-disk image from the Himawari-8/9 satellite
and posts it to a Discord webhook along with current weather information from
Adelaide Airport (BOM), plus a short forecast pulled from OpenWeatherMap.

## Setup

1. Clone the repo and install dependencies (Pillow, requests):

   ```sh
   python -m pip install --upgrade pillow requests
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

   The bot will find the most recent Himawari tile set, stitch the image, fetch
   the weather and forecast, then post everything to Discord.

## Notes

- The BOM JSON feed blocks requests without a browser-like user-agent; the
  script sets one automatically.
- Forecasts are fetched using the OpenWeatherMap One Call API. If the forecast
  request fails the bot will still post the satellite image and current
  observation.

Happy meteorology! 🌤️
