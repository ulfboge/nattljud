#!/usr/bin/env python3
"""
Bygger webbsidans data från BTO Acoustic Pipeline-exporter.

  python scripts/build.py                     # results/**/*.csv -> docs/data/data.json
  python scripts/build.py --refresh           # hämta om artinfo från GBIF/Wikipedia
  python scripts/build.py --no-weather        # hoppa över SMHI
  python scripts/build.py --artportalen       # skriv exports/artportalen_<datum>_<tid>.xlsx med
                                              # resultatfiler som inte exporterats tidigare
  python scripts/build.py --artportalen --min-prob 0.9
  python scripts/build.py --artportalen --alla  # alla filer, oavsett tidigare export (loggas inte)
  python scripts/build.py --artportalen --utan "Art1,Art2"  # utelämna arter (kommaseparerat);
                                              # arter i DOUBTFUL utelämnas alltid
  python scripts/build.py --add-site "Hemma" "Hildingavägen 33, Djursholm" hemma
        # ny lokal från adress eller "lat,lon"; valfritt: mappnamn under results/ som hör dit

Lokal väljs per rad i denna ordning: 1) mappen under results/ matchar en lokals
"folders", 2) BATCH NAME matchar "batches" (jokertecken tillåtna, t.ex. "2026_25_sep_*"),
3) närmaste lokal inom dess "radius_m" från CSV-filens koordinater, annars skapas en ny.

CSV-filer läses rekursivt under results/, så de kan ligga i undermappar
(t.ex. results/2026-09-25_stocksund/). Dubbletter (samma inspelning och art)
räknas bara en gång.

Vilka resultatfiler som redan gått till Artportalen loggas i data/artportalen_exporterat.json
(filnamn, utan mapp). Ta bort en post där för att exportera om de filerna.

Artinfo cachas i data/species_cache.json, väder i data/weather_cache.json.
Lokalnamn, noggrannhet och publik precision redigeras i data/sites.json.
"""
import csv, glob, json, os, sys, time, urllib.parse, urllib.request
from collections import OrderedDict
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smhi, artportalen, inat, ebird  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "data", "species_cache.json")
SITES = os.path.join(ROOT, "data", "sites.json")
WEATHER = os.path.join(ROOT, "data", "weather_cache.json")
EXPORTS = os.path.join(ROOT, "exports")
AP_LOG = os.path.join(ROOT, "data", "artportalen_exporterat.json")
EQUIPMENT = os.path.join(ROOT, "data", "equipment.json")
OUT = os.path.join(ROOT, "docs", "data")
INAT_USER = "ulfboge"  # iNaturalist-användare vars publika observationer tas med (--no-inat stänger av)
INAT_CACHE = os.path.join(ROOT, "data", "inat_cache.json")
TAXONOMY_CACHE = os.path.join(ROOT, "data", "taxonomy_cache.json")
EBIRD_DIRS = [os.path.join(ROOT, "eBird"), os.path.join(ROOT, "data", "ebird")]
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


# Bestämningar som visas på webbsidan men märks som troligen felaktiga och aldrig går till Artportalen.
DOUBTFUL = {
    "Myotis bechsteinii": "Bechsteins fladdermus är i Sverige bara känd från Skåne, "
                          "och klassificeraren förväxlar den lätt med andra Myotis-arter. Kontrollera i "
                          "spektrogram innan fyndet används.",
    # BirdNET-bestämningar som är osannolika för platsen eller tiden (natt i oktober, Djursholm)
    "Botaurus stellaris": "Rördrom i en villaträdgård i Djursholm är osannolikt, och BirdNET ger lätt "
                          "falsklarm för rördrom på låga, dova ljud. Lyssna på klippet innan fyndet används.",
    "Falco subbuteo": "Lärkfalken har normalt lämnat Sverige i oktober, och det är bara ett enstaka "
                      "segment. Lyssna på klippet innan fyndet används.",
    "Tringa erythropus": "Sen svartsnäppa på ett enstaka segment mitt i natten. Lyssna på klippet innan "
                         "fyndet används.",
    "Coccothraustes coccothraustes": "Stenknäck som lockar mitt i natten är osannolikt. Lyssna på klippen "
                                     "innan fynden används.",
}


