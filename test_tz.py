import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

adelaide_tz = ZoneInfo("Australia/Adelaide")
dt = datetime.fromisoformat("2026-03-29T06:00:00+00:00").astimezone(adelaide_tz)

print("Aware dt:", dt)
print("Naive dt:", dt.replace(tzinfo=None))
