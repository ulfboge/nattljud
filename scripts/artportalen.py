"""Artportalen-underlag: en rad per art, natt och lokal.

Skriver exports/artportalen_<datum>.xlsx med två flikar:
  Fynd     – arter vars bästa registrering når minsta sannolikhet (standard 0,8)
  Granska  – alla taxa med statistik, även de som inte kom med

Kolumnerna följer Artportalens fält men är inte en exakt kopia av den officiella
importmallen. Kopiera kolumnerna till mallen från artportalen.se/ImportSighting,
eller lägg mallen i data/ så kan skriptet anpassas till den.
"""
import os
from datetime import datetime
from statistics import median

from geo import wgs84_to_sweref99tm

GROUP_METHOD = {"bat": "Ultraljudsdetektor", "bush-cricket": "Ultraljudsdetektor",
                "terrestrial mammal": "Ultraljudsdetektor", "bird": "Ultraljudsdetektor"}

CALL_SV = {"echolocation": "ekolod", "social": "sociala läten"}


def _n(k):
    return f"{k} registrering" if k == 1 else f"{k} registreringar"


def _p(v):
    return f"{v:.2f}".replace(".", ",")


def _span(times):
    a, b = times[0][11:16], times[-1][11:16]
    return f"kl. {a}" if a == b else f"kl. {a}–{b}"


def export(rows, species, sites, out_dir, min_prob=0.8, classifier=""):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  ! openpyxl saknas – kör: pip install openpyxl")
        return None

    # gruppera detektioner per (lokal, natt, art)
    groups = {}
    for d in rows:  # d = [spIdx, siteIdx, time, prob, callType, night, file]
        groups.setdefault((d[1], d[5], d[0]), []).append(d)

    fynd, granska = [], []
    for (si, night, spi), dets in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
        sp, site = species[spi], sites[si]
        probs = [d[3] for d in dets]
        good = [d for d in dets if d[3] >= min_prob]
        times = sorted(d[2] for d in (good or dets))
        e, n = wgs84_to_sweref99tm(site["lat"], site["lon"])
        calls = {d[4] for d in good if d[4]}
        is_species = sp.get("rank") == "species"
        rec = {
            "Artnamn": sp.get("sv") or sp["sci"],
            "Vetenskapligt namn": sp["sci"],
            "Taxon-id (Dyntaxa)": sp.get("dyntaxaId"),
            "Antal": 1,
            "Enhet": "",
            "Aktivitet": "",
            "Startdatum": times[0][:10], "Starttid": times[0][11:16],
            "Slutdatum": times[-1][:10], "Sluttid": times[-1][11:16],
            "Lokalnamn": site["name"],
            "Ost (SWEREF 99 TM)": e, "Nord (SWEREF 99 TM)": n,
            "Noggrannhet (m)": site.get("accuracy_m", 50),
            "Bestämningsmetod": GROUP_METHOD.get(sp.get("group"), "Ultraljudsdetektor"),
            "Osäker artbestämning": "Ja" if median(probs) < min_prob else "",
            "Publik kommentar": (f"Ultraljudsdetektor, {_n(len(good))} {_span(times)}"
                                 f"{' (' + ', '.join(CALL_SV.get(c, c) for c in sorted(calls)) + ')' if calls else ''}. "
                                 f"Automatisk artbestämning BTO Acoustic Pipeline, högsta sannolikhet {_p(max(probs))}."),
            "Privat kommentar": f"Klassificerare {classifier}. Median sannolikhet {_p(median(probs))}, {_n(len(dets))} totalt. Ej manuellt verifierad.",
        }
        stat = {"Natt": night, "Lokal": site["name"], "Artnamn": rec["Artnamn"], "Vetenskapligt namn": sp["sci"],
                "Grupp": sp.get("groupSv", ""), "Registreringar": len(dets), f"≥ {min_prob:g}": len(good),
                "Median p": round(median(probs), 2), "Max p": round(max(probs), 2)}
        ok = is_species and good
        stat["Med i Fynd"] = "Ja" if ok else ("Nej – ej art" if not is_species else f"Nej – ingen ≥ {min_prob:g}")
        granska.append(stat)
        if ok:
            fynd.append(rec)

    wb = Workbook()
    for ws, data, title in ((wb.active, fynd, "Fynd"), (wb.create_sheet(), granska, "Granska")):
        ws.title = title
        if not data:
            ws.append(["Inga rader"])
            continue
        cols = list(data[0].keys())
        ws.append(cols)
        for r in data:
            ws.append([r.get(c) for c in cols])
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="E1E0D9")
        for i, c in enumerate(cols, 1):
            width = max(len(str(c)), *(len(str(r.get(c) or "")) for r in data))
            ws.column_dimensions[get_column_letter(i)].width = min(60, width + 2)
        ws.freeze_panes = "A2"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"artportalen_{datetime.now():%Y-%m-%d}.xlsx")
    wb.save(path)
    return path, len(fynd), len(granska)
