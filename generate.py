"""Draw the Kindle dashboard from the files in data/.

Layout (600x800, 1-bit black & white), top to bottom:
    date / updated time
    weather now + today        (data/weather.json)
    4-day forecast             (data/weather.json)
    AI usage, Codex + Claude   (data/codex.json, data/claude.json)
    AerisIQ map status         (data/aerisiq.json)

Options (mainly for testing):
    --data DIR     read the JSON files from DIR (default: ./data)
    --out FILE     write the image here (default: ./dashboard.png)
    --now ISO      pretend the current time is ISO (e.g. 2026-11-17T15:00:00+00:00)
"""

import argparse
import functools
import json
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("America/Chicago")
W, H = 600, 800
M = 30                   # left/right margin
BLACK, WHITE = 0, 255
STALE_AFTER_MIN = 25     # show "as of ..." when the last good data is older than this
LATE_AFTER_H = 24        # AerisIQ: a live run older than this is LATE


# ---------- fonts & text ----------

@functools.lru_cache(maxsize=None)
def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(os.path.join(HERE, "fonts", name), size)


def text(d, xy, s, size, bold=False, anchor="la", fill=BLACK):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)


def fit(d, s, max_w, size, bold=False, min_size=14):
    """Largest font size <= size that fits max_w; truncate with … if needed."""
    while size > min_size and d.textlength(s, font=font(size, bold)) > max_w:
        size -= 1
    while len(s) > 1 and d.textlength(s, font=font(size, bold)) > max_w:
        s = s[:-2] + "…"
    return s, size


# ---------- time formatting ----------

def clock(dt):
    return f"{dt.hour % 12 or 12}:{dt:%M} {dt:%p}"


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ) if s else None


def when_past(dt, now):
    """'9:58 AM' today, 'yesterday 11:58 PM', else 'Mon Nov 16, 1:02 AM'."""
    days = (now.date() - dt.date()).days
    if days == 0:
        return clock(dt)
    if days == 1:
        return f"yesterday {clock(dt)}"
    return f"{dt:%a %b} {dt.day}, {clock(dt)}"


def when_ahead(dt, now):
    """Compact future time: '2:20 PM' today, 'Sat 4:00 AM' this week, else 'Nov 24 12:34 AM'."""
    days = (dt.date() - now.date()).days
    if days == 0:
        return clock(dt)
    if days < 7:
        return f"{dt:%a} {clock(dt)}"
    return f"{dt:%b} {dt.day} {clock(dt)}"


def ago(dt, now):
    minutes = max(0, (now - dt).total_seconds() / 60)
    if minutes < 60:
        return f"{minutes:.0f} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.0f} h ago"
    return f"{minutes / 1440:.0f} d ago"


def stale_note(data, now):
    """'' when fresh, otherwise a short note about how old the data is."""
    if not data:
        return "no data yet"
    last_ok = parse_iso(data.get("lastOkAt"))
    if last_ok is None:
        return "unavailable"
    if not data.get("ok") or (now - last_ok).total_seconds() / 60 > STALE_AFTER_MIN:
        return f"as of {when_past(last_ok, now)}"
    return ""


# ---------- weather icons (simple line drawings, scale with s) ----------

def _cloud(d, cx, cy, s, lw):
    """Outlined cloud, white inside (so it can sit on top of a sun)."""
    parts = [(-0.24, 0.06, 0.18), (0.0, -0.08, 0.25), (0.24, 0.08, 0.16)]
    for inset, color in ((0, BLACK), (lw, WHITE)):
        for dx, dy, r in parts:
            rr = r * s - inset
            d.ellipse((cx + dx * s - rr, cy + dy * s - rr, cx + dx * s + rr, cy + dy * s + rr), fill=color)
        d.rectangle((cx - 0.24 * s, cy + 0.06 * s, cx + 0.24 * s, cy + 0.24 * s - inset), fill=color)


def _sun(d, cx, cy, s, lw):
    r = 0.2 * s
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=BLACK, width=lw)
    for i in range(8):
        a = i * math.pi / 4
        d.line((cx + math.cos(a) * 0.3 * s, cy + math.sin(a) * 0.3 * s,
                cx + math.cos(a) * 0.44 * s, cy + math.sin(a) * 0.44 * s), fill=BLACK, width=lw)


