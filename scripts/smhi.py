"""Väder från SMHI:s öppna observationsdata (metobs) för en natt och en lokal.

Hämtar timvärden från närmaste aktiva station per parameter. De senaste ~4
månaderna kommer från 'latest-months' (ej slutgiltigt kvalitetsgranskat),
äldre nätter från 'corrected-archive'.
"""
import csv, io, json, math, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

from geo import night_window, utc_to_local

API = "https://opendata-download-metobs.smhi.se/api/version/1.0"
UA = {"User-Agent": "bat-fynd/1.0 (github.com/ulfboge/bat)"}
PARAMS = {  # nyckel -> (SMHI-parameter, beskrivning, maxavstånd km)
    "temp": (1, "Lufttemperatur, °C", 40),
    "wind": (4, "Vindhastighet medel 10 min, m/s", 40),
    "precip": (7, "Nederbörd per timme, mm", 40),
    "cloud": (16, "Total molnmängd, %", 60),
    "humidity": (6, "Relativ luftfuktighet, %", 40),
}
_station_lists, _series = {}, {}


def _get(url, as_json=True):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
                return json.loads(data) if as_json else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    print("  ! SMHI misslyckades:", url, file=sys.stderr)
    return None


def _dist_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def _stations(param, lat, lon, when_ms, max_km):
    """Stationer med data vid tidpunkten, sorterade efter avstånd."""
    if param not in _station_lists:
        _station_lists[param] = (_get(f"{API}/parameter/{param}.json") or {}).get("station", [])
    out = []
    for s in _station_lists[param]:
        if s.get("from", 0) <= when_ms <= s.get("to", 0):
            d = _dist_km(lat, lon, s["latitude"], s["longitude"])
            if d <= max_km:
                out.append((d, s))
    return sorted(out, key=lambda x: x[0])


def _series_for(param, station, start, end):
    """Dict {utc-timme: värde} för stationen, från rätt period."""
    key = (param, station, start.date() < (datetime.now(timezone.utc) - timedelta(days=100)).date())
    if key not in _series:
        vals = {}
        if not key[2]:
            d = _get(f"{API}/parameter/{param}/station/{station}/period/latest-months/data.json") or {}
            for v in d.get("value") or []:
                try:
                    vals[datetime.fromtimestamp(v["date"] / 1000, tz=timezone.utc)] = float(v["value"])
                except (TypeError, ValueError):
                    pass
        else:
            txt = _get(f"{API}/parameter/{param}/station/{station}/period/corrected-archive/data.csv", as_json=False) or ""
            for row in csv.reader(io.StringIO(txt), delimiter=";"):
                if len(row) >= 3 and len(row[0]) == 10 and row[0][4] == "-" and ":" in row[1]:
                    try:
                        t = datetime.strptime(row[0] + " " + row[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        vals[t] = float(row[2])
                    except ValueError:
                        pass
        _series[key] = vals
    return _series[key]


def night_weather(night_date, lat, lon):
    """Timvärden från en timme före solnedgång till en timme efter soluppgång + sammanfattning."""
    ss, sr = night_window(night_date, lat, lon)
    start = (ss - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end = sr + timedelta(hours=1)
    hours = []
    t = start
    while t <= end:
        hours.append(t)
        t += timedelta(hours=1)
    out = {"sunset": utc_to_local(ss).strftime("%Y-%m-%dT%H:%M"), "sunrise": utc_to_local(sr).strftime("%Y-%m-%dT%H:%M"),
           "hours": [utc_to_local(h).strftime("%Y-%m-%dT%H:%M") for h in hours], "stations": {}}
    mid_ms = int(ss.timestamp() * 1000)
    for key, (param, label, max_km) in PARAMS.items():
        series = None
        for dist, st in _stations(param, lat, lon, mid_ms, max_km)[:3]:
            vals = _series_for(param, st["key"], start, end)
            got = [vals.get(h) for h in hours]
            if sum(v is not None for v in got) >= len(hours) * 0.6:
                series = got
                out["stations"][key] = {"name": st["name"], "id": st["key"], "km": round(dist, 1), "label": label}
                break
        out[key] = series

    night = [i for i, h in enumerate(hours) if ss <= h <= sr]
    def vals(k, idx):
        return [out[k][i] for i in idx if out.get(k) and out[k][i] is not None]
    def near(k, when):
        if not out.get(k):
            return None
        i = min(range(len(hours)), key=lambda j: abs((hours[j] - when).total_seconds()))
        return out[k][i]
    tn, wn, pn, cn = vals("temp", night), vals("wind", night), vals("precip", night), vals("cloud", night)
    out["summary"] = {
        "tempSunset": near("temp", ss),
        "tempMin": min(tn) if tn else None,
        "windMean": round(sum(wn) / len(wn), 1) if wn else None,
        "windMax": max(wn) if wn else None,
        "precipSum": round(sum(pn), 1) if pn else None,
        "cloudMean": round(sum(cn) / len(cn)) if cn else None,
    }
    out["complete"] = end < datetime.now(timezone.utc) - timedelta(hours=3) and out.get("temp") is not None
    return out
