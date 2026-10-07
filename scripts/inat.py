"""iNaturalist och Dyntaxa för artträdet.

- Observationer för en användare hämtas från iNaturalists öppna API (bara publika fynd, ingen inloggning).
- Taxonomin (alla rangnivåer: rike, stam, klass, underklass, ordning, överfamilj, familj, underfamilj …)
  kommer från iNaturalist, som även har utländska arter.
- Dyntaxa (via GBIF) ger svenska namn där iNaturalist saknar dem, och visar om Dyntaxa använder ett
  annat vetenskapligt namn än iNaturalist.

Allt cachas i data/inat_cache.json (observationer) och data/taxonomy_cache.json (taxa, namnuppslag,
Dyntaxa), så att bygget fungerar utan nät och bara hämtar det som är nytt.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.inaturalist.org/v1"
SWEDEN = 7599  # iNaturalists place_id för Sverige (styr vilket svenskt namn som föredras)
DYNTAXA_DATASET = "de8934f4-a136-481c-a87a-b0b202b80a31"
UA = {"User-Agent": "nattljud/1.0 (github.com/ulfboge/nattljud)"}
# Rangnivåer som tas med i trädet (iNaturalists namn). Lägre nivåer än släkte (sektion m.m.) hoppas över.
TREE_RANKS = ["kingdom", "phylum", "subphylum", "superclass", "class", "subclass", "infraclass", "superorder",
              "order", "suborder", "infraorder", "parvorder", "superfamily", "epifamily", "family", "subfamily",
              "supertribe", "tribe", "subtribe", "genus"]
ICONIC_SV = {"Insecta": "Insekter", "Plantae": "Växter", "Arachnida": "Spindeldjur", "Fungi": "Svampar",
             "Mollusca": "Blötdjur", "Mammalia": "Däggdjur", "Aves": "Fåglar", "Actinopterygii": "Strålfeniga fiskar",
             "Reptilia": "Kräldjur", "Amphibia": "Groddjur", "Animalia": "Övriga djur", "Chromista": "Kromister",
             "Protozoa": "Protozoer"}


def _get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                print("  ! misslyckades:", url, e, file=sys.stderr)
                return None
            time.sleep(5 * (i + 1) if "429" in str(e) else 2)


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0, separators=(",", ":"))


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


# ---------------------------------------------------------------- observationer
def fetch_observations(user, cache_path, online=True):
    """Alla publika observationer för användaren (kompakt form). Faller tillbaka på cachen utan nät."""
    cache = _load(cache_path, {"user": user, "observations": []})
    if not online:
        return cache["observations"]
    obs, id_above = [], 0
    while True:
        r = _get(f"{API}/observations?user_login={urllib.parse.quote(user)}&per_page=200&order_by=id&order=asc"
                 f"&id_above={id_above}&locale=sv")
        if r is None:
            print("  iNaturalist: kunde inte hämta – använder cachen")
            return cache["observations"]
        res = r.get("results", [])
        if not res:
            break
        obs += [_compact(o) for o in res]
        id_above = res[-1]["id"]
        time.sleep(1)
    obs = [o for o in obs if o]
    _save(cache_path, {"user": user, "fetched": time.strftime("%Y-%m-%d %H:%M"), "observations": obs})
    return obs


def _compact(o):
    if not o.get("location") or not o.get("taxon"):
        return None
    lat, lon = (float(x) for x in o["location"].split(","))
    t = o.get("time_observed_at") or ""
    photo = (o.get("photos") or [{}])[0]
    return {
        "id": o["id"], "taxon": o["taxon"]["id"], "date": o.get("observed_on") or "",
        "time": t[11:16] if len(t) >= 16 else "", "lat": round(lat, 6), "lon": round(lon, 6),
        "acc": o.get("positional_accuracy"), "obscured": bool(o.get("obscured")),
        "quality": o.get("quality_grade", ""), "place": o.get("place_guess") or "",
        "photo": (photo.get("url") or "").replace("/square.", "/medium."),
        "license": photo.get("license_code") or "", "sounds": len(o.get("sounds") or []),
    }


# ---------------------------------------------------------------- taxonomi
class Taxonomy:
    def __init__(self, cache_path, online=True):
        self.cache_path, self.online = cache_path, online
        c = _load(cache_path, {})
        self.taxa = c.get("taxa", {})          # id -> {name, rank, sv, parent, anc, wiki, iconic}
        self.names = c.get("names", {})        # vetenskapligt namn -> id (eller null)
        self.dyntaxa = c.get("dyntaxa", {})    # vetenskapligt namn -> {id, name, sv} (eller {})

    def save(self):
        _save(self.cache_path, {"taxa": self.taxa, "names": self.names, "dyntaxa": self.dyntaxa})

    def lookup(self, name):
        """iNaturalist-id för ett vetenskapligt namn (följer synonymer, t.ex. Eptesicus → Cnephaeus)."""
        if name in self.names or not self.online:
            return self.names.get(name)
        r = _get(f"{API}/taxa?q={urllib.parse.quote(name)}&per_page=10&is_active=true") or {}
        res = r.get("results", [])
        hit = next((t for t in res if t["name"] == name), None)
        if hit is None:  # namnet är synonym: iNat matchar på matched_term
            hit = next((t for t in res if (t.get("matched_term") or "").lower() == name.lower()), None)
        self.names[name] = hit["id"] if hit else None
        self._tick()
        time.sleep(0.5)
        return self.names[name]

    def ensure(self, ids):
        """Hämta taxa (med alla förfäder) som inte finns i cachen."""
        missing = sorted({int(i) for i in ids if i is not None and str(i) not in self.taxa})
        if missing and self.online:
            print(f"  iNaturalist: hämtar {len(missing)} taxa")
        for k in range(0, len(missing) if self.online else 0, 30):
            r = _get(f"{API}/taxa/{','.join(map(str, missing[k:k + 30]))}?locale=sv&preferred_place_id={SWEDEN}") or {}
            for t in r.get("results", []):
                self._store(t, full=True)
                for a in t.get("ancestors", []):
                    if str(a["id"]) not in self.taxa:
                        self._store(a)
            self.save()
            time.sleep(1)

    def _store(self, t, full=False):
        anc = [int(x) for x in (t.get("ancestry") or "").split("/") if x]
        rec = {"name": t["name"], "rank": t["rank"], "sv": _cap(t.get("preferred_common_name") or ""),
               "parent": anc[-1] if anc else None, "iconic": t.get("iconic_taxon_name")}
        if full:
            # standardbilden om den är fritt licensierad, annars första fritt licensierade bland taxonbilderna
            cands = [t.get("default_photo") or {}] + [(x or {}).get("photo") or {} for x in t.get("taxon_photos") or []]
            ph = next((x for x in cands if x.get("license_code") and x.get("medium_url")), {})
            # bara fritt licensierade bilder (iNaturalist anger licens per foto)
            rec["photo"] = {"src": ph.get("medium_url"), "artist": ph.get("attribution", ""),
                            "license": (ph.get("license_code") or "").upper(),
                            "page": f"https://www.inaturalist.org/photos/{ph.get('id')}"} \
                if ph.get("license_code") and ph.get("medium_url") else None
        if full and t.get("wikipedia_summary"):
            rec["wiki"] = {"extract": t["wikipedia_summary"], "url": t.get("wikipedia_url") or ""}
        self.taxa[str(t["id"])] = {**self.taxa.get(str(t["id"]), {}), **rec}

    def photos(self, ids):
        """Standardbild för taxa (hämtar om taxa som cachats innan bilder sparades)."""
        old = [i for i in ids if i is not None and "photo" not in (self.get(i) or {})]
        for i in old:
            self.taxa.pop(str(i), None)
        self.ensure(old)
        return {i: (self.get(i) or {}).get("photo") for i in ids}

    def get(self, i):
        return self.taxa.get(str(i))

    def path(self, i):
        """Förfäder (rot först) som finns i TREE_RANKS, följt av taxonet självt."""
        out, cur = [], self.get(i)
        seen = set()
        while cur and cur.get("parent") and cur["parent"] not in seen:
            seen.add(cur["parent"])
            p = self.get(cur["parent"])
            if p and p["rank"] in TREE_RANKS:
                out.append(cur["parent"])
            cur = p
        return list(reversed(out)) + [int(i)]

    # ------------------------------------------------------------ Dyntaxa
    def prefetch_dyntaxa(self, names, workers=8):
        """Slå upp många namn parallellt (första bygget kan gälla tusen namn)."""
        todo = sorted({n for n in names if n and n not in self.dyntaxa})
        if not todo or not self.online:
            return
        print(f"  Dyntaxa: slår upp {len(todo)} namn", flush=True)
        from concurrent.futures import ThreadPoolExecutor
        self._bulk = True
        try:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(self.dyntaxa_for, todo))
        finally:
            self._bulk = False
        self.save()

    def dyntaxa_for(self, name):
        """{id, name (accepterat namn i Dyntaxa), sv} eller {} om namnet saknas i Dyntaxa."""
        if name in self.dyntaxa or not self.online:
            return self.dyntaxa.get(name) or {}
        r = _get(f"https://api.gbif.org/v1/species/search?datasetKey={DYNTAXA_DATASET}"
                 f"&q={urllib.parse.quote(name)}&limit=10")
        if r is None:
            return {}  # nätfel – sparas inte, försöker igen nästa bygge
        res = [x for x in r.get("results", []) if x.get("canonicalName") == name]
        out = {}
        for x in res:
            tid = x.get("taxonID") or ""
            if tid.startswith("urn:lsid:dyntaxa.se:Taxon:"):
                out = {"id": int(tid.rsplit(":", 1)[1]), "name": name, "sv": _sv_vernacular(x)}
                break
        else:
            for x in res:  # synonym → följ till accepterat taxon
                if x.get("acceptedKey"):
                    a = _get(f"https://api.gbif.org/v1/species/{x['acceptedKey']}") or {}
                    tid = a.get("taxonID") or ""
                    if tid.startswith("urn:lsid:dyntaxa.se:Taxon:"):
                        out = {"id": int(tid.rsplit(":", 1)[1]), "name": a.get("canonicalName"),
                               "sv": _sv_vernacular(a)}
                        break
        self.dyntaxa[name] = out
        self._tick()
        return out

    def _tick(self):
        if getattr(self, "_bulk", False):
            return
        self._n = getattr(self, "_n", 0) + 1
        if self._n % 25 == 0:
            self.save()


def _sv_vernacular(x):
    v = [n.get("vernacularName") for n in x.get("vernacularNames", []) if n.get("language") in (None, "", "swe", "sv")]
    if not v and x.get("vernacularName"):
        v = [x["vernacularName"]]
    return _cap(v[0]) if v else ""
