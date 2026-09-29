#!/usr/bin/env python3
"""
Bygger webbsidans data från BTO Acoustic Pipeline-exporter.

  python scripts/build.py                     # results/**/*.csv -> docs/data/data.json
  python scripts/build.py --refresh           # hämta om artinfo från GBIF/Wikipedia
  python scripts/build.py --no-weather        # hoppa över SMHI
  python scripts/build.py --artportalen       # skriv även exports/artportalen_<datum>.xlsx
  python scripts/build.py --artportalen --min-prob 0.9
  python scripts/build.py --add-site "Hemma" "Hildingavägen 33, Djursholm" hemma
        # ny lokal från adress eller "lat,lon"; valfritt: mappnamn under results/ som hör dit

Lokal väljs per rad i denna ordning: 1) mappen under results/ matchar en lokals
"folders", 2) BATCH NAME matchar "batches" (jokertecken tillåtna, t.ex. "2026_25_sep_*"),
3) närmaste lokal inom dess "radius_m" från CSV-filens koordinater, annars skapas en ny.

CSV-filer läses rekursivt under results/, så de kan ligga i undermappar
(t.ex. results/2026-09-25_stocksund/). Dubbletter (samma inspelning och art)
räknas bara en gång.

Artinfo cachas i data/species_cache.json, väder i data/weather_cache.json.
Lokalnamn, noggrannhet och publik precision redigeras i data/sites.json.
"""
import csv, glob, json, os, sys, time, urllib.parse, urllib.request
from collections import OrderedDict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smhi, artportalen  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "data", "species_cache.json")
SITES = os.path.join(ROOT, "data", "sites.json")
WEATHER = os.path.join(ROOT, "data", "weather_cache.json")
EXPORTS = os.path.join(ROOT, "exports")
EQUIPMENT = os.path.join(ROOT, "data", "equipment.json")
OUT = os.path.join(ROOT, "docs", "data")
UA = {"User-Agent": "bat-fynd/1.0 (github.com/ulfboge/bat)"}

# Svenska namn som går före allt annat. Fladdermöss enligt Naturvårdsverkets
# lista (namnen ändrades 2013). Övriga arter: sv-Wikipedias titel, sedan GBIF.
SV_NAMES = {
    "Myotis daubentonii": "Vattenfladdermus",
    "Myotis dasycneme": "Dammfladdermus",
    "Myotis brandtii": "Tajgafladdermus",
    "Myotis mystacinus": "Mustaschfladdermus",
    "Myotis nattereri": "Fransfladdermus",
    "Myotis bechsteinii": "Bechsteins fladdermus",
    "Myotis myotis": "Större musöra",
    "Myotis alcathoe": "Nymffladdermus",
    "Pipistrellus pygmaeus": "Dvärgpipistrell",
    "Pipistrellus pipistrellus": "Sydpipistrell",
    "Pipistrellus nathusii": "Trollpipistrell",
    "Nyctalus noctula": "Större brunfladdermus",
    "Nyctalus leisleri": "Mindre brunfladdermus",
    "Eptesicus serotinus": "Sydfladdermus",
    "Eptesicus nilssonii": "Nordfladdermus",
    "Vespertilio murinus": "Gråskimlig fladdermus",
    "Barbastella barbastellus": "Barbastell",
    "Plecotus auritus": "Brunlångöra",
    "Plecotus austriacus": "Grålångöra",
    "Aves": "Fåglar (obestämd art)",
}
GROUP_SV = {"bat": "Fladdermöss", "bush-cricket": "Vårtbitare",
            "bird": "Fåglar", "terrestrial mammal": "Övriga däggdjur",
            "": "Oidentifierat"}