def _moon(d, cx, cy, s, lw):
    r = 0.3 * s
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLACK)
    ox, oy = cx + 0.16 * s, cy - 0.12 * s
    d.ellipse((ox - r, oy - r, ox + r, oy + r), fill=WHITE)


def draw_icon(d, kind, cx, cy, s):
    lw = max(2, round(s / 18))
    if kind == "sun":
        _sun(d, cx, cy, s, lw)
    elif kind == "moon":
        _moon(d, cx, cy, s, lw)
    elif kind in ("partly_day", "partly_night"):
        (_sun if kind == "partly_day" else _moon)(d, cx - 0.16 * s, cy - 0.16 * s, 0.7 * s, lw)
        _cloud(d, cx + 0.08 * s, cy + 0.1 * s, 0.8 * s, lw)
    elif kind == "cloud":
        _cloud(d, cx, cy, s, lw)
    elif kind == "fog":
        for dy, half in ((-0.18, 0.36), (-0.06, 0.28), (0.06, 0.36), (0.18, 0.24)):
            d.line((cx - half * s, cy + dy * s, cx + half * s, cy + dy * s), fill=BLACK, width=lw)
    else:  # rain, snow, storm: cloud on top, something falling below
        top = cy - 0.12 * s
        _cloud(d, cx, top, s, lw)
        if kind == "rain":
            for dx in (-0.18, 0.0, 0.18):
                x = cx + dx * s
                d.line((x + 0.05 * s, cy + 0.2 * s, x - 0.03 * s, cy + 0.4 * s), fill=BLACK, width=lw)
        elif kind == "snow":
            for dx in (-0.2, 0.0, 0.2):
                x, y, r = cx + dx * s, cy + 0.32 * s, 0.07 * s
                for a in (0, math.pi / 3, 2 * math.pi / 3):
                    d.line((x - math.cos(a) * r, y - math.sin(a) * r,
                            x + math.cos(a) * r, y + math.sin(a) * r), fill=BLACK, width=max(2, lw - 1))
        else:  # storm
            bolt = [(0.04, 0.14), (-0.1, 0.32), (0.0, 0.32), (-0.06, 0.48), (0.12, 0.26), (0.02, 0.26)]
            d.polygon([(cx + x * s, cy + y * s) for x, y in bolt], fill=BLACK)


def condition(code, is_day=True):
    """WMO weather code -> (short label, icon kind)."""
    clear = "sun" if is_day else "moon"
    partly = "partly_day" if is_day else "partly_night"
    table = {
        0: ("Clear", clear), 1: ("Mostly clear", clear), 2: ("Partly cloudy", partly),
        3: ("Cloudy", "cloud"), 45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
        51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
        56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
        61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
        66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
        71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"),
        77: ("Snow grains", "snow"), 80: ("Showers", "rain"), 81: ("Showers", "rain"),
        82: ("Heavy showers", "rain"), 85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
        95: ("Thunderstorm", "storm"), 96: ("Storm, hail", "storm"), 99: ("Storm, hail", "storm"),
    }
    return table.get(code, ("Unknown", "cloud"))


def deg(x):
    return "–" if x is None else f"{int(round(x))}°"


def compass(degrees):
    if degrees is None:
        return ""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(degrees / 45) % 8]


# ---------- sections ----------

def draw_header(d, now):
    text(d, (M, 14), f"{now:%A}, {now:%b} {now.day}", 28, bold=True)
    text(d, (W - M, 37), f"Updated {clock(now)}", 20, anchor="rs")
    d.line((M, 56, W - M, 56), fill=BLACK, width=3)