BIRDNET = os.path.join(ROOT, "data", "birdnet")
BIRDNET_MIN = 0.5
BIRDNET_CLASSIFIER = "BirdNET 2.4"


def apply_birdnet(rows):
    """BTO:s ultraljudsklassificerare anger fåglar bara som "Aves sp.". Klippen har körts genom BirdNET
    (data/birdnet/*.csv, semikolonseparerade: Fil;Tid;Start s;Slut s;Art;Vetenskapligt namn;Sannolikhet).
    En Aves sp.-detektion ersätts av de arter BirdNET hittat i samma fil med sannolikhet ≥ BIRDNET_MIN
    (högsta värdet per art); sannolikheten blir BirdNETs. Övriga lämnas som obestämda."""
    best = {}
    for f in sorted(glob.glob(os.path.join(BIRDNET, "*.csv"))):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                sci, p = r.get("Vetenskapligt namn", "").strip(), (r.get("Sannolikhet") or "").replace(",", ".")
                if not sci or not p or float(p) < BIRDNET_MIN:
                    continue
                d = best.setdefault(r["Fil"], {})
                d[sci] = max(d.get(sci, 0), float(p))
    if not best:
        return
    out, n = [], 0
    for r in rows:
        hits = best.get(r["ORIGINAL FILE NAME"]) if r["SCIENTIFIC NAME"].strip() == "Aves sp." else None
        if not hits:
            out.append(r)
            continue
        for sci, p in sorted(hits.items(), key=lambda kv: -kv[1]):
            out.append({**r, "SCIENTIFIC NAME": sci, "SPECIES": "", "ENGLISH NAME": "", "SPECIES GROUP": "bird",
                        "PROBABILITY": f"{p:.2f}", "CALL TYPE": "", "_source": "BirdNET"})
            n += 1
    rows[:] = out
    print(f"  BirdNET: {n} fågeldetektioner artbestämda (≥ {BIRDNET_MIN:g})")


def birdnet_only(rows, wavs_per_file):
    """Inspelningar gjorda i detektorns fågelläge laddas inte upp till BTO utan körs bara genom BirdNET.
    Klipp i data/birdnet/*.csv som saknas i BTO-resultaten blir egna detektioner: en per klipp och art
    med högsta sannolikhet ≥ BIRDNET_MIN (tid = klippets start + segmentets början).
    Position från data/birdnet/<samma namn>.json: {"lat": .., "lon": ..}.
    Varje BirdNET-fil räknas som en resultatfil i Artportalen-loggen."""
    from datetime import timedelta
    in_bto = {r["ORIGINAL FILE NAME"] for r in rows}
    added = []
    for f in sorted(glob.glob(os.path.join(BIRDNET, "*.csv"))):
        meta_f = f[:-4] + ".json"
        meta = json.load(open(meta_f, encoding="utf-8")) if os.path.exists(meta_f) else {}
        best, wavs = {}, set()
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                if r["Fil"] in in_bto:
                    continue
                wavs.add(r["Fil"])
                sci, p = r.get("Vetenskapligt namn", "").strip(), (r.get("Sannolikhet") or "").replace(",", ".")
                if not sci or not p or float(p) < BIRDNET_MIN:
                    continue
                k = (r["Fil"], sci)
                if float(p) > best.get(k, (0,))[0]:
                    best[k] = (float(p), float(r["Start s"] or 0), r["Tid"])
        if not wavs:
            continue
        if not meta.get("lat"):
            print(f"  ! {os.path.basename(f)}: {len(wavs)} klipp utan BTO-resultat men position saknas ({os.path.basename(meta_f)})")
            continue
        wavs_per_file[os.path.basename(f)] = wavs
        for (wav, sci), (p, start, tid) in sorted(best.items()):
            t = datetime.strptime(tid, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=start)
            night = (t - timedelta(hours=12)).date()
            added.append({"RECORDING FILE NAME": wav, "ORIGINAL FILE NAME": wav, "ORIGINAL FILE PART": "0",
                          "LATITUDE": str(meta["lat"]), "LONGITUDE": str(meta["lon"]), "SPECIES": "",
                          "SCIENTIFIC NAME": sci, "ENGLISH NAME": "", "SPECIES GROUP": "bird",
                          "PROBABILITY": f"{p:.2f}", "CALL TYPE": "", "ACTUAL DATE": t.strftime("%d/%m/%Y"),
                          "SURVEY DATE": night.strftime("%d/%m/%Y"), "TIME": t.strftime("%H:%M:%S"),
                          "CLASSIFIER NAME": BIRDNET_CLASSIFIER, "BATCH NAME": "", "_folder": "",
                          "_source": "BirdNET"})
        print(f"  BirdNET (fågelläge) {os.path.basename(f)}: {len(wavs)} klipp, "
              f"{sum(1 for k in best if k[0] in wavs)} detektioner ≥ {BIRDNET_MIN:g}")
    rows.extend(added)


