"""Read current weather + 4-day forecast from Open-Meteo and save data/weather.json.

Location comes from WEATHER_LAT / WEATHER_LON in .env. Open-Meteo is free and
needs no API key. Units: °C and km/h.

The city name for those coordinates is looked up online (OpenStreetMap
Nominatim reverse geocoding) and cached in data/place.json. It is asked again
only when the coordinates change, as Nominatim's usage policy requires caching.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode

from common import DATA_DIR, http_get, read_env, run_collector

FORECAST_DAYS = 4  # days after today
PLACE_CACHE = os.path.join(DATA_DIR, "place.json")


def lookup_place(lat, lon):
    """City name like 'Springfield, IL' for the coordinates, or '' if unknown. Never raises."""
    key = f"{lat},{lon}"
    try:
        with open(PLACE_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if cache.get("key") == key and cache.get("name"):
        return cache["name"]

    query = urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10,
                       "addressdetails": 1, "accept-language": "en"})
    try:
        status, body, _ = http_get(f"https://nominatim.openstreetmap.org/reverse?{query}")
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        address = json.loads(body).get("address") or {}
    except (OSError, ValueError, RuntimeError) as e:
        print(f"weather: place lookup failed ({e}), no city name this time", file=sys.stderr)
        return ""

    city = next((address[k] for k in ("city", "town", "village", "hamlet", "municipality",
                                      "county") if address.get(k)), "")
    if address.get("country_code") == "us":
        region = address.get("ISO3166-2-lvl4", "").removeprefix("US-")  # "US-IL" -> "IL"
    else:
        region = address.get("country", "")
    name = ", ".join(part for part in (city, region) if part)
    if name:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PLACE_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"key": key, "name": name, "source": "OpenStreetMap Nominatim",
                       "lookedUpAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}, f)
        os.replace(PLACE_CACHE + ".tmp", PLACE_CACHE)
        print(f"weather: looked up place name: {name}")
    return name


def fetch(previous):
    env = read_env()
    query = urlencode({
        "latitude": env["WEATHER_LAT"],
        "longitude": env["WEATHER_LON"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "weather_code,wind_speed_10m,wind_direction_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max",
        "timezone": "America/Chicago",
        "forecast_days": FORECAST_DAYS + 1,  # today + the next days
        "wind_speed_unit": "kmh",
    })
    status, body, _ = http_get(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=20)
    if status != 200:
        raise RuntimeError(f"Open-Meteo HTTP {status}: {body[:120]!r}")
    data = json.loads(body)

    c, d = data["current"], data["daily"]
    if c.get("temperature_2m") is None:
        raise RuntimeError("no current temperature in the response")
    current = {
        "time": c["time"],
        "temp": c["temperature_2m"],
        "feels": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"),
        "code": c.get("weather_code"),
        "wind": c.get("wind_speed_10m"),
        "windDir": c.get("wind_direction_10m"),
        "isDay": bool(c.get("is_day", 1)),
    }
    days = [
        {"date": d["time"][i],
         "code": d["weather_code"][i],
         "max": d["temperature_2m_max"][i],
         "min": d["temperature_2m_min"][i],
         "rain": d["precipitation_probability_max"][i]}
        for i in range(len(d["time"]))
    ]
    if len(days) < FORECAST_DAYS + 1:
        raise RuntimeError(f"only {len(days)} forecast days in the response")
    place = lookup_place(env["WEATHER_LAT"], env["WEATHER_LON"])
    return {"weather": {"place": place, "current": current, "days": days}}


def describe(payload):
    c, today = payload["weather"]["current"], payload["weather"]["days"][0]
    t = lambda x: "?" if x is None else int(round(x))  # int() avoids printing "-0"
    return (f"now {t(c['temp'])}°C (code {c['code']}), "
            f"today {t(today['max'])}/{t(today['min'])}°C, "
            f"{len(payload['weather']['days']) - 1} forecast days")


if __name__ == "__main__":
    sys.exit(run_collector("weather", fetch, describe))
