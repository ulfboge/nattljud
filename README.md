# Nattljud – ultraljudsfynd

Webbsida över djur registrerade med fladdermusdetektor och artbestämda automatiskt i
[BTO Acoustic Pipeline](https://www.bto.org/our-science/projects/bto-acoustic-pipeline).
Sidan visar fyndlokaler på karta, arter i systematisk ordning med bild och fakta,
aktivitet under natten och klassificerarens säkerhet.

## Lägga till nya inspelningar

1. Exportera resultat-CSV från BTO Acoustic Pipeline och lägg dem i `results/`.
2. Kör `python scripts/build.py` (Python 3, inga extra paket).
   Nya arter hämtar taxonomi (GBIF), svenskt namn, text och bild (Wikipedia/Commons)
   och cachas i `data/species_cache.json`. `--refresh` hämtar om allt.
3. Nya lokaler läggs till i `data/sites.json` med namn från OpenStreetMap.
   Byt gärna `name`, skriv en `note`, och sätt `decimals` till t.ex. `2` (≈1 km)
   om exakt position inte ska synas publikt.
4. Committa och pusha – GitHub Pages publicerar `docs/`.

## Titta lokalt

    cd docs
    python -m http.server 8000

och öppna http://localhost:8000.

## Struktur

    results/                 rå-CSV från BTO
    scripts/build.py         CSV -> docs/data/data.json
    data/sites.json          lokaler (redigerbar)
    data/species_cache.json  artinfo från GBIF/Wikipedia
    docs/                    webbsidan (GitHub Pages)

Bilder: Wikimedia Commons, se licenser på sidan. Texter: Wikipedia (CC BY-SA).
Svenska fladdermusnamn enligt Naturvårdsverket.
