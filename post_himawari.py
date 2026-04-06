import os
import sys
import io
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from PIL import Image, ImageDraw, ImageFont

import xml.etree.ElementTree as ET

session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

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

BOM_FORECAST_URL = "https://www.bom.gov.au/fwo/IDS10044.xml"
HOURLY_FORECAST_LOCATION_ID = "r1f90q"
SIDE_PANEL_WIDTH = 200


def parse_utc_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(value) == 14 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_font(size: int, bold: bool = False):
    try:
        from matplotlib import font_manager

        weight = "bold" if bold else "normal"
        font_path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight=weight))
        return ImageFont.truetype(font_path, size=size)
    except Exception:
        return ImageFont.load_default()


def draw_centered_text(draw: ImageDraw.ImageDraw, center_x: float, y: float, text: str, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text((center_x - width / 2, y), text, font=font, fill=fill)


def estimate_rain_last_24h(observations: list[dict]) -> float | None:
    if not observations:
        return None

    latest_time = parse_utc_timestamp(observations[0].get("aifstime_utc"))
    if latest_time is None:
        return None

    cutoff = latest_time - timedelta(hours=24)
    series = []
    for obs in observations:
        obs_time = parse_utc_timestamp(obs.get("aifstime_utc"))
        if obs_time is None or obs_time < cutoff:
            continue
        rain_value = safe_float(obs.get("rain_trace"))
        if rain_value is not None:
            series.append((obs_time, rain_value))

    if not series:
        return None

    series.sort(key=lambda item: item[0])
    total = 0.0
    previous = series[0][1]
    for _, rain_value in series[1:]:
        delta = rain_value - previous
        if delta > 0:
            total += delta
        previous = rain_value

    return round(total, 1)


def render_sidebar_panel(title: str, items: list[dict], height: int) -> Image.Image:
    background_color = (255, 255, 255) # White to match the forecast plots
    panel = Image.new("RGB", (SIDE_PANEL_WIDTH, height), background_color)
    draw = ImageDraw.Draw(panel)

    panel_width, panel_height = panel.size
    
    # Outer border
    draw.rectangle((0, 0, panel_width - 1, panel_height - 1), outline=(220, 220, 220), width=1)

    title_font = load_font(32, bold=True)
    label_font = load_font(18, bold=True)
    value_font = load_font(36, bold=True)
    detail_font = load_font(16)

    title_color = (60, 60, 60)
    text_color = (20, 20, 20)
    dim_color = (120, 120, 120)

    draw_centered_text(draw, panel_width / 2, 50, title, title_font, title_color)
    
    # Separator under title
    draw.line((40, 100, panel_width - 40, 100), fill=(220, 220, 220), width=2)

    # Top of content
    top = int(height * 0.18)
    bottom = int(height * 0.88)
    usable_height = max(1, bottom - top)
    step = usable_height / max(len(items), 1)

    for index, item in enumerate(items):
        y = top + index * step
        if index > 0:
            divider_y = y - 30
            draw.line((40, divider_y, panel_width - 40, divider_y), fill=(235, 235, 235), width=1)
        draw_centered_text(draw, panel_width / 2, y, item["label"], label_font, dim_color)
        draw_centered_text(draw, panel_width / 2, y + 32, str(item["value"]), value_font, text_color)
        if item.get("detail"):
            draw_centered_text(draw, panel_width / 2, y + 80, item["detail"], detail_font, dim_color)

    footer = items[-1].get("footer") if items else None
    if footer:
        footer_font = load_font(14)
        draw_centered_text(draw, panel_width / 2, panel_height - 50, footer, footer_font, dim_color)

    return panel


def fetch_hourly_forecast_summary(location_id: str = HOURLY_FORECAST_LOCATION_ID) -> dict:
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://api.weather.bom.gov.au/v1/locations/{location_id}/forecasts/hourly"
    r = session.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    adelaide_tz = ZoneInfo("Australia/Adelaide") if ZoneInfo is not None else timezone.utc
    current_time = datetime.now(timezone.utc).astimezone(adelaide_tz).replace(tzinfo=None)
    current_date = current_time.date()

    cache_file = "hourly_forecast_cache.json"
    try:
        with open(cache_file, "r") as f:
            forecast_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        forecast_cache = {}

    for entry in data.get("data", []):
        time_value = entry.get("time")
        temp_value = entry.get("temp")
        if time_value and temp_value is not None:
            forecast_cache[time_value] = temp_value

    keys_to_delete = []
    for time_str in forecast_cache.keys():
        dt = parse_utc_timestamp(time_str)
        if dt is None:
            continue
        local_dt = dt.astimezone(adelaide_tz).replace(tzinfo=None)
        if local_dt.date() < current_date - timedelta(days=1):
            keys_to_delete.append(time_str)
    for key in keys_to_delete:
        del forecast_cache[key]

    with open(cache_file, "w") as f:
        json.dump(forecast_cache, f, indent=2)

    hours = []
    temps = []
    for time_str, temp in sorted(forecast_cache.items()):
        dt = parse_utc_timestamp(time_str)
        if dt is None:
            continue
        local_dt = dt.astimezone(adelaide_tz).replace(tzinfo=None)
        if local_dt.date() == current_date or (local_dt.date() == current_date + timedelta(days=1) and local_dt.hour == 0):
            hours.append(local_dt)
            temps.append(temp)

    wind_speeds = []
    rain_next_24h = 0.0
    for entry in data.get("data", []):
        dt = parse_utc_timestamp(entry.get("time"))
        if dt is None:
            continue
        local_dt = dt.astimezone(adelaide_tz).replace(tzinfo=None)

        wind = entry.get("wind", {})
        wind_speed = wind.get("speed_kilometre")
        if local_dt.date() == current_date or (local_dt.date() == current_date + timedelta(days=1) and local_dt.hour == 0):
            if isinstance(wind_speed, (int, float)):
                wind_speeds.append(wind_speed)

        if current_time <= local_dt < current_time + timedelta(days=1):
            rain = entry.get("rain", {})
            rain_value = rain.get("precipitation_amount_50_percent_chance")
            if rain_value is None:
                amount = rain.get("amount", {})
                rain_value = amount.get("max")
                if rain_value is None:
                    rain_value = amount.get("min")
            rain_next_24h += safe_float(rain_value) or 0.0

    return {
        "hours": hours,
        "temps": temps,
        "wind_min": min(wind_speeds) if wind_speeds else None,
        "wind_max": max(wind_speeds) if wind_speeds else None,
        "rain_next_24h": round(rain_next_24h, 1),
    }


def fetch_weather(url: str) -> dict:
    """Retrieve the latest observation and pull out the fields we care about.

    The BOM site blocks automated clients unless a browser-like user-agent is
    supplied, so we include a simple header here. The JSON structure contains a
    list under ``observations.data``; we take the first entry.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    r = session.get(url, timeout=10, headers=headers)
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
        "rain_trace": obs.get("rain_trace"),
        "lat": obs.get("lat"),
        "lon": obs.get("lon"),
        "observation_time": obs.get("aifstime_utc"),
        "history": obs_list,
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
        r = session.head(url, timeout=10)
        if r.status_code == 200:
            print(f"✅ Found valid timestamp: {url}")
            return candidate
        print(f"⚠️  Not available: {url}")
    raise RuntimeError("Could not find a valid Himawari image in the last 2 hours.")


def fetch_tile(url: str) -> Image.Image:
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def build_full_disk(timestamp: datetime) -> bytes:
    full_size = ZOOM * TILE_SIZE  # e.g. 4400px for ZOOM=8
    canvas = Image.new("RGB", (full_size, full_size), "black")

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


def fetch_forecast() -> dict:
    """Fetch the BOM daily forecast XML and return min/max temperatures and descriptions."""
    headers = {"User-Agent": "Mozilla/5.0"}
    r = session.get(BOM_FORECAST_URL, timeout=10, headers=headers)
    r.raise_for_status()

    tree = ET.parse(io.StringIO(r.text))
    root = tree.getroot()

    adelaide = root.find(".//area[@description='Adelaide']")
    if adelaide is None:
        raise RuntimeError("Adelaide area not found in BOM forecast XML")

    entries = []
    for period in adelaide.findall("forecast-period"):
        start_time = period.get("start-time-local")
        # Format usually "2026-03-29T15:00:00+10:30"
        
        min_temp_elem = period.find("element[@type='air_temperature_minimum']")
        max_temp_elem = period.find("element[@type='air_temperature_maximum']")
        precis_elem = period.find("text[@type='precis']")
        
        min_t = int(min_temp_elem.text) if min_temp_elem is not None and min_temp_elem.text else None
        max_t = int(max_temp_elem.text) if max_temp_elem is not None and max_temp_elem.text else None
        desc = precis_elem.text if precis_elem is not None else ""
        
        entries.append({
            "dt_txt": start_time,
            "min": min_t,
            "max": max_t,
            "desc": desc
        })

    return {"entries": entries}


def make_quad_forecast_image(forecast: dict, weather: dict) -> bytes:
    """Return PNG bytes of a 2x2 grid containing the temperature plots and radar images."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import re

    # 1. GENERATE 7-DAY PLOT (Bottom Left)
    entries = forecast.get("entries", [])
    dts = []
    mins = []
    maxs = []
    
    for entry in entries:
        try:
            dt = datetime.fromisoformat(entry["dt_txt"])
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
        except Exception:
            continue
        if entry["max"] is not None:
            dts.append(dt)
            mins.append(entry["min"] if entry["min"] is not None else entry["max"] - 5)
            maxs.append(entry["max"])

    if dts:
        fig1, ax1 = plt.subplots(figsize=(8, 5.12), dpi=100)
        ax1.plot(dts, maxs, marker='o', linestyle='-', color='#d62728', label='Max Temp (°C)')
        ax1.plot(dts, mins, marker='o', linestyle='-', color='#1f77b4', label='Min Temp (°C)')
        ax1.fill_between(dts, mins, maxs, color='gray', alpha=0.1)
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Temp (°C)")
        ax1.set_title("7‑Day Temperature Forecast")
        ax1.legend(loc="upper right")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%A\n%d %b'))
        ax1.xaxis.set_major_locator(mdates.DayLocator())
        fig1.autofmt_xdate(rotation=0, ha='center')
        fig1.tight_layout()
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format="png")
        plt.close(fig1)
        buf1.seek(0)
        img_7day = Image.open(buf1).convert("RGB").resize((800, 512))
    else:
        img_7day = Image.new("RGB", (800, 512), "white")

    # 2. GENERATE HOURLY PLOT (Top Left)
    img_hourly = Image.new("RGB", (800, 512), "white")
    try:
        hourly_summary = fetch_hourly_forecast_summary()
        hours = hourly_summary.get("hours", [])
        temps = hourly_summary.get("temps", [])
        adelaide_tz = ZoneInfo("Australia/Adelaide") if ZoneInfo is not None else timezone.utc
        current_time = datetime.now(timezone.utc).astimezone(adelaide_tz).replace(tzinfo=None)
        current_date = current_time.date()
        start_of_day = datetime(current_date.year, current_date.month, current_date.day)

        if hours:
            fig2, ax2 = plt.subplots(figsize=(8, 5.12), dpi=100)
            ax2.plot(hours, temps, marker='o', linestyle='-', color='#ff7f0e')

            # Add vertical line for current time
            ax2.axvline(x=current_time, color='magenta', linestyle='--', linewidth=2, label='Current Time')
            ax2.legend(loc="upper right")

            # Set hard limits for 12am to 12am next day
            ax2.set_xlim(start_of_day, start_of_day + timedelta(days=1))
            ax2.set_xlabel("Time (Current Day)")
            ax2.set_ylabel("Temp (°C)")
            ax2.set_title("Current Day Expected Temperature")
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%I %p'))
            ax2.xaxis.set_major_locator(mdates.HourLocator(interval=3))
            fig2.autofmt_xdate(rotation=45, ha='right')
            fig2.tight_layout()
            buf2 = io.BytesIO()
            fig2.savefig(buf2, format="png")
            plt.close(fig2)
            buf2.seek(0)
            img_hourly = Image.open(buf2).convert("RGB").resize((800, 512))
    except Exception as e:
        print(f"⚠️  Failed to generate hourly plot: {e}")

    # 3. HELPER TO FETCH RADAR (Top Right / Bottom Right)
    def fetch_radar(radar_id):
        headers = {"User-Agent": "Mozilla/5.0"}
        def fetch_pil(u):
            r = session.get(u, headers=headers, timeout=10)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
        try:
            bg = fetch_pil("https://www.bom.gov.au/products/radar_transparencies/IDR463.background.png")
            topo = fetch_pil("https://www.bom.gov.au/products/radar_transparencies/IDR463.topography.png")
            loc = fetch_pil("https://www.bom.gov.au/products/radar_transparencies/IDR463.locations.png")
            
            loop_url = f"https://reg.bom.gov.au/products/{radar_id}.loop.shtml"
            html = session.get(loop_url, headers=headers, timeout=10).text
            matches = re.findall(r'theImageNames\[\d+\]\s*=\s*"([^"]+)";', html)
            
            if matches:
                sweep = fetch_pil("https://reg.bom.gov.au" + matches[-1])
            else:
                sweep = Image.new("RGBA", (512, 512), (0,0,0,0))
                
            canvas = Image.alpha_composite(bg, topo)
            canvas = Image.alpha_composite(canvas, sweep)
            canvas = Image.alpha_composite(canvas, loc)
            return canvas.convert("RGB").resize((512, 512))
        except Exception as err:
            print(f"⚠️  Failed to fetch radar {radar_id}: {err}")
            return Image.new("RGB", (512, 512), "white")

    radar_now = fetch_radar("IDR463")
    radar_24h = fetch_radar("IDR46D")

    # 4. FETCH EXTRA DATA FOR PANELS
    try:
        hourly_summary = fetch_hourly_forecast_summary()
        rain_last_24h = estimate_rain_last_24h(weather.get("history", []))
        current_wind = safe_float(weather.get("wind_spd_kmh"))
        current_wind_dir = weather.get("wind_dir") or "-"

        temps_today = hourly_summary.get("temps", [])
        hours_today = hourly_summary.get("hours", [])
        max_t = min_t = max_time = min_time = None
        if temps_today and len(temps_today) == len(hours_today):
            max_t = max(temps_today)
            min_t = min(temps_today)
            max_idx = temps_today.index(max_t)
            min_idx = temps_today.index(min_t)
            max_time = hours_today[max_idx].strftime("%I %p").lstrip("0")
            min_time = hours_today[min_idx].strftime("%I %p").lstrip("0")

        current_temp = safe_float(weather.get("air_temp"))

        temp_panel = render_sidebar_panel(
            "TEMP",
            [
                {
                    "label": "Current",
                    "value": f"{current_temp:.1f}°C" if current_temp is not None else "N/A",
                    "detail": "Measured now",
                },
                {
                    "label": "High today",
                    "value": f"{max_t:.1f}°C" if max_t is not None else "N/A",
                    "detail": f"Around {max_time}" if max_time else "Expected maximum",
                },
                {
                    "label": "Low today",
                    "value": f"{min_t:.1f}°C" if min_t is not None else "N/A",
                    "detail": f"Around {min_time}" if min_time else "Expected minimum",
                },
            ],
            512
        )

        wind_panel = render_sidebar_panel(
            "WIND",
            [
                {
                    "label": "Current",
                    "value": f"{int(current_wind)} km/h" if current_wind is not None else "N/A",
                    "detail": current_wind_dir,
                },
                {
                    "label": "Low today",
                    "value": f"{hourly_summary['wind_min']:.0f} km/h" if hourly_summary.get("wind_min") is not None else "N/A",
                    "detail": "Expected minimum",
                },
                {
                    "label": "High today",
                    "value": f"{hourly_summary['wind_max']:.0f} km/h" if hourly_summary.get("wind_max") is not None else "N/A",
                    "detail": "Expected maximum",
                },
            ],
            512
        )

        left_panel = Image.new("RGB", (SIDE_PANEL_WIDTH, 1024), "white")
        left_panel.paste(temp_panel, (0, 0))
        left_panel.paste(wind_panel, (0, 512))

        right_panel = render_sidebar_panel(
            "RAIN",
            [
                {
                    "label": "Last 24h",
                    "value": f"{rain_last_24h:.1f} mm" if rain_last_24h is not None else "N/A",
                    "detail": "From station history",
                },
                {
                    "label": "Next 24h",
                    "value": f"{hourly_summary['rain_next_24h']:.1f} mm" if hourly_summary.get("rain_next_24h") is not None else "N/A",
                    "detail": "Forecast amount",
                },
            ],
            1024
        )
    except Exception as e:
        print(f"⚠️  Failed to render side panels: {e}")
        left_panel = Image.new("RGB", (SIDE_PANEL_WIDTH, 1024), "white")
        right_panel = Image.new("RGB", (SIDE_PANEL_WIDTH, 1024), "white")

    # 5. COMPOSITE 2x2 QUAD + SIDE PANELS
    quad = Image.new("RGB", (1312 + SIDE_PANEL_WIDTH * 2, 1024), "white")
    
    # Left Panel
    quad.paste(left_panel, (0, 0))
    # 2x2 Grid
    quad.paste(img_hourly, (SIDE_PANEL_WIDTH, 0))                 # Top Left
    quad.paste(img_7day, (SIDE_PANEL_WIDTH, 512))                 # Bottom Left
    quad.paste(radar_now, (SIDE_PANEL_WIDTH + 800, 0))            # Top Right
    quad.paste(radar_24h, (SIDE_PANEL_WIDTH + 800, 512))          # Bottom Right
    # Right Panel
    quad.paste(right_panel, (SIDE_PANEL_WIDTH + 1312, 0))
    
    out = io.BytesIO()
    quad.save(out, format="PNG")
    out.seek(0)
    return out.read()