def draw_weather(d, y, data, now):
    """Current weather + today's range. Returns nothing; occupies y .. y+150."""
    weather = (data or {}).get("weather")
    note = stale_note(data, now)
    if not weather:
        text(d, (M, y + 50), "Weather unavailable", 30, bold=True)
        text(d, (M, y + 92), note, 22)
        return
    if note:
        text(d, (W - M, y + 6), note, 16, anchor="ra")

    c, today = weather["current"], weather["days"][0]
    label, icon = condition(c["code"], c["isDay"])
    draw_icon(d, icon, M + 48, y + 64, 96)

    temp = f"{deg(c['temp'])}C"
    text(d, (M + 108, y + 18), temp, 72, bold=True)
    xr = max(345, M + 108 + d.textlength(temp, font=font(72, True)) + 18)
    s, size = fit(d, label, W - M - xr, 30, bold=True)
    text(d, (xr, y + 18), s, size, bold=True)
    # Everything in this column is "now"; the Today line below is the whole day.
    now_lines = [f"feels {deg(c['feels'])}"]
    if c.get("wind") is not None:
        now_lines.append(f"wind {c['wind']:.0f} km/h {compass(c['windDir'])}")
    if c.get("humidity") is not None:
        now_lines.append(f"humidity {c['humidity']}%")
    for i, line in enumerate(now_lines):
        text(d, (xr, y + 54 + i * 26), line, 22)

    rain = "–" if today["rain"] is None else f"{today['rain']}%"
    text(d, (M, y + 138), f"Today  H {deg(today['max'])}  L {deg(today['min'])}   rain {rain}", 22)


def draw_forecast(d, y, data, now):
    weather = (data or {}).get("weather")
    if not weather:
        return
    days = weather["days"][1:5]
    col_w = (W - 2 * M) / len(days)
    for i, day in enumerate(days):
        cx = M + col_w * (i + 0.5)
        date = datetime.strptime(day["date"], "%Y-%m-%d")
        text(d, (cx, y + 10), f"{date:%a}".upper(), 22, bold=True, anchor="ma")
        draw_icon(d, condition(day["code"])[1], cx, y + 68, 58)
        text(d, (cx, y + 104), f"{deg(day['max'])} / {deg(day['min'])}", 24, bold=True, anchor="ma")
        rain = "–" if day["rain"] is None else f"{day['rain']}%"
        text(d, (cx, y + 134), f"rain {rain}", 18, anchor="ma")


def draw_usage_cell(d, x, y, w, win, now):
    if not win:
        text(d, (x + w, y + 27), "n/a", 26, bold=True, anchor="rs")
        return
    used = win["usedPercent"]
    resets = datetime.fromtimestamp(win["resetsAt"], TZ) if win.get("resetsAt") is not None else None
    if resets is not None and resets <= now:
        used, note = 0.0, f"reset at {clock(resets)}"   # old data from before the reset
    elif resets is not None:
        note = f"resets {when_ahead(resets, now)}"
    else:
        note = "not started"
    left = 100.0 - used

    bar_w = 108
    d.rectangle((x, y + 4, x + bar_w, y + 28), outline=BLACK, width=2)
    fill_w = round((bar_w - 8) * left / 100)
    if fill_w > 0:
        d.rectangle((x + 4, y + 8, x + 4 + fill_w, y + 24), fill=BLACK)
    text(d, (x + w, y + 28), f"{left:.0f}%", 26, bold=True, anchor="rs")
    s, size = fit(d, note, w, 18)
    text(d, (x, y + 38), s, size)


def draw_usage(d, y, codex, claude, now):
    col1, col2, col_w = 166, 386, W - M - 386
    text(d, (M, y + 12), "AI USAGE", 22, bold=True)
    text(d, (col1, y + 16), "5-HOUR LEFT", 17, bold=True)
    text(d, (col2, y + 16), "WEEKLY LEFT", 17, bold=True)
    for i, (name, data) in enumerate((("Codex", codex), ("Claude", claude))):
        ry = y + 50 + i * 76
        text(d, (M, ry + 2), name, 26, bold=True)
        note = stale_note(data, now)
        if note:
            s, size = fit(d, note, col1 - M - 8, 16)
            text(d, (M, ry + 38), s, size)
        windows = (data or {}).get("windows") or {}
        draw_usage_cell(d, col1, ry, col_w, windows.get("five_hour"), now)
        draw_usage_cell(d, col2, ry, col_w, windows.get("weekly"), now)