def merge_pairs(species, rows):
    """Slå ihop arter som inte går att skilja på ljudet till ett artpar (artportalen.PAIRS).
    Returnerar ny artlista, index per vetenskapligt namn (även för de sammanslagna arterna)
    och medlemsindex per sammanslagen art (sparas som nionde fält i detektionen)."""
    n_by_sci = {}
    for r in rows:
        k = r["SCIENTIFIC NAME"].strip() or "Oidentifierad"
        n_by_sci[k] = n_by_sci.get(k, 0) + 1
    out, index, member_of, pair_pos = [], {}, {}, {}
    for s in species:
        key = artportalen.PAIRS.get(s["sci"])
        if not key:
            index[s["sci"]] = len(out)
            out.append(s)
            continue
        if key not in pair_pos:
            pair_pos[key] = len(out)
            t = artportalen.PAIR_TAXA[key]
            out.append({k: s.get(k) for k in ("kingdom", "phylum", "class", "order", "family", "genus",
                                              "group", "groupSv", "image")}
                       | {"sci": t["sci"], "sv": t["sv"], "apName": t["apName"], "en": t["en"],
                          "rank": "species", "dyntaxaId": t["dyntaxaId"], "gbifKey": None,
                          "note": t["note"], "pairNote": t["pairNote"], "code": "", "members": []})
        pair = out[pair_pos[key]]
        if not pair.get("image") and s.get("image"):
            pair["image"] = s["image"]
        member_of[s["sci"]] = len(pair["members"])
        pair["members"].append({"sci": s["sci"], "sv": s.get("sv"), "code": s.get("code"),
                                "n": n_by_sci.get(s["sci"], 0), "dyntaxaId": s.get("dyntaxaId")})
        pair["code"] = "/".join(m["code"] for m in pair["members"] if m["code"])
        index[s["sci"]] = pair_pos[key]
    for s in out:
        if s.get("image") is None:
            s.pop("image", None)
    return out, index, member_of


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

# ------------------------------------------------------------------ iNaturalist och artträd
# Namn att slå upp i iNaturalist för detektorns taxa som inte är vanliga artnamn.
INAT_NAME = {"Aves sp.": "Aves", "Myotis mystacinus/brandtii": "Myotis"}