def get_json(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                print("  ! misslyckades:", url, e, file=sys.stderr)
                return None
            time.sleep(3 * (i + 1) if "429" in str(e) else 1.5)


def fetch_species(sci):
    """Taxonomi från GBIF, text/bild från svenska Wikipedia, licens från Commons."""
    q = urllib.parse.quote
    name = "Aves" if sci == "Aves sp." else sci
    info = {"sci": sci}
    m = get_json(f"https://api.gbif.org/v1/species/match?name={q(name)}") or {}
    info["gbifKey"] = m.get("usageKey")
    info["rank"] = (m.get("rank") or "").lower()
    for k in ("kingdom", "phylum", "class", "order", "family", "genus"):
        info[k] = m.get(k)
    info["dyntaxaId"] = None
    # Dyntaxa-id (för länk till Artfakta) via Dyntaxas checklista på GBIF
    dy = get_json("https://api.gbif.org/v1/species/search?datasetKey=de8934f4-a136-481c-a87a-b0b202b80a31"
                  f"&q={q(name)}&limit=10") or {}
    res = [r for r in dy.get("results", []) if r.get("canonicalName") == name]
    for r in res:
        tid = r.get("taxonID") or ""
        if tid.startswith("urn:lsid:dyntaxa.se:Taxon:"):
            info["dyntaxaId"] = int(tid.rsplit(":", 1)[1])
            break
    else:
        # namnet är synonym i Dyntaxa (t.ex. Eptesicus nilssonii -> Cnephaeus nilssonii): följ till accepterat taxon
        for r in res:
            if r.get("acceptedKey"):
                a = get_json(f"https://api.gbif.org/v1/species/{r['acceptedKey']}") or {}
                tid = a.get("taxonID") or ""
                if tid.startswith("urn:lsid:dyntaxa.se:Taxon:"):
                    info["dyntaxaId"] = int(tid.rsplit(":", 1)[1])
                    info["dyntaxaName"] = a.get("canonicalName")
                    break
    # svenska namn
    info["sv"] = SV_NAMES.get(name)
    if not info["sv"] and info["gbifKey"]:
        v = get_json(f"https://api.gbif.org/v1/species/{info['gbifKey']}/vernacularNames?limit=200") or {}
        sv = [x["vernacularName"] for x in v.get("results", []) if x.get("language") == "swe"]
        info["sv"] = sv[0].capitalize() if sv else None
    # GBIF-fynd i Sverige och inom 25 km från lokalerna fylls i av build()
    # Wikipedia (sv, faller tillbaka på en)
    for lang in ("sv", "en"):
        time.sleep(1)
        s = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{q(name.replace(' ', '_'))}")
        if s and s.get("type") == "standard" and s.get("extract"):
            info["wiki"] = {"lang": lang, "title": s["title"], "extract": s["extract"],
                            "url": s["content_urls"]["desktop"]["page"]}
            img = s.get("thumbnail") or {}
            orig = (s.get("originalimage") or {}).get("source", "")
            if img:
                fname = urllib.parse.unquote(orig.split("/")[-1].split("?")[0]) if orig else None
                info["image"] = {"src": img["source"].split("?")[0].replace(f"/{img['width']}px-", "/640px-").split("?")[0]
                                 if img.get("width", 0) < 640 and "/thumb/" in img["source"] else img["source"],
                                 "file": fname}
                if fname:
                    ii = get_json("https://commons.wikimedia.org/w/api.php?action=query&format=json"
                                  f"&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=500&titles=File:{q(fname)}") or {}
                    for p in ii.get("query", {}).get("pages", {}).values():
                        ii0 = (p.get("imageinfo") or [{}])[0]
                        md = ii0.get("extmetadata", {})
                        if ii0.get("thumburl"):
                            info["image"]["src"] = ii0["thumburl"]
                        import re
                        strip = lambda t: re.sub(r"<[^>]+>", "", t or "").strip()
                        info["image"]["artist"] = strip(md.get("Artist", {}).get("value"))[:120]
                        info["image"]["license"] = strip(md.get("LicenseShortName", {}).get("value"))
                        info["image"]["page"] = f"https://commons.wikimedia.org/wiki/File:{q(fname)}"
            if lang == "sv" and not SV_NAMES.get(name) and info["rank"] == "species":
                info["sv"] = s["title"]
            break
    return info


def gbif_counts(info, sites):
    if not info.get("gbifKey"):
        return
    k = info["gbifKey"]
    se = get_json(f"https://api.gbif.org/v1/occurrence/search?taxonKey={k}&country=SE&limit=0") or {}
    info["gbifSE"] = se.get("count")
    near = 0
    for s in sites:
        n = get_json(f"https://api.gbif.org/v1/occurrence/search?taxonKey={k}"
                     f"&geoDistance={s['lat']},{s['lon']},25km&limit=0") or {}
        near = max(near, n.get("count") or 0)
    info["gbifNear25km"] = near


def site_name(lat, lon):
    r = get_json(f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=14&accept-language=sv") or {}
    a = r.get("address", {})
    return a.get("suburb") or a.get("village") or a.get("town") or a.get("city") or f"{lat}, {lon}"


def _dist_m(lat1, lon1, lat2, lon2):
    import math
    return math.hypot((lat1 - lat2) * 111320, (lon1 - lon2) * 111320 * math.cos(math.radians(lat1)))


def assign_site(r, sites):
    """Välj lokal för en rad: 1) mappnamn, 2) batchnamn, 3) närmaste lokal inom radius_m."""
    import fnmatch
    parts = r.get("_folder", "").split("/")
    for i, st in enumerate(sites):
        if any(fnmatch.fnmatch(p, pat) for pat in st.get("folders", []) for p in parts):
            return i
    for i, st in enumerate(sites):
        if any(fnmatch.fnmatch(r.get("BATCH NAME", ""), pat) for pat in st.get("batches", [])):
            return i
    try:
        lat, lon = float(r["LATITUDE"]), float(r["LONGITUDE"])
    except (TypeError, ValueError):
        return None
    best = min(((_dist_m(lat, lon, st["lat"], st["lon"]), i) for i, st in enumerate(sites)
                if _dist_m(lat, lon, st["lat"], st["lon"]) <= st.get("radius_m", 100)), default=None)
    return best[1] if best else None


def next_site_id(sites):
    n = 1
    while any(st["id"] == f"L{n}" for st in sites):
        n += 1
    return f"L{n}"


def add_site(name, where, folders=()):
    """Lägg till en lokal manuellt: where = 'lat,lon' eller en adress (slås upp i OpenStreetMap)."""
    try:
        lat, lon = (float(v) for v in where.split(","))
    except ValueError:
        res = get_json("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(where))
        if not res:
            sys.exit(f"Hittade inte adressen: {where}")
        lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
        print("  hittade:", res[0]["display_name"])
    sites = json.load(open(SITES, encoding="utf-8")) if os.path.exists(SITES) else []
    st = {"id": next_site_id(sites), "name": name, "lat": round(lat, 5), "lon": round(lon, 5), "decimals": 5,
          "accuracy_m": 50, "radius_m": 100, "folders": list(folders), "batches": [], "note": ""}
    sites.append(st)
    json.dump(sites, open(SITES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  la till {st['id']} {name} ({st['lat']}, {st['lon']})" + (f", mappar: {', '.join(folders)}" if folders else ""))


def build(refresh=False, weather=True, export_ap=False, min_prob=0.8):
    files = sorted(glob.glob(os.path.join(RESULTS, "**", "*.csv"), recursive=True))
    rows, seen, dups = [], set(), 0
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r["_folder"] = os.path.relpath(os.path.dirname(f), RESULTS).replace("\\", "/")
                k = (r["RECORDING FILE NAME"], r["ORIGINAL FILE PART"], r["SCIENTIFIC NAME"])
                if k in seen:
                    dups += 1
                    continue
                seen.add(k)
                rows.append(r)
    print(f"{len(files)} filer, {len(rows)} detektioner" + (f" ({dups} dubbletter borttagna)" if dups else ""))

    # --- lokaler ---
    sites = json.load(open(SITES, encoding="utf-8")) if os.path.exists(SITES) else []
    for st in sites:
        st.setdefault("decimals", 5)
        st.setdefault("accuracy_m", 50)
        st.setdefault("radius_m", 100)
        st.setdefault("folders", [])
        st.setdefault("batches", [])
        st.setdefault("note", "")
    counts = {}
    for r in rows:
        si = assign_site(r, sites)
        if si is None:
            key = (round(float(r["LATITUDE"] or 0), 5), round(float(r["LONGITUDE"] or 0), 5))
            print("  ny lokal:", key, "– byt namn i data/sites.json vid behov")
            sites.append({"id": next_site_id(sites), "name": site_name(*key), "lat": key[0], "lon": key[1],
                          "decimals": 5, "accuracy_m": 50, "radius_m": 100, "folders": [], "batches": [], "note": ""})
            time.sleep(1)
            si = assign_site(r, sites)
        r["_site"] = si
        counts[si] = counts.get(si, 0) + 1
    for si, n in sorted(counts.items()):
        print(f"  {sites[si]['name']}: {n} detektioner")
    json.dump(sites, open(SITES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # --- utrustning (inspelare) ---
    eq = json.load(open(EQUIPMENT, encoding="utf-8")) if os.path.exists(EQUIPMENT) else {"recorders": {}}
    rec_ids = list(eq.get("recorders", {}))
    for r in rows:
        dev = r.get("ORIGINAL FILE NAME", "").rsplit("_", 2)[0]   # DEV_001_20260925_191217.wav -> DEV_001
        rid = eq.get("devices", {}).get(dev) or sites[r["_site"]].get("utrustning") or eq.get("default")
        r["_rec"] = rec_ids.index(rid) if rid in rec_ids else -1
        r["_dev"] = dev
    recorders = [{"id": k, **v} for k, v in eq.get("recorders", {}).items()]

    # --- arter ---
    cache = {} if refresh or not os.path.exists(CACHE) else json.load(open(CACHE, encoding="utf-8"))
    sp_keys = OrderedDict()
    for r in rows:
        sci = r["SCIENTIFIC NAME"].strip() or "Oidentifierad"
        sp_keys.setdefault(sci, {"group": r["SPECIES GROUP"].strip(), "code": r["SPECIES"].strip(),
                                 "en": r["ENGLISH NAME"].strip()})
    for sci, meta in sp_keys.items():
        if sci != "Oidentifierad" and (sci not in cache or "wiki" not in cache[sci] or "dyntaxaId" not in cache[sci] or ("image" in cache[sci] and not cache[sci]["image"].get("license"))):
            print("  hämtar artinfo:", sci)
            cache[sci] = fetch_species(sci)
            gbif_counts(cache[sci], sites)
            time.sleep(2)  # snällt mot Wikipedia
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    species = []
    for sci, meta in sp_keys.items():
        info = dict(cache.get(sci, {"sci": sci, "sv": "Oidentifierad signal"}))
        info.update(meta, groupSv=GROUP_SV.get(meta["group"], meta["group"]))
        species.append(info)
    sp_index = {s["sci"]: i for i, s in enumerate(species)}

    # --- detektioner (kompakt) ---
    det = []
    for r in rows:
        d, mth, y = r["ACTUAL DATE"].split("/")
        sd, sm, sy = r["SURVEY DATE"].split("/")
        det.append([
            sp_index[r["SCIENTIFIC NAME"].strip() or "Oidentifierad"],
            r["_site"],
            f"{y}-{mth}-{d}T{r['TIME']}",
            float(r["PROBABILITY"] or 0),
            r["CALL TYPE"].strip(),
            f"{sy}-{sm}-{sd}",
            r["ORIGINAL FILE NAME"],
            r["_rec"],
        ])
    det.sort(key=lambda x: x[2])
    classifier = sorted({r["CLASSIFIER NAME"] for r in rows})
    # Publik version av lokalerna: sätt "decimals" i data/sites.json (t.ex. 2 ≈ 1 km)
    # om exakt position inte ska synas på webben.
    pub_sites = []
    for st in sites:
        dec = st.get("decimals", 5)
        pub_sites.append({**st, "lat": round(st["lat"], dec), "lon": round(st["lon"], dec)})
    # --- väder per natt och lokal (SMHI) ---
    wx = {}
    if weather:
        wcache = json.load(open(WEATHER, encoding="utf-8")) if os.path.exists(WEATHER) else {}
        for night, si in sorted({(d[5], d[1]) for d in det}):
            ck = f"{night}|{sites[si]['id']}"
            if ck not in wcache or not wcache[ck].get("complete"):
                print("  hämtar väder:", night, sites[si]["name"])
                wcache[ck] = smhi.night_weather(date.fromisoformat(night), sites[si]["lat"], sites[si]["lon"])
            wx[f"{night}|{si}"] = wcache[ck]
        json.dump(wcache, open(WEATHER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "classifier": classifier,
           "fields": ["species", "site", "time", "prob", "callType", "night", "file", "recorder"],
           "species": species, "sites": pub_sites, "recorders": recorders, "weather": wx, "detections": det}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Skrev docs/data/data.json ({len(species)} taxa, {len(sites)} lokaler, "
          f"{len({d[5] for d in det})} nätter)")

    if export_ap:
        res = artportalen.export(det, species, sites, EXPORTS, min_prob=min_prob, classifier=", ".join(classifier),
                                 recorders=recorders)
        if res:
            print(f"Skrev {os.path.relpath(res[0], ROOT)} ({res[1]} fynd, {res[2]} rader att granska)")


if __name__ == "__main__":
    a = sys.argv
    if "--add-site" in a:
        i = a.index("--add-site")
        add_site(a[i + 1], a[i + 2], a[i + 3].split(",") if len(a) > i + 3 and not a[i + 3].startswith("--") else ())
        sys.exit(0)
    mp = float(a[a.index("--min-prob") + 1]) if "--min-prob" in a else 0.8
    build(refresh="--refresh" in a, weather="--no-weather" not in a,
          export_ap="--artportalen" in a, min_prob=mp)