def aerisiq_view(data, now):
    """-> (status, problem line or None, run dict or None, run 'last seen' note)."""
    if not data:
        return "DOWN", "no check has run yet", None, ""
    run = data.get("run")
    if data.get("ok"):
        status, problem = data.get("status", "DOWN"), data.get("problem")
    else:
        status, problem = "ERROR", f"checker failed: {data.get('error')}"

    if status == "OK" and run:
        start = datetime.strptime(run["runId"], "%Y-%m-%d_%H:%M:%S").replace(tzinfo=timezone.utc)
        age_h = (now - start).total_seconds() / 3600
        if age_h > LATE_AFTER_H:
            status, problem = "LATE", f"Run started {age_h:.0f} h ago (limit {LATE_AFTER_H} h)"

    note = stale_note(data, now)
    if note and problem is None:
        problem = f"Last check {note.removeprefix('as of ')}"

    seen = ""
    if run and data.get("runSeenAt") != data.get("fetchedAt") and data.get("runSeenAt"):
        seen = f"last seen {when_past(parse_iso(data['runSeenAt']), now)}"
    return status, problem, run, seen


def draw_aerisiq(d, y, data, now):
    status, problem, run, seen = aerisiq_view(data, now)
    text(d, (M, y + 14), "AERISIQ MAP", 24, bold=True)

    # "Status: OK", problems as a black badge with white text
    label_font = font(22)
    value_font = font(24, True)
    vw = d.textlength(status, font=value_font)
    if status == "OK":
        text(d, (W - M, y + 36), status, 24, bold=True, anchor="rs")
        x_label = W - M - vw - 8
    else:
        pad = 10
        box = (W - M - vw - 2 * pad, y + 8, W - M, y + 44)
        d.rounded_rectangle(box, radius=6, fill=BLACK)
        text(d, (W - M - pad, y + 36), status, 24, bold=True, anchor="rs", fill=WHITE)
        x_label = box[0] - 8
    d.text((x_label, y + 36), "Status:", font=label_font, fill=BLACK, anchor="rs")

    value_x = M + 150
    text(d, (M, y + 64), "Current run", 22)
    text(d, (M, y + 100), "Published", 22)
    if run:
        start = datetime.strptime(run["runId"], "%Y-%m-%d_%H:%M:%S")
        run_label = f"{start:%b} {start.day} {start:%H}z"
        text(d, (value_x, y + 64), run_label, 22, bold=True)
        if seen:
            sx = value_x + d.textlength(run_label, font=font(22, True)) + 12
            s, size = fit(d, f"({seen})", W - M - sx, 18)
            text(d, (sx, y + 67), s, size)
        published = parse_iso(run.get("publishedAt"))
        if published:
            s, size = fit(d, f"{when_past(published, now)}  ({ago(published, now)})", W - M - value_x, 22)
            text(d, (value_x, y + 100), s, size)
    else:
        text(d, (value_x, y + 64), "unknown", 22, bold=True)
    if problem:
        s, size = fit(d, problem, W - 2 * M, 20)
        text(d, (M, y + 136), s, size, bold=True)


def load(data_dir, source):
    try:
        with open(os.path.join(data_dir, f"{source}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def render(data_dir, now):
    im = Image.new("L", (W, H), WHITE)
    d = ImageDraw.Draw(im)

    draw_header(d, now)
    weather = load(data_dir, "weather")
    draw_weather(d, 62, weather, now)
    d.line((M, 228, W - M, 228), fill=BLACK, width=1)
    draw_forecast(d, 232, weather, now)
    d.line((M, 394, W - M, 394), fill=BLACK, width=3)
    draw_usage(d, 400, load(data_dir, "codex"), load(data_dir, "claude"), now)
    d.line((M, 590, W - M, 590), fill=BLACK, width=3)
    draw_aerisiq(d, 596, load(data_dir, "aerisiq"), now)

    # Plain threshold (no dithering) keeps text edges clean on e-ink.
    return im.convert("1", dither=Image.Dither.NONE)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=os.path.join(HERE, "data"))
    parser.add_argument("--out", default=os.path.join(HERE, "dashboard.png"))
    parser.add_argument("--now", help="ISO time to use instead of the current time")
    args = parser.parse_args()

    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc).astimezone(TZ)
    image = render(args.data, now)

    tmp = args.out + ".tmp.png"
    image.save(tmp, optimize=True)
    size = os.path.getsize(tmp)
    if size >= 1024 * 1024:
        os.remove(tmp)
        raise SystemExit(f"image too large: {size} bytes")
    os.replace(tmp, args.out)
    print(f"generated {args.out} ({size} bytes)")


if __name__ == "__main__":
    main()
