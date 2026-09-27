# Nattljud – ultraljudsfynd

Webbsida över djur registrerade med fladdermusdetektor och artbestämda automatiskt i
[BTO Acoustic Pipeline](https://www.bto.org/our-science/projects/bto-acoustic-pipeline).
Sidan visar fyndlokaler på karta, arter i systematisk ordning med bild och fakta,
aktivitet under natten, väder från SMHI, jämförelser mellan nätter och lokaler
och klassificerarens säkerhet.

## Lägga till nya inspelningar

1. Exportera resultat-CSV från BTO Acoustic Pipeline och lägg dem under `results/`.
   Filerna läses rekursivt, så en undermapp per natt och lokal fungerar bra:

       results/
         2026-09-25_stocksund/   *.csv
         2026-10-02_stocksund/   *.csv
         2026-10-03_rinkeby/     *.csv

   Natt och lokal läses ur CSV-filerna (SURVEY DATE och koordinaterna), inte ur
   mappnamnen – mappar är bara för din egen ordning. Om samma export råkar ligga
   dubbelt räknas varje inspelning bara en gång.

2. Kör `python scripts/build.py` (Python 3, inga extra paket för sidan).
   - Nya arter: taxonomi (GBIF), Dyntaxa-id, svenskt namn, text och bild
     (Wikipedia/Commons) cachas i `data/species_cache.json`. `--refresh` hämtar om allt.
   - Väder: timvärden från SMHI:s närmaste stationer per natt och lokal,
     cachas i `data/weather_cache.json`. `--no-weather` hoppar över.

3. Nya lokaler läggs till i `data/sites.json` med namn från OpenStreetMap. Fält:
   - `name`, `note` – visas på sidan
   - `decimals` – publik precision; `2` ≈ 1 km om exakt position inte ska synas
   - `accuracy_m` – noggrannhet i Artportalen-underlaget (standard 50 m)

4. Committa och pusha – GitHub Pages publicerar `docs/`.

## Artportalen

    python scripts/build.py --artportalen                 # minsta sannolikhet 0,8
    python scripts/build.py --artportalen --min-prob 0.9

Skriver `exports/artportalen_<datum>.xlsx`:

- **Fynd** – en rad per art, natt och lokal där minst en registrering når gränsen.
  SWEREF 99 TM-koordinater, start-/sluttid, Dyntaxa-id och färdiga kommentarer
  (antal registreringar, lätestyp, sannolikhet, klassificerare).
- **Granska** – alla taxa med statistik, även de som inte kom med och varför.

Kolumnerna följer Artportalens fält men är inte en kopia av den officiella
importmallen (hämtas inloggad på artportalen.se/ImportSighting). Kontrollera
fynden – särskilt enstaka registreringar och *Myotis* – innan du rapporterar.

## Ljudfiler

Lägg wav-filerna i `audio/` med samma mappstruktur som `results/`. Mappen är
undantagen från git (filerna är stora); spektrogram och korta ljudexempel per art
kan genereras därifrån till `docs/`.

## Titta lokalt

    cd docs
    python -m http.server 8000

och öppna http://localhost:8000.

## Struktur

    results/                 rå-CSV från BTO (valfria undermappar)
    audio/                   wav-filer (ej i git)
    scripts/build.py         CSV -> docs/data/data.json (+ Artportalen-export)
    scripts/smhi.py          väder från SMHI:s öppna data
    scripts/artportalen.py   Artportalen-underlag (kräver openpyxl)
    scripts/geo.py           SWEREF 99 TM, sol-tider, svensk tid
    data/sites.json          lokaler (redigerbar)
    data/*_cache.json        artinfo och väder
    exports/                 Artportalen-filer (ej i git)
    docs/                    webbsidan (GitHub Pages)

Bilder: Wikimedia Commons, se licenser på sidan. Texter: Wikipedia (CC BY-SA).
Väder: SMHI (CC BY 4.0). Svenska fladdermusnamn enligt Naturvårdsverket.
