"""Små geohjälpare utan externa paket: SWEREF 99 TM, sol-tider och svensk lokaltid."""
import math
from datetime import datetime, timedelta, timezone


# ---------- WGS84 -> SWEREF 99 TM (Lantmäteriets Gauss–Krüger-formler) ----------
def wgs84_to_sweref99tm(lat, lon):
    a, f = 6378137.0, 1 / 298.257222101          # GRS 80
    lon0, k0, fn, fe = math.radians(15.0), 0.9996, 0.0, 500000.0
    e2 = f * (2 - f)
    n = f / (2 - f)
    ah = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    A = e2
    B = (5 * e2 ** 2 - e2 ** 3) / 6
    C = (104 * e2 ** 3 - 45 * e2 ** 4) / 120
    D = (1237 * e2 ** 4) / 1260
    b1 = n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180
    b2 = 13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440
    b3 = 61 * n ** 3 / 240 - 103 * n ** 4 / 140
    b4 = 49561 * n ** 4 / 161280
    phi, lam = math.radians(lat), math.radians(lon)
    s = math.sin(phi)
    phis = phi - s * math.cos(phi) * (A + B * s ** 2 + C * s ** 4 + D * s ** 6)
    dl = lam - lon0
    xi = math.atan(math.tan(phis) / math.cos(dl))
    eta = math.atanh(math.cos(phis) * math.sin(dl))
    x = k0 * ah * (xi + b1 * math.sin(2 * xi) * math.cosh(2 * eta) + b2 * math.sin(4 * xi) * math.cosh(4 * eta)
                   + b3 * math.sin(6 * xi) * math.cosh(6 * eta) + b4 * math.sin(8 * xi) * math.cosh(8 * eta)) + fn
    y = k0 * ah * (eta + b1 * math.cos(2 * xi) * math.sinh(2 * eta) + b2 * math.cos(4 * xi) * math.sinh(4 * eta)
                   + b3 * math.cos(6 * xi) * math.sinh(6 * eta) + b4 * math.cos(8 * xi) * math.sinh(8 * eta)) + fe
    return round(y), round(x)   # (Ost/E, Nord/N) i meter


# ---------- svensk lokaltid (CET/CEST) utan tzdata ----------
def _last_sunday(year, month):
    d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def se_offset(utc_dt):
    """Timmar före UTC för Sverige vid given UTC-tid (1 eller 2)."""
    y = utc_dt.year
    start = _last_sunday(y, 3).replace(hour=1, tzinfo=timezone.utc)
    end = _last_sunday(y, 10).replace(hour=1, tzinfo=timezone.utc)
    return 2 if start <= utc_dt < end else 1


def utc_to_local(utc_dt):
    return (utc_dt + timedelta(hours=se_offset(utc_dt))).replace(tzinfo=None)


def local_to_utc(local_dt):
    guess = local_dt.replace(tzinfo=timezone.utc) - timedelta(hours=1)
    return local_dt.replace(tzinfo=timezone.utc) - timedelta(hours=se_offset(guess))


# ---------- solnedgång/soluppgång (NOAA, ±1–2 min) ----------
def _sun_event(date, lat, lon, rising, zenith=90.833):
    N = date.timetuple().tm_yday
    lng_hour = lon / 15
    t = N + ((6 if rising else 18) - lng_hour) / 24
    M = 0.9856 * t - 3.289
    L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    RA = (RA + (math.floor(L / 90) * 90 - math.floor(RA / 90) * 90)) / 15
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
    if not -1 <= cos_h <= 1:
        return None
    H = (360 - math.degrees(math.acos(cos_h)) if rising else math.degrees(math.acos(cos_h))) / 15
    T = H + RA - 0.06571 * t - 6.622
    UT = (T - lng_hour) % 24
    return datetime(date.year, date.month, date.day, tzinfo=timezone.utc) + timedelta(hours=UT)


def night_window(night_date, lat, lon):
    """(solnedgång, soluppgång) som UTC-datetimes för natten som börjar night_date."""
    ss = _sun_event(night_date, lat, lon, rising=False)
    sr = _sun_event(night_date + timedelta(days=1), lat, lon, rising=True)
    return ss, sr
