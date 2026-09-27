#!/usr/bin/env python3
"""
Bygger webbsidans data från BTO Acoustic Pipeline-exporter.

  python scripts/build.py            # läs results/*.csv -> docs/data/*.json
  python scripts/build.py --refresh  # hämta om artinfo från GBIF/Wikipedia

Artinfo (taxonomi, svenska namn, bild, text, GBIF-fynd) cachas i
data/species_cache.json så att nätet bara behövs för nya arter.
Lokalnamn kan redigeras i data/sites.json.
"""
import csv, glob, json, os, sys, time, urllib.parse, urllib.request
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "data", "species_cache.json")
SITES = os.path.join(ROOT, "data", "sites.json")
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
    for r in dy.get("results", []):
        tid = r.get("taxonID") or ""
        if tid.startswith("urn:lsid:dyntaxa.se:Taxon:") and r.get("canonicalName") == name:
            info["dyntaxaId"] = int(tid.rsplit(":", 1)[1])
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


def build(refresh=False):
    files = sorted(glob.glob(os.path.join(RESULTS, "*.csv")))
    rows = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rows += list(csv.DictReader(fh))
    print(f"{len(files)} filer, {len(rows)} detektioner")

    # --- lokaler ---
    sites = json.load(open(SITES, encoding="utf-8")) if os.path.exists(SITES) else []
    site_idx = {(s["lat"], s["lon"]): i for i, s in enumerate(sites)}
    for r in rows:
        key = (round(float(r["LATITUDE"]), 5), round(float(r["LONGITUDE"]), 5))
        if key not in site_idx:
            print("  ny lokal:", key)
            site_idx[key] = len(sites)
            sites.append({"id": f"L{len(sites)+1}", "name": site_name(*key),
                          "lat": key[0], "lon": key[1], "decimals": 5, "note": ""})
            time.sleep(1)
    json.dump(sites, open(SITES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

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
        key = (round(float(r["LATITUDE"]), 5), round(float(r["LONGITUDE"]), 5))
        det.append([
            sp_index[r["SCIENTIFIC NAME"].strip() or "Oidentifierad"],
            site_idx[key],
            f"{y}-{mth}-{d}T{r['TIME']}",
            float(r["PROBABILITY"] or 0),
            r["CALL TYPE"].strip(),
            f"{sy}-{sm}-{sd}",
            r["ORIGINAL FILE NAME"],
        ])
    det.sort(key=lambda x: x[2])
    classifier = sorted({r["CLASSIFIER NAME"] for r in rows})
    # Publik version av lokalerna: sätt "decimals" i data/sites.json (t.ex. 2 ≈ 1 km)
    # om exakt position inte ska synas på webben.
    pub_sites = []
    for st in sites:
        dec = st.get("decimals", 5)
        pub_sites.append({**st, "lat": round(st["lat"], dec), "lon": round(st["lon"], dec)})
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "classifier": classifier,
           "fields": ["species", "site", "time", "prob", "callType", "night", "file"],
           "species": species, "sites": pub_sites, "detections": det}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Skrev docs/data/data.json ({len(species)} taxa, {len(sites)} lokaler)")


if __name__ == "__main__":
    build(refresh="--refresh" in sys.argv)
