"""Read current weather + 4-day forecast from Open-Meteo and save data/weather.json.

Location comes from WEATHER_LAT / WEATHER_LON in .env. Open-Meteo is free and
needs no API key. Units: °C and km/h.
"""

import json
import sys
from urllib.parse import urlencode

from common import http_get, read_env, run_collector

FORECAST_DAYS = 4  # days after today


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
    return {"weather": {"current": current, "days": days}}


def describe(payload):
    c, today = payload["weather"]["current"], payload["weather"]["days"][0]
    t = lambda x: "?" if x is None else int(round(x))  # int() avoids printing "-0"
    return (f"now {t(c['temp'])}°C (code {c['code']}), "
            f"today {t(today['max'])}/{t(today['min'])}°C, "
            f"{len(payload['weather']['days']) - 1} forecast days")


if __name__ == "__main__":
    sys.exit(run_collector("weather", fetch, describe))
