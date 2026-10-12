"""Artportalen: läser egna fynd exporterade från Artportalen (Sök fynd → Tabell → Excel) i mappen artportalen/.

Excel-filen läses utan extra paket. Raderna har fyndets id, art, datum, tid, lokal och koordinater i
SWEREF 99 TM. Skyddade fynd hoppas alltid över. Samma fynd i flera exporter räknas en gång (fyndets id).
Vilka fynd som redan finns bland detektorns eller iNaturalists fynd avgörs i build.py.
"""
import glob
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from geo import sweref99tm_to_wgs84

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xlsx_rows(path):
    """Första bladets rader som listor av strängar."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))[0]
        rows = []
        for row in ET.fromstring(z.read(sheet)).iter(f"{{{_NS['m']}}}row"):
            out = []
            for c in row.findall("m:c", _NS):
                i = _col(c.get("r"))
                out += [""] * (i - len(out))
                t, v = c.get("t"), c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
                else:
                    val = v.text if v is not None else ""
                out.append(val or "")
            rows.append(out)
        return rows


def read(folders):
    """Lista med {id, sci, sv, date, time, lat, lon, acc, place, count} – skyddade fynd utelämnade."""
    out, seen = [], set()
    for folder in folders:
        for f in sorted(glob.glob(os.path.join(folder, "*.xlsx"))):
            rows = _xlsx_rows(f)
            head = next((i for i, r in enumerate(rows) if "Vetenskapligt namn" in r and "Id" in r), None)
            if head is None:
                print(f"  Artportalen: känner inte igen formatet i {os.path.basename(f)} – hoppar över")
                continue
            ix = {k: i for i, k in enumerate(rows[head]) if k and k not in ()}
            get = lambda r, k: (r[ix[k]] if k in ix and ix[k] < len(r) else "").strip()
            for r in rows[head + 1:]:
                fid, sci = get(r, "Id"), get(r, "Vetenskapligt namn")
                if not fid or not sci or fid in seen:
                    continue
                seen.add(fid)
                if get(r, "Skyddat fynd").lower() not in ("", "nej", "false"):
                    continue
                try:
                    lat, lon = sweref99tm_to_wgs84(float(get(r, "Ost")), float(get(r, "Nord")))
                except ValueError:
                    lat = lon = None
                antal, enhet = get(r, "Antal"), get(r, "Enhet")
                acc = get(r, "Noggrannhet")
                place, kommun = get(r, "Lokalnamn"), get(r, "Kommun")
                if kommun and kommun not in place:
                    place = f"{place}, {kommun}" if place else kommun
                out.append({"id": int(float(fid)), "sci": sci, "sv": get(r, "Artnamn"),
                            "date": get(r, "Startdatum")[:10], "time": get(r, "Starttid")[:5],
                            "lat": round(lat, 6) if lat is not None else None,
                            "lon": round(lon, 6) if lon is not None else None,
                            "acc": int(float(acc)) if acc else None, "place": place,
                            "count": " ".join(x for x in (antal, enhet) if x)})
    return out