def post_to_discord(webhook_url: str, image_bytes: bytes, timestamp: datetime):
    import json
    time_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    size_mb = len(image_bytes) / 1024 / 1024

    # grab weather information; if it fails we'll let the exception bubble up
    weather = fetch_weather(WEATHER_URL)

    # try to obtain a forecast from BOM; it's okay if the
    # request fails, we can just omit that part of the message
    forecast_str = ""
    forecast_image = None
    try:
        fc = fetch_forecast()
        if fc and fc.get("entries"):
            # Show today and tomorrow in the discord text description
            parts = []
            for i, entry in enumerate(fc["entries"][:2]):
                desc = entry["desc"]
                max_t = f"{entry['max']}°C" if entry["max"] is not None else "?°C"
                if i == 0:
                    parts.append(f"Tonight/Rest of Today: {desc} Max {max_t}")
                else:
                    parts.append(f"Tomorrow: {desc} Max {max_t}")
                    
            if parts:
                forecast_str = "\n🔮 Forecast: " + " | ".join(parts)
                
            # generate full-image of 2x2 forecast quad
            try:
                forecast_image = make_quad_forecast_image(fc, weather)
            except Exception as ie:
                print(f"⚠️  Forecast image generation failed: {ie}")
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

    files = {"file": ("himawari.jpg", image_bytes, "image/jpeg")}
    if forecast_image:
        files["forecast"] = ("forecast.png", forecast_image, "image/png")

    # 1. Attempt to delete the previous message
    try:
        with open("last_message_id.txt", "r") as f:
            old_msg_id = f.read().strip()
        if old_msg_id:
            # We need to strip query params from the base url if any exist before appending /messages/{id}
            base_url = webhook_url.split("?")[0]
            delete_url = f"{base_url}/messages/{old_msg_id}"
            del_resp = session.delete(delete_url, timeout=10)
            if del_resp.status_code == 204:
                print(f"🗑️  Deleted previous message: {old_msg_id}")
            else:
                print(f"⚠️  Failed to delete previous message: {del_resp.status_code}")
    except FileNotFoundError:
        pass  # No previous message to delete
    except Exception as e:
        print(f"⚠️  Error deleting previous message: {e}")

    # 2. Post the new message (Note the wait=true param to get the message object back)
    post_url = f"{webhook_url}&wait=true" if "?" in webhook_url else f"{webhook_url}?wait=true"

    response = session.post(
        post_url,
        data={"payload_json": json.dumps(payload)},
        files=files,
        timeout=60
    )
    response.raise_for_status()

    # 3. Save the new message ID for next time
    try:
        new_message_data = response.json()
        new_msg_id = new_message_data.get('id')
        if new_msg_id:
            with open("last_message_id.txt", "w") as f:
                f.write(new_msg_id)
            print(f"✅ Saved new message ID: {new_msg_id}")
    except Exception as e:
        print(f"⚠️  Failed to parse new message ID: {e}")

    print(f"✅ Posted successfully! ({size_mb:.1f}MB)")


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: DISCORD_WEBHOOK_URL environment variable not set.")
        sys.exit(1)

    timestamp = find_valid_timestamp()
    image_bytes = build_full_disk(timestamp)
    post_to_discord(webhook_url, image_bytes, timestamp)


if __name__ == "__main__":
    main()