def add_inat(species, sites, use_inat=True, online=True):
    """Lägg till iNaturalist-observationer och bygg det systematiska trädet för alla taxa.
    Returnerar (tree, observations). tree: {id: [förälder, rang, vetenskapligt namn, svenskt namn]}.
    Detektorns arter får 'inat' (taxon-id i trädet); iNaturalist-arter läggs till sist i species."""
    tax = inat.Taxonomy(TAXONOMY_CACHE, online)
    for s in species:
        if s["sci"] != "Oidentifierad":
            s["inat"] = tax.lookup(INAT_NAME.get(s["sci"], s["sci"]))
    raw = inat.fetch_observations(INAT_USER, INAT_CACHE, online) if use_inat else []
    for o in raw:
        o["src"] = "i"
    eb = ebird.read(EBIRD_DIRS)
    for e in eb:
        tid = tax.lookup(e["sci"])
        if tid is None:
            print("  eBird: hittar inte i iNaturalist:", e["sci"])
            continue
        raw.append({"id": e["sub"], "taxon": tid, "date": e["date"], "time": e["time"], "lat": e["lat"],
                    "lon": e["lon"], "acc": None, "obscured": False, "quality": "", "license": "", "photo": "",
                    "place": ", ".join(x for x in (e["place"], e["region"]) if x), "sounds": 0,
                    "src": "e" if e["kind"] == "obs" else "l", "count": e["count"],
                    "country": "SE" if (e["region"] or "").startswith("SE") else "X"})
    if eb:
        print(f"  eBird: {len(eb)} rader")
    tax.ensure([s.get("inat") for s in species] + [o["taxon"] for o in raw])

    for s in species:
        if s["sci"] != "Oidentifierad":
            s["sources"] = [s.get("source") or "BTO"]
    by_taxon = {s["inat"]: i for i, s in enumerate(species) if s.get("inat") and not s.get("members")}
    obs = []
    for o in sorted(raw, key=lambda o: (o["date"], o["time"])):
        t = tax.get(o["taxon"])
        if not t:
            continue
        i = by_taxon.get(o["taxon"])
        if i is None:
            i = by_taxon[o["taxon"]] = len(species)
            species.append({"sci": t["name"], "sv": t.get("sv") or "", "rank": t["rank"], "inat": o["taxon"],
                            "group": "obs", "groupSv": inat.ICONIC_SV.get(t.get("iconic"), "Övrigt"),
                            "iconic": t.get("iconic"), "code": "", "en": "", **({"wiki": {
                                "lang": "sv" if "sv.wikipedia" in t["wiki"]["url"] else "en", "title": t["name"],
                                **t["wiki"]}} if t.get("wiki") else {})})
        s = species[i]
        s.setdefault("sources", [])
        src_name = "iNaturalist" if o["src"] == "i" else "eBird"
        if src_name not in s["sources"]:
            s["sources"].append(src_name)
        if o["photo"] and not s.get("image"):
            s["image"] = {"src": o["photo"], "artist": "Johan Karlsson", "license": o["license"].upper() or "iNaturalist",
                          "page": f"https://www.inaturalist.org/observations/{o['id']}"}
        site = -1 if o["lat"] is None else next((k for k, st in enumerate(sites)
                     if _dist_m(o["lat"], o["lon"], st["lat"], st["lon"]) <= st.get("radius_m", 100)), -1)
        obs.append([i, o["id"], o["date"], o["time"], o["lat"], o["lon"], o["acc"], o["quality"][:1], o["place"],
                    o["photo"], site, 1 if o["obscured"] else 0, o["license"], o["src"],
                    o.get("country", "")])

    # Bild till taxa utan eget foto (t.ex. eBird-fynd): iNaturalists standardbild om den är fritt licensierad.
    noimg = [s for s in species if not s.get("image") and s.get("inat") and not s.get("members")]
    ph = tax.photos([s["inat"] for s in noimg])
    for s in noimg:
        if ph.get(s["inat"]):
            s["image"] = ph[s["inat"]]

    # Dyntaxa: svenskt namn där iNaturalist saknar det, och avvikande vetenskapligt namn för arter.
    need = [tax.get(s["inat"])["name"] for s in species if s.get("group") == "obs" and tax.get(s.get("inat"))]
    for s in species:
        for n in tax.path(s["inat"]) if s.get("inat") else []:
            t = tax.get(n)
            if t and not t.get("sv") and t["rank"] not in ("species", "subspecies"):
                need.append(t["name"])
    tax.prefetch_dyntaxa(need)
    for s in species:
        t = tax.get(s.get("inat")) if s.get("inat") else None
        if not t or s.get("members") or s["sci"] in INAT_NAME:
            continue
        if t["name"] != s["sci"]:
            s["inatName"] = t["name"]  # t.ex. Eptesicus nilssonii heter Cnephaeus nilssonii i iNaturalist
        if s.get("group") == "obs":
            dy = tax.dyntaxa_for(t["name"])
            if dy:
                s.setdefault("dyntaxaId", dy.get("id"))
                if dy.get("name") and dy["name"] != t["name"]:
                    s["dyntaxaName"] = dy["name"]
                if not s.get("sv"):
                    s["sv"] = dy.get("sv") or ""
            if not s.get("sv"):
                s["sv"] = ""

    # Trädet: alla noder på vägen från rike till varje taxon.
    tree = {}
    for s in species:
        if not s.get("inat"):
            continue
        for n in tax.path(s["inat"]):
            t = tax.get(n)
            if t and str(n) not in tree:
                tree[str(n)] = [t.get("parent"), t["rank"], t["name"], t.get("sv") or ""]
    # svenska namn på högre taxa från Dyntaxa där iNaturalist saknar dem
    for k, v in tree.items():
        if not v[3] and v[1] not in ("species", "subspecies"):
            v[3] = (tax.dyntaxa_for(v[2]) or {}).get("sv", "")
    # förälder = närmaste förfader som finns i trädet
    for k, v in tree.items():
        p = v[0]
        while p is not None and str(p) not in tree:
            p = (tax.get(p) or {}).get("parent")
        v[0] = p
    tax.save()
    if use_inat:
        print(f"  iNaturalist/eBird: {len(obs)} observationer, {sum(1 for s in species if s.get('group') == 'obs')} nya taxa")
    return tree, obs


