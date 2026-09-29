# Nattljud – ultraljudsfynd

Webbsida över djur registrerade med fladdermusdetektor och artbestämda automatiskt i
[BTO Acoustic Pipeline](https://www.bto.org/our-science/projects/bto-acoustic-pipeline).
Sidan visar fyndlokaler på karta, arter i systematisk ordning med bild och fakta,
aktivitet under natten, väder från SMHI, jämförelser mellan nätter och lokaler
och klassificerarens säkerhet.

Under *Nytt för lokalen* lyfts den senast tillkomna arten fram per lokal – arter vars
första registrering (över vald sannolikhetsgräns) kom efter lokalens första natt.
Samma art får en etikett *Ny* på sitt kort i artlistan.

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

3. Lokaler finns i `data/sites.json`. Varje rad i CSV-filerna kopplas till en lokal i
   denna ordning:
   1. mappen under `results/` matchar lokalens `folders` (t.ex. `["hemma*"]`)
   2. BATCH NAME matchar lokalens `batches` (t.ex. `["2026_25_sep_*"]`)
   3. CSV-filens koordinater ligger inom lokalens `radius_m` (standard 100 m)
   4. annars skapas en ny lokal från koordinaterna, med namn från OpenStreetMap

   Lägg till en lokal manuellt – från adress eller koordinater – och koppla en mapp:

       python scripts/build.py --add-site "Ängen vid ån" "59.412,18.093" angen
       python scripts/build.py --add-site "Sommarstugan" "Storgatan 1, Norrtälje" stugan

   Övriga fält per lokal:
   - `name`, `note` – visas på sidan
   - `decimals` – publik precision på webbsidan; `2` ≈ 1 km (bra för hemmet)
   - `accuracy_m` – noggrannhet i Artportalen-underlaget
   - `utrustning` – inspelare för lokalen om filnamnet inte avgör (id i equipment.json)
   - `metod_fladdermoss` – tvinga en viss metod i Artportalen för lokalen

4. Utrustning finns i `data/equipment.json`. Inspelaren väljs per fil via början på
   ORIGINAL FILE NAME (t.ex. `DEV_001` → Apodemus Pippyg2), annars lokalens
   `utrustning`, annars `default`. Lägg till en ny inspelare under `recorders` och koppla
   dess filprefix under `devices`. Fältet `artportalen_metod_fladdermoss` styr Metod i
   Artportalen-exporten (Pippyg2: *Autobox med höghastighetsinspelning*).

5. Committa och pusha – GitHub Pages publicerar `docs/`.

## Artportalen

    python scripts/build.py --artportalen                 # minsta sannolikhet 0,8
    python scripts/build.py --artportalen --min-prob 0.9
    python scripts/build.py --artportalen --alla          # allt, oavsett tidigare export

Exporten tar bara med resultatfiler i `results/` som inte exporterats tidigare.
Vilka filer som gått iväg loggas i `data/artportalen_exporterat.json` (filnamn utan
mapp, så filerna kan flyttas till undermappar). Ta bort en post där för att exportera
om de filerna. `--alla` tar med allt och ändrar inte loggen. Om en art redan
rapporterats för en natt och fler inspelningar från samma natt dyker upp senare får
det nya fyndet ett löpnummer i Externid, och Granska-bladet säger till.

Skriver `exports/artportalen_<datum>_<tid>.xlsx` med samma kolumner som Artportalens
Excelmall (version 4.17), ett blad per artgrupp:

- **Fladdermöss** – Antal = antal registreringar, Enhet *Registreringar*, Aktivitet *Aktiv*,
  Metod från inspelaren
- **Ryggradslösa djur** – vårtbitare, Aktivitet *Spel*, Metod *Ultraljudsdetektor*
- **Däggdjur (exkl.fladdermöss)** – t.ex. näbbmöss (mallen saknar ultraljud som metod)
- **Granska** – alla taxa, varför de är med eller inte, och vad som bör kontrolleras

Import: sätt koordinatsystem *SWEREF99 TM* under Min profil i Artportalen, markera
rubrikraden och fynden på ett blad, kopiera och klistra in på
artportalen.se/ImportSighting. Fynden hamnar sedan under *Granska & publicera*.
Kontrollera enstaka registreringar och *Myotis* i spektrogram innan du publicerar.

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
