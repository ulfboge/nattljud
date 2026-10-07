"""eBird: läser nedladdade CSV-filer i mappen eBird/ (eller data/ebird/).

Två format känns igen:
- Livslista (ebird_world_life_list.csv från "Life list" → Download): en rad per art med första fyndet –
  lokalnamn, region och datum men inga koordinater.
- Alla fynd (MyEBirdData.csv från ebird.org/downloadMyData): en rad per art och checklista, med
  koordinater och tid. Finns båda för samma art används de fullständiga fynden.
"""
import csv
import glob
import os
from datetime import datetime


def _date(s):
    for f in ("%d %b %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _time(s):
    for f in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(s.strip(), f).strftime("%H:%M")
        except ValueError:
            pass
    return ""


def read(folders):
    """Lista med {sci, date, time, lat, lon, place, region, count, sub, kind} – kind = 'life' eller 'obs'."""
    life, obs = [], []
    for folder in folders:
        for f in sorted(glob.glob(os.path.join(folder, "*.csv"))):
            with open(f, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            if not rows:
                continue
            cols = rows[0].keys()
            if "Submission ID" in cols:  # MyEBirdData.csv
                for r in rows:
                    sci = (r.get("Scientific Name") or "").strip()
                    if not sci or " x " in sci or "/" in sci or sci.endswith(" sp."):
                        continue  # hybrider, artpar och obestämda hoppas över
                    lat, lon = r.get("Latitude"), r.get("Longitude")
                    obs.append({"sci": sci, "date": _date(r.get("Date", "")), "time": _time(r.get("Time", "")),
                                "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
                                "place": r.get("Location", ""), "region": r.get("State/Province", ""),
                                "count": r.get("Count", ""), "sub": r.get("Submission ID", ""), "kind": "obs"})
            elif "Taxon Order" in cols and "SubID" in cols:  # livslista
                for r in rows:
                    sci = (r.get("Scientific Name") or "").strip()
                    if not sci or (r.get("Category") or "species") not in ("species", "issf", "form"):
                        continue
                    life.append({"sci": sci, "date": _date(r.get("Date", "")), "time": "", "lat": None, "lon": None,
                                 "place": r.get("Location", ""), "region": r.get("S/P", ""),
                                 "count": r.get("Count", ""), "sub": r.get("SubID", ""), "kind": "life"})
            else:
                print(f"  eBird: känner inte igen formatet i {os.path.basename(f)} – hoppar över")
    have = {o["sci"] for o in obs}
    return obs + [x for x in life if x["sci"] not in have]