def build(refresh=False, weather=True, export_ap=False, min_prob=0.8, export_all=False, exclude=(), use_inat=True,
          online=True):
    files = sorted(glob.glob(os.path.join(RESULTS, "**", "*.csv"), recursive=True))
    rows, seen, dups = [], set(), 0
    wavs_per_file = {}  # resultatfilens namn -> inspelningar i den (för Artportalen-loggen)
    for f in files:
        wf = wavs_per_file.setdefault(os.path.basename(f), set())
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                wf.add(r["ORIGINAL FILE NAME"])
                r["_folder"] = os.path.relpath(os.path.dirname(f), RESULTS).replace("\\", "/")
                k = (r["RECORDING FILE NAME"], r["ORIGINAL FILE PART"], r["SCIENTIFIC NAME"])
                if k in seen:
                    dups += 1
                    continue
                seen.add(k)
                rows.append(r)
    print(f"{len(files)} filer, {len(rows)} detektioner" + (f" ({dups} dubbletter borttagna)" if dups else ""))
    apply_birdnet(rows)
    birdnet_only(rows, wavs_per_file)

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
                                 "en": r["ENGLISH NAME"].strip(),
                                 **({"source": r["_source"]} if r.get("_source") else {})})
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
    species, sp_index, member_of = merge_pairs(species, rows)
    for s in species:
        if s["sci"] in DOUBTFUL:
            s["doubt"] = DOUBTFUL[s["sci"]]
    tree, obs = add_inat(species, sites, use_inat, online)

    # --- detektioner (kompakt) ---
    det = []
    for r in rows:
        d, mth, y = r["ACTUAL DATE"].split("/")
        sd, sm, sy = r["SURVEY DATE"].split("/")
        sci = r["SCIENTIFIC NAME"].strip() or "Oidentifierad"
        det.append([
            sp_index[r["SCIENTIFIC NAME"].strip() or "Oidentifierad"],
            r["_site"],
            f"{y}-{mth}-{d}T{r['TIME']}",
            float(r["PROBABILITY"] or 0),
            r["CALL TYPE"].strip(),
            f"{sy}-{sm}-{sd}",
            r["ORIGINAL FILE NAME"],
            r["_rec"],
        ] + ([member_of[sci]] if sci in member_of else []))
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
           "fields": ["species", "site", "time", "prob", "callType", "night", "file", "recorder", "btoMember"],
           "species": species, "sites": pub_sites, "recorders": recorders, "weather": wx, "detections": det,
           "tree": tree, "inatUser": INAT_USER if use_inat else None,
           "obsFields": ["species", "id", "date", "time", "lat", "lon", "acc", "quality", "place", "photo", "site",
                         "obscured", "license", "source", "country"],
           "observations": obs}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Skrev docs/data/data.json ({len(species)} taxa, {len(sites)} lokaler, "
          f"{len({d[5] for d in det})} nätter, {len(obs)} fältobservationer)")

    if export_ap:
        export_artportalen(det, species, sites, classifier, recorders, wavs_per_file, min_prob, export_all, exclude)


