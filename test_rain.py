import post_himawari
import json
headers = {"User-Agent": "Mozilla/5.0"}
r = post_himawari.session.get("https://api.weather.bom.gov.au/v1/locations/r1f90q/forecasts/hourly", headers=headers)
data = r.json()
with open("dump.json", "w") as f:
    json.dump(data, f, indent=2)
