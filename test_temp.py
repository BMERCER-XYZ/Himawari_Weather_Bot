import post_himawari
weather = post_himawari.fetch_weather(post_himawari.WEATHER_URL)
hourly_summary = post_himawari.fetch_hourly_forecast_summary()

temps_today = hourly_summary.get("temps", [])
hours_today = hourly_summary.get("hours", [])

if temps_today:
    max_t = max(temps_today)
    min_t = min(temps_today)
    max_idx = temps_today.index(max_t)
    min_idx = temps_today.index(min_t)
    max_time = hours_today[max_idx].strftime("%I %p").lstrip("0")
    min_time = hours_today[min_idx].strftime("%I %p").lstrip("0")
    print(f"Max: {max_t} at {max_time}")
    print(f"Min: {min_t} at {min_time}")
else:
    print("No temps_today")

print(f"Current: {weather.get('air_temp')}C")