def export_artportalen(det, species, sites, classifier, recorders, wavs_per_file, min_prob, export_all, exclude=()):
    """Exportera bara detektioner från resultatfiler som inte exporterats tidigare, och logga dem."""
    log = json.load(open(AP_LOG, encoding="utf-8")) if os.path.exists(AP_LOG) else {"exporter": []}
    done = {f for e in log["exporter"] for f in e["filer"]}
    prev_ids = {x for e in log["exporter"] for x in e.get("externid", [])}
    new_files = sorted(wavs_per_file) if export_all else sorted(f for f in wavs_per_file if f not in done)
    if not new_files:
        print("Artportalen: inga nya resultatfiler sedan senaste exporten – inget skrivet.")
        return
    old_wavs = set() if export_all else set().union(*(wavs_per_file[f] for f in wavs_per_file if f in done))
    sel = [d for d in det if d[6] not in old_wavs]
    doubt = {sp["sci"] for sp in species if sp.get("doubt")}
    if doubt - set(exclude):
        print(f"Artportalen: utelämnar tveksamma bestämningar: {', '.join(sorted(doubt - set(exclude)))}")
    exclude = set(exclude) | doubt
    if exclude:
        skip = {i for i, sp in enumerate(species) if sp["sci"] in exclude}
        n0 = len(sel)
        sel = [d for d in sel if d[0] not in skip]
        print(f"Artportalen: utelämnar {', '.join(sorted(exclude))} ({n0 - len(sel)} detektioner)")
    if not sel:
        print("Artportalen: de nya filerna innehåller bara inspelningar som redan exporterats – inget skrivet.")
        return
    nights = sorted({d[5] for d in sel})
    res = artportalen.export(sel, species, sites, EXPORTS, min_prob=min_prob, classifier=", ".join(classifier),
                             recorders=recorders, prev_ids=set() if export_all else prev_ids,
                             scope=f"{len(new_files)} resultatfiler, nätter från {', '.join(nights)}"
                                   + (" (alla filer, --alla)" if export_all else " som inte exporterats tidigare"))
    if not res:
        return
    path, n_obs, n_rev, ids = res
    print(f"Skrev {os.path.relpath(path, ROOT)} ({n_obs} fynd, {n_rev} rader att granska; "
          f"{len(new_files)} resultatfiler, nätter {', '.join(nights)})")
    if export_all:
        print("  (--alla: loggen i data/artportalen_exporterat.json ändrades inte)")
        return
    log["exporter"].append({"datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "xlsx": os.path.relpath(path, ROOT).replace("\\", "/"),
                            "min_prob": min_prob, "natter": nights, "filer": new_files, "externid": ids})
    with open(AP_LOG, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    print(f"  {len(new_files)} resultatfiler markerade som exporterade i {os.path.relpath(AP_LOG, ROOT)}")


if __name__ == "__main__":
    a = sys.argv
    if "--add-site" in a:
        i = a.index("--add-site")
        add_site(a[i + 1], a[i + 2], a[i + 3].split(",") if len(a) > i + 3 and not a[i + 3].startswith("--") else ())
        sys.exit(0)
    mp = float(a[a.index("--min-prob") + 1]) if "--min-prob" in a else 0.8
    build(refresh="--refresh" in a, weather="--no-weather" not in a, use_inat="--no-inat" not in a,
          online="--offline" not in a,
          export_ap="--artportalen" in a, min_prob=mp, export_all="--alla" in a,
          exclude={x.strip() for x in a[a.index("--utan") + 1].split(",")} if "--utan" in a else ())
