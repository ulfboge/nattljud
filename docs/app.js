/* Nattljud – visar BTO Acoustic Pipeline-resultat. Data byggs av scripts/build.py. */
(() => {
  "use strict";

  // ---------- svenska namn på högre taxa ----------
  const TAXA_SV = {
    Mammalia: "Däggdjur", Aves: "Fåglar", Insecta: "Insekter", Amphibia: "Groddjur",
    Chiroptera: "Fladdermöss", Orthoptera: "Hopprätvingar", Soricomorpha: "Insektsätare",
    Eulipotyphla: "Insektsätare", Rodentia: "Gnagare",
    Vespertilionidae: "Läderlappar", Tettigoniidae: "Vårtbitare", Soricidae: "Näbbmöss",
    Gryllidae: "Syrsor", Muridae: "Råttdjur",
  };
  const AP_IMPORT = "https://www.artportalen.se/ImportSighting";
  const CLASS_ORDER = ["Mammalia", "Aves", "Amphibia", "Insecta"];
  // Färg följer gruppen (entiteten), aldrig rangordningen.
  const GROUPS = [
    { key: "bat", sv: "Fladdermöss", color: "var(--s1)" },
    { key: "bush-cricket", sv: "Vårtbitare", color: "var(--s2)" },
    { key: "bird", sv: "Fåglar", color: "var(--s3)" },
    { key: "terrestrial mammal", sv: "Övriga däggdjur", color: "var(--s4)" },
    { key: "", sv: "Oidentifierat", color: "var(--s0)" },
  ];
  const groupOf = k => GROUPS.find(g => g.key === k) || { key: k, sv: k, color: "var(--s0)" };
  const svTax = n => (n && TAXA_SV[n]) || n || "–";

  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = n => n.toLocaleString("sv-SE");
  const median = a => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  let D, map, siteLayer, NEW = new Map();
  const state = { minProb: 0.5, night: "all", site: "all" };

  // ---------- tid ----------
  // Minuter från kl 12 natten börjar (natt = SURVEY DATE), så att 19:00→420, 03:00→900.
  function relMin(t, night) {
    const day = (Date.UTC(+t.slice(0, 4), +t.slice(5, 7) - 1, +t.slice(8, 10)) -
                 Date.UTC(+night.slice(0, 4), +night.slice(5, 7) - 1, +night.slice(8, 10))) / 864e5;
    return day * 1440 + (+t.slice(11, 13)) * 60 + (+t.slice(14, 16)) - 720;
  }
  const clock = rel => { const m = ((rel + 720) % 1440 + 1440) % 1440; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; };
  const stockholmRel = date => {
    const p = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Stockholm", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
    const h = +p.find(x => x.type === "hour").value, m = +p.find(x => x.type === "minute").value;
    const lm = h * 60 + m; return lm >= 720 ? lm - 720 : lm + 720;
  };
  const nightLabel = n => {
    const d = new Date(n + "T12:00:00Z"), d2 = new Date(d.getTime() + 864e5);
    const mo = d.toLocaleDateString("sv-SE", { month: "short", timeZone: "UTC" });
    const mo2 = d2.toLocaleDateString("sv-SE", { month: "short", timeZone: "UTC" });
    return mo === mo2 ? `${d.getUTCDate()}–${d2.getUTCDate()} ${mo} ${d.getUTCFullYear()}` : `${d.getUTCDate()} ${mo}–${d2.getUTCDate()} ${mo2} ${d2.getUTCFullYear()}`;
  };
  const shortTime = t => `${+t.slice(8, 10)}/${+t.slice(5, 7)} ${t.slice(11, 16)}`;

  // ---------- filter ----------
  const inScope = d => (state.night === "all" || d[5] === state.night) && (state.site === "all" || d[1] === +state.site);
  const scoped = () => D.detections.filter(inScope);
  const passing = () => D.detections.filter(d => inScope(d) && d[3] >= state.minProb);

  // ---------- tooltip ----------
  const tip = $("#tip");
  document.addEventListener("mousemove", e => {
    const el = e.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    tip.innerHTML = el.dataset.tip; tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 12, y = e.clientY - h - 10;
    if (x + w > innerWidth - 8) x = e.clientX - w - 12;
    if (y < 8) y = e.clientY + 16;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });

  // ---------- init ----------
  fetch("data/data.json").then(r => r.json()).then(data => {
    D = data;
    D.species.forEach((s, i) => { s.i = i; s.probs = []; });
    D.detections.forEach(d => D.species[d[0]].probs.push(d[3]));
    const nights = [...new Set(D.detections.map(d => d[5]))].sort();
    $("#night").innerHTML = `<option value="all">Alla nätter (${nights.length})</option>` + nights.map(n => `<option value="${n}">${nightLabel(n)}</option>`).join("");
    $("#site").innerHTML = `<option value="all">Alla lokaler (${D.sites.length})</option>` + D.sites.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join("");
    $("#classifier").textContent = D.classifier.join(", ");
    $("#gen").textContent = `Data uppdaterad ${D.generated}.`;
    $("#prob").addEventListener("input", e => { state.minProb = +e.target.value; render(); });
    $("#night").addEventListener("change", e => { state.night = e.target.value; render(); });
    $("#site").addEventListener("change", e => { state.site = e.target.value; render(); });
    renderCredits();
    initMap();
    render();
  }).catch(err => { $("#lede").textContent = "Kunde inte läsa data/data.json – kör scripts/build.py. (" + err + ")"; });

  function render() {
    $("#probOut").textContent = state.minProb.toFixed(2);
    const all = scoped(), pass = passing();
    const hid = all.length - pass.length;
    const hidTaxa = new Set(all.map(d => d[0])).size - new Set(pass.map(d => d[0])).size;
    $("#hiddenNote").textContent = hid ? `${fmt(hid)} detektioner under gränsen döljs${hidTaxa ? ` (${hidTaxa} taxa försvinner helt)` : ""}.` : "Inga detektioner döljs.";
    NEW = newBySite();
    renderLede(pass); renderTiles(pass); renderNew(); renderMap(pass); renderActivity(pass); renderWeather(); renderCompare(); renderEquipment(); renderTaxonomy(pass); renderTable(all);
  }

  function counts(dets) { const c = new Map(); dets.forEach(d => c.set(d[0], (c.get(d[0]) || 0) + 1)); return c; }
  const isTaxon = s => s.sci !== "Oidentifierad";
  const isSpecies = s => s.rank === "species";

  function renderLede(pass) {
    const nights = new Set(pass.map(d => d[5])).size, sites = new Set(pass.map(d => d[1])).size;
    const c = counts(pass);
    const bats = D.species.filter(s => s.group === "bat" && isSpecies(s) && c.get(s.i)).length;
    $("#lede").textContent = `${fmt(pass.length)} registreringar från ${nights} ${nights === 1 ? "natt" : "nätter"} på ${sites} ${sites === 1 ? "lokal" : "lokaler"}, automatiskt artbestämda. ${bats} fladdermusarter över vald sannolikhetsgräns.`;
  }

  function renderTiles(pass) {
    const c = counts(pass);
    const sp = D.species.filter(s => isSpecies(s) && c.get(s.i));
    const bats = pass.filter(d => D.species[d[0]].group === "bat").length;
    const tiles = [
      [fmt(pass.length), "detektioner"],
      [sp.length, "arter"],
      [sp.filter(s => s.group === "bat").length, "fladdermusarter"],
      [fmt(bats), "fladdermusregistreringar"],
      [new Set(pass.map(d => d[5])).size, "nätter"],
      [new Set(pass.map(d => d[1])).size, "lokaler"],
    ];
    $("#tiles").innerHTML = tiles.map(([v, l]) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  }

  // ---------- nytt för lokalen ----------
  // Per lokal: första natten varje art registrerats (över vald gräns). Arter vars första natt är
  // senare än lokalens första natt räknas som tillskott; den senaste av dem lyfts fram.
  function newBySite() {
    const out = new Map();
    D.sites.forEach((_, i) => out.set(i, { nights: new Set(), first: new Map() }));
    D.detections.forEach(d => {
      const o = out.get(d[1]); o.nights.add(d[5]);
      if (d[3] < state.minProb || !isSpecies(D.species[d[0]])) return;
      const f = o.first.get(d[0]);
      if (!f || d[5] < f.night) o.first.set(d[0], { night: d[5], n: 1, max: d[3] });
      else if (d[5] === f.night) { f.n++; f.max = Math.max(f.max, d[3]); }
    });
    out.forEach(o => {
      o.nights = [...o.nights].sort();
      o.start = o.nights[0];
      o.added = [...o.first].filter(([, f]) => f.night > o.start)
        .map(([sp, f]) => ({ sp, ...f })).sort((a, b) => b.night.localeCompare(a.night) || b.n - a.n);
      o.latest = o.added.length ? o.added.filter(a => a.night === o.added[0].night) : [];
    });
    return out;
  }
  const newestSpecies = () => {
    const s = new Map();
    NEW.forEach((o, si) => { if (state.site === "all" || si === +state.site) o.latest.forEach(a => s.has(a.sp) || s.set(a.sp, { ...a, site: si })); });
    return s;
  };

  function renderNew() {
    const html = [...NEW].filter(([si, o]) => (state.site === "all" || si === +state.site) && o.nights.length).map(([si, o]) => {
      const site = D.sites[si], nSp = o.first.size;
      const head = `<h3>${esc(site.name)}</h3><p class="sub">${o.nights.length} ${o.nights.length === 1 ? "natt" : "nätter"} · ${nSp} arter · första natten ${nightLabel(o.start)}</p>`;
      if (o.nights.length === 1) return `<div class="new-site">${head}<p class="sub">Bara en natt hittills – nya arter visas här från nästa natt.</p></div>`;
      if (!o.added.length) return `<div class="new-site">${head}<p class="sub">Inga nya arter sedan första natten.</p></div>`;
      const hl = o.latest.map(a => {
        const s = D.species[a.sp];
        return `<button class="new-hl" data-sp="${a.sp}"><span class="thumb"${s.image ? ` style="background-image:url('${esc(s.image.src)}')"` : ""}></span>
          <span><span class="lbl">Senast nya art</span><br><span class="nm">${esc(s.sv || s.sci)}</span> <i class="dt">${esc(s.sci)}</i><br>
          <span class="dt">Första gången natten ${nightLabel(a.night)} · ${a.n} ${a.n === 1 ? "registrering" : "registreringar"}, högsta p ${a.max.toFixed(2)}</span></span></button>`;
      }).join("");
      const rest = o.added.filter(a => a.night !== o.latest[0].night);
      const list = rest.length ? `<ul class="new-list">${rest.map(a => `<li><a data-sp="${a.sp}">${esc(D.species[a.sp].sv || D.species[a.sp].sci)}</a><span class="when">${nightLabel(a.night)}</span></li>`).join("")}</ul>` : "";
      return `<div class="new-site">${head}${hl}${list}</div>`;
    }).join("");
    $("#newsp").innerHTML = html || `<p class="sub">Inga lokaler med data.</p>`;
    $("#newsp").querySelectorAll("[data-sp]").forEach(b => b.addEventListener("click", () => openSpecies(+b.dataset.sp)));
  }

  // ---------- karta ----------
  function initMap() {
    map = L.map("map", { scrollWheelZoom: false });
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri World Imagery" });
    L.control.layers({ Karta: osm, Flygfoto: sat }).addTo(map);
    siteLayer = L.layerGroup().addTo(map);
    const b = L.latLngBounds(D.sites.map(s => [s.lat, s.lon]));
    D.sites.length > 1 ? map.fitBounds(b.pad(0.3)) : map.setView(b.getCenter(), 14);
  }
  function renderMap(pass) {
    siteLayer.clearLayers();
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--s1").trim();
    D.sites.forEach((s, i) => {
      const dets = pass.filter(d => d[1] === i);
      const c = [...counts(dets)].sort((a, b) => b[1] - a[1]);
      const nBat = c.filter(([k]) => D.species[k].group === "bat");
      const lt = (NEW.get(i) || {}).latest || [];
      const html = `<b>${esc(s.name)}</b><br>${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}${s.note ? `<br>${esc(s.note)}` : ""}
        ${lt.length ? `<br><b>Senast nya art:</b> ${lt.map(a => esc(D.species[a.sp].sv || D.species[a.sp].sci)).join(", ")} (${nightLabel(lt[0].night)})` : ""}
        <br>${fmt(dets.length)} detektioner, ${nBat.length} fladdermustaxa<ul>${c.map(([k, n]) => `<li>${esc(D.species[k].sv || D.species[k].sci)}: ${fmt(n)}</li>`).join("")}</ul>`;
      L.circleMarker([s.lat, s.lon], { radius: 8 + Math.sqrt(dets.length) / 6, color: "#fff", weight: 2, fillColor: accent, fillOpacity: .85 })
        .bindPopup(html).bindTooltip(s.name).addTo(siteLayer);
    });
  }

  // ---------- aktivitet ----------
  function sunTimes() {
    const nights = state.night === "all" ? [...new Set(D.detections.map(d => d[5]))].sort() : [state.night];
    const site = D.sites[state.site === "all" ? 0 : +state.site];
    if (!window.SunCalc || !site) return null;
    const t = SunCalc.getTimes(new Date(nights[0] + "T12:00:00Z"), site.lat, site.lon);
    const t2 = SunCalc.getTimes(new Date(new Date(nights[0] + "T12:00:00Z").getTime() + 864e5), site.lat, site.lon);
    return { sunset: stockholmRel(t.sunset), sunrise: stockholmRel(t2.sunrise), dusk: stockholmRel(t.dusk), dawn: stockholmRel(t2.dawn), approx: nights.length > 1 };
  }

  function barChart(dets, color, sun, range, label) {
    const BIN = 15, W = 480, H = 140, m = { l: 34, r: 8, t: 14, b: 20 };
    const [x0, x1] = range, nb = Math.ceil((x1 - x0) / BIN);
    const bins = new Array(nb).fill(0);
    dets.forEach(d => { const b = Math.floor((relMin(d[2], d[5]) - x0) / BIN); if (b >= 0 && b < nb) bins[b]++; });
    const max = Math.max(1, ...bins);
    const step = niceStep(max), top = Math.ceil(max / step) * step;
    const iw = W - m.l - m.r, ih = H - m.t - m.b, bw = iw / nb;
    const X = v => m.l + (v - x0) / (x1 - x0) * iw, Y = v => m.t + ih - v / top * ih;
    let g = "";
    for (let v = 0; v <= top; v += step) g += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 5}" y="${Y(v) + 3}" text-anchor="end">${fmt(v)}</text>`;
    for (let h = Math.ceil(x0 / 60) * 60; h <= x1; h += 120) g += `<text x="${X(h)}" y="${H - 5}" text-anchor="middle">${clock(h).slice(0, 2)}</text>`;
    if (sun) {
      [["sunset", "Solnedgång"], ["sunrise", "Soluppgång"]].forEach(([k, name]) => {
        if (sun[k] >= x0 && sun[k] <= x1) g += `<line class="sun" x1="${X(sun[k])}" x2="${X(sun[k])}" y1="${m.t - 6}" y2="${m.t + ih}" data-tip="${name} ${clock(sun[k])}${sun.approx ? " (första natten)" : ""}"/><text class="sunl" x="${X(sun[k]) + (k === "sunset" ? 3 : -3)}" y="${m.t - 4}" text-anchor="${k === "sunset" ? "start" : "end"}">${k === "sunset" ? "☾ " : ""}${clock(sun[k])}${k === "sunrise" ? " ☀" : ""}</text>`;
      });
    }
    let bars = "";
    bins.forEach((v, i) => {
      const x = m.l + i * bw, tipTxt = `${clock(x0 + i * BIN)}–${clock(x0 + (i + 1) * BIN)}<br><b>${fmt(v)}</b> ${label}`;
      bars += `<rect class="hit" x="${x}" y="${m.t}" width="${bw}" height="${ih}" data-tip="${tipTxt}"/>`;
      if (v) { const y = Y(v), h = Math.max(1, m.t + ih - y); bars += `<path class="bar" fill="${color}" d="${roundTop(x + 1, y, Math.max(1, bw - 2), h, Math.min(2, (bw - 2) / 2))}" data-tip="${tipTxt}"/>`; }
    });
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)} per 15 minuter">${g}${bars}<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/></svg>`;
  }
  const roundTop = (x, y, w, h, r) => r <= 0 || h < r ? `M${x},${y + h}V${y}H${x + w}V${y + h}Z` : `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  function niceStep(max) { const raw = max / 3, p = 10 ** Math.floor(Math.log10(raw)), f = raw / p; return Math.max(1, (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p); }
  function nightRange(dets, sun) {
    const rel = dets.map(d => relMin(d[2], d[5]));
    let lo = Math.min(...rel, sun ? sun.sunset - 30 : Infinity), hi = Math.max(...rel, sun ? sun.sunrise + 30 : -Infinity);
    if (!isFinite(lo)) { lo = 360; hi = 1080; }
    return [Math.floor(lo / 60) * 60, Math.ceil(hi / 60) * 60];
  }

  function renderActivity(pass) {
    const sun = sunTimes(), range = nightRange(scoped(), sun);
    const out = GROUPS.map(g => {
      const dets = pass.filter(d => D.species[d[0]].group === g.key);
      if (!dets.length) return "";
      return `<div class="chart"><h4><span class="sw" style="background:${g.color}"></span>${g.sv} <span class="n">${fmt(dets.length)}</span></h4>${barChart(dets, g.color, sun, range, "detektioner")}</div>`;
    }).join("");
    $("#activity").innerHTML = out || `<p class="sub">Inga detektioner över gränsen.</p>`;
  }

  // ---------- systematik ----------
  function renderTaxonomy(pass) {
    const c = counts(pass), all = counts(scoped()), fresh = newestSpecies();
    const taxa = D.species.filter(s => isTaxon(s) && all.get(s.i));
    const tree = {};
    taxa.forEach(s => {
      const cl = s.class || "Övrigt", or = s.order || "", fa = s.family || "";
      ((tree[cl] ??= {})[or] ??= {})[fa] ??= [];
      tree[cl][or][fa].push(s);
    });
    const classes = Object.keys(tree).sort((a, b) => (CLASS_ORDER.indexOf(a) + 99 * (CLASS_ORDER.indexOf(a) < 0)) - (CLASS_ORDER.indexOf(b) + 99 * (CLASS_ORDER.indexOf(b) < 0)));
    const card = s => {
      const n = c.get(s.i) || 0, med = median(s.probs);
      const img = s.image ? `style="background-image:url('${esc(s.image.src)}')"` : "";
      const nw = fresh.get(s.i);
      const tag = nw ? `<span class="newtag">Ny${D.sites.length > 1 && state.site === "all" ? ` för ${esc(D.sites[nw.site].name)}` : ""} ${nightLabel(nw.night).replace(/ \d{4}$/, "")}</span>` : "";
      return `<button class="card${n ? "" : " dim"}${nw ? " is-new" : ""}" data-sp="${s.i}" aria-label="${esc(s.sv || s.sci)}, ${n} detektioner${nw ? ", ny art för lokalen" : ""}">
        <div class="img" ${img} role="img" aria-label="">${tag}</div>
        <div class="body"><div class="sv">${esc(s.sv || s.sci)}</div><div class="sci">${isSpecies(s) ? esc(s.sci) : "obestämd art"}</div>
        <div class="meta"><span class="cnt">${fmt(n)}</span>${med < 0.5 ? `<span class="badge">osäker bestämning</span>` : `<span>median p ${med.toFixed(2)}</span>`}</div>
        ${n ? "" : `<div class="sub" style="margin:.2rem 0 0;font-size:.75rem">${fmt(all.get(s.i))} under gränsen</div>`}</div></button>`;
    };
    $("#taxonomy").innerHTML = classes.map(cl => {
      const orders = tree[cl];
      return `<div class="class-block"><h3>${svTax(cl)} <span class="sci" style="font-weight:400;color:var(--muted)">${esc(cl)}</span></h3>` +
        Object.keys(orders).sort().map(or => `<div class="order-block">${or ? `<h4>${svTax(or)} <span class="sci" style="font-weight:400;color:var(--muted)">${esc(or)}</span></h4>` : ""}` +
          Object.keys(orders[or]).sort().map(fa => `<div class="family-block">${fa ? `<h5>${svTax(fa)} <span class="sci">${esc(fa)}</span></h5>` : ""}<div class="cards">` +
            orders[or][fa].sort((a, b) => (c.get(b.i) || 0) - (c.get(a.i) || 0)).map(card).join("") + `</div></div>`).join("") + `</div>`).join("") + `</div>`;
    }).join("");
    $("#taxonomy").querySelectorAll(".card").forEach(b => b.addEventListener("click", () => openSpecies(+b.dataset.sp)));
  }

  // ---------- artdialog ----------
  function openSpecies(i) {
    const s = D.species[i], dets = scoped().filter(d => d[0] === i), pass = dets.filter(d => d[3] >= state.minProb);
    const probs = dets.map(d => d[3]), sun = sunTimes();
    const echo = dets.filter(d => d[4] === "echolocation").length, social = dets.filter(d => d[4] === "social").length;
    const img = s.image ? `<img class="dlg-hero" src="${esc(s.image.src)}" alt="${esc(s.sv || s.sci)}"><p class="credit">Foto: ${esc(s.image.artist || "okänd")}, <a href="${esc(s.image.page)}" target="_blank" rel="noopener">${esc(s.image.license || "se Commons")}</a></p>` : "";
    const path = [s.class, s.order, s.family].filter(Boolean).map(t => `${svTax(t)} (<i>${esc(t)}</i>)`).join(" › ");
    const facts = [
      [fmt(pass.length), `detektioner ≥ ${state.minProb.toFixed(2)}`],
      [fmt(dets.length), "detektioner totalt"],
      [probs.length ? Math.max(...probs).toFixed(2) : "–", "högsta sannolikhet"],
      [probs.length ? median(probs).toFixed(2) : "–", "median sannolikhet"],
      [dets.length ? shortTime(dets[0][2]) : "–", "första"],
      [dets.length ? shortTime(dets[dets.length - 1][2]) : "–", "sista"],
    ];
    if (s.group === "bat") facts.push([`${echo} / ${social}`, "ekolod / sociala läten"]);
    if (s.gbifSE != null) facts.push([fmt(s.gbifSE), "GBIF-fynd i Sverige"], [fmt(s.gbifNear25km ?? 0), "GBIF-fynd inom 25 km"]);
    const links = [
      s.wiki && `<a href="${esc(s.wiki.url)}" target="_blank" rel="noopener">Wikipedia</a>`,
      s.gbifKey && `<a href="https://www.gbif.org/species/${s.gbifKey}" target="_blank" rel="noopener">GBIF</a>`,
      s.dyntaxaId && `<a href="https://artfakta.se/taxa/${s.dyntaxaId}" target="_blank" rel="noopener">Artfakta</a>`,
      isSpecies(s) && `<a href="${AP_IMPORT}" target="_blank" rel="noopener">Rapportera i Artportalen</a>`,
    ].filter(Boolean).join("");
    const g = groupOf(s.group);
    $("#dlgBody").innerHTML = `${img}<div class="dlg-content">
      <h2 id="dlgTitle">${esc(s.sv || s.sci)}</h2>
      <div class="sub">${isSpecies(s) ? `<i>${esc(s.sci)}</i> · ` : ""}${esc(s.en)}${s.code ? ` · BTO-kod ${esc(s.code)}` : ""}</div>
      <div class="sub">${path}</div>
      ${[...NEW].filter(([, o]) => o.first.has(i)).map(([si, o]) => { const f = o.first.get(i), isNew = f.night > o.start;
        return `<div class="sub">${isNew ? `<span class="newtag" style="position:static">Ny</span> ` : ""}Första fynd på ${esc(D.sites[si].name)}: natten ${nightLabel(f.night)}${isNew ? "" : " (lokalens första natt)"}</div>`; }).join("")}
      ${s.dyntaxaName && s.dyntaxaName !== s.sci ? `<div class="sub">I Dyntaxa: <i>${esc(s.dyntaxaName)}</i></div>` : ""}
      ${s.wiki ? `<p>${esc(s.wiki.extract)} <a href="${esc(s.wiki.url)}" target="_blank" rel="noopener">Läs mer</a></p>` : ""}
      ${median(probs) < 0.5 ? `<p><span class="badge">osäker bestämning</span> Medianen för klassificerarens sannolikhet är under 0,5 – verifiera i spektrogram innan fyndet rapporteras.</p>` : ""}
      <div class="facts">${facts.map(([v, l]) => `<div><b>${v}</b><span>${l}</span></div>`).join("")}</div>
      <div class="chart"><h4><span class="sw" style="background:${g.color}"></span>Aktivitet (≥ ${state.minProb.toFixed(2)})</h4>${barChart(pass, g.color, sun, nightRange(scoped(), sun), "detektioner")}</div>
      <h3>Sannolikhetsfördelning</h3>${heat(probs, true)}
      <h3>Detektioner (${fmt(dets.length)})</h3>
      <div class="det-list"><table><thead><tr><th>Tid</th><th class="num">p</th><th>Lätestyp</th><th>Fil</th></tr></thead><tbody>
        ${dets.slice(0, 500).map(d => `<tr${d[3] < state.minProb ? ' style="color:var(--muted)"' : ""}><td>${shortTime(d[2])}</td><td class="num">${d[3].toFixed(2)}</td><td>${d[4] === "echolocation" ? "ekolod" : d[4] === "social" ? "socialt" : esc(d[4])}</td><td>${esc(d[6])}</td></tr>`).join("")}
      </tbody></table></div>${dets.length > 500 ? `<p class="sub">Visar de första 500.</p>` : ""}
      <div class="links" style="margin-top:1rem">${links}</div></div>`;
    $("#dlg").showModal();
  }
  $("#dlg").addEventListener("click", e => { if (e.target.id === "dlg") e.target.close(); });

  // ---------- tabell ----------
  function heat(probs, big) {
    const bins = new Array(10).fill(0);
    probs.forEach(p => bins[Math.min(9, Math.floor(p * 10))]++);
    const n = probs.length || 1;
    const lvl = v => v === 0 ? 0 : v / n < .05 ? 1 : v / n < .15 ? 2 : v / n < .35 ? 3 : v / n < .6 ? 4 : 5;
    const sz = big ? ' style="width:28px;height:22px"' : "";
    return `<span class="heat" role="img" aria-label="Sannolikhetsfördelning">${bins.map((v, i) => `<span${sz ? ` style="width:28px;height:22px;background:var(--seq-${lvl(v)})"` : ` style="background:var(--seq-${lvl(v)})"`} data-tip="p ${(i / 10).toFixed(1)}–${((i + 1) / 10).toFixed(1)}: <b>${fmt(v)}</b>"></span>`).join("")}</span>` +
      (big ? `<div class="sub" style="display:flex;justify-content:space-between;width:${10 * 30}px;margin-top:.2rem"><span>0</span><span>0,5</span><span>1</span></div>` : "");
  }
  let sortKey = "n", sortDir = -1;
  function renderTable(all) {
    const byS = new Map();
    all.forEach(d => { (byS.get(d[0]) || byS.set(d[0], []).get(d[0])).push(d); });
    const rows = [...byS].map(([i, dets]) => {
      const s = D.species[i], probs = dets.map(d => d[3]);
      return { s, dets, probs, n: dets.length, np: dets.filter(d => d[3] >= state.minProb).length, med: median(probs), max: Math.max(...probs), first: dets[0][2], last: dets[dets.length - 1][2], name: s.sv || s.sci, grp: groupOf(s.group).sv };
    });
    rows.sort((a, b) => (a[sortKey] > b[sortKey] ? 1 : a[sortKey] < b[sortKey] ? -1 : 0) * sortDir);
    const cols = [["name", "Art"], ["grp", "Grupp"], ["n", "Antal", 1], ["np", `≥ ${state.minProb.toFixed(2)}`, 1], ["med", "Median p", 1], ["max", "Max p", 1], [null, "Fördelning 0–1"], ["first", "Första"], ["last", "Sista"]];
    $("#table").innerHTML = `<thead><tr>${cols.map(([k, l, num]) => `<th${num ? ' class="num"' : ""}${k ? ` data-k="${k}"` : ""}>${l}${k === sortKey ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(r => `<tr data-sp="${r.s.i}" style="cursor:pointer"><td><b>${esc(r.name)}</b>${isSpecies(r.s) ? ` <i style="color:var(--ink-2)">${esc(r.s.sci)}</i>` : ""}</td><td><span class="sw" style="background:${groupOf(r.s.group).color}"></span> ${r.grp}</td>
        <td class="num">${fmt(r.n)}</td><td class="num">${fmt(r.np)}</td><td class="num">${r.med.toFixed(2)}</td><td class="num">${r.max.toFixed(2)}</td><td>${heat(r.probs)}</td><td>${shortTime(r.first)}</td><td>${shortTime(r.last)}</td></tr>`).join("") + "</tbody>";
    $("#table").querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
      const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : (["name", "grp", "first", "last"].includes(k) ? 1 : -1); sortKey = k; renderTable(scoped());
    }));
    $("#table").querySelectorAll("tr[data-sp]").forEach(tr => tr.addEventListener("click", () => { if (D.species[+tr.dataset.sp].sci !== "Oidentifierad") openSpecies(+tr.dataset.sp); }));
  }

  // ---------- väder ----------
  const wxKeys = (ignoreNight) => Object.keys(D.weather || {}).filter(k => {
    const [n, si] = k.split("|");
    return (ignoreNight || state.night === "all" || n === state.night) && (state.site === "all" || +si === +state.site);
  }).sort();
  const f1 = v => v == null ? "–" : String(v).replace(".", ",");

  function lineChart(pts, color, sun, range, unit, bars) {
    const W = 480, H = 120, m = { l: 34, r: 8, t: 14, b: 20 };
    const [x0, x1] = range, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const vals = pts.map(p => p[1]).filter(v => v != null);
    if (!vals.length) return `<p class="sub">Ingen data.</p>`;
    let lo = bars ? 0 : Math.floor(Math.min(...vals)), hi = Math.ceil(Math.max(...vals));
    if (hi - lo < 2) { hi = lo + 2; }
    const step = niceStep(hi - lo) ; lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const X = v => m.l + (v - x0) / (x1 - x0) * iw, Y = v => m.t + ih - (v - lo) / (hi - lo) * ih;
    let g = "";
    for (let v = lo; v <= hi + 1e-9; v += step) g += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 5}" y="${Y(v) + 3}" text-anchor="end">${f1(+v.toFixed(1))}</text>`;
    for (let h = Math.ceil(x0 / 60) * 60; h <= x1; h += 120) g += `<text x="${X(h)}" y="${H - 5}" text-anchor="middle">${clock(h).slice(0, 2)}</text>`;
    if (sun) [["sunset"], ["sunrise"]].forEach(([k]) => { if (sun[k] >= x0 && sun[k] <= x1) g += `<line class="sun" x1="${X(sun[k])}" x2="${X(sun[k])}" y1="${m.t - 6}" y2="${m.t + ih}"/>`; });
    let marks = "";
    const inR = pts.filter(p => p[1] != null && p[0] >= x0 && p[0] <= x1);
    if (bars) {
      const bw = Math.max(2, iw / ((x1 - x0) / 60) - 3);
      inR.forEach(([x, v]) => { const y = Y(v), h = m.t + ih - y; marks += `<rect class="hit" x="${X(x) - bw / 2}" y="${m.t}" width="${bw}" height="${ih}" data-tip="${clock(x)}<br><b>${f1(v)}</b> ${unit}"/>`; if (v > 0) marks += `<path class="bar" fill="${color}" d="${roundTop(X(x) - bw / 2, y, bw, Math.max(1, h), Math.min(2, bw / 2))}" data-tip="${clock(x)}<br><b>${f1(v)}</b> ${unit}"/>`; });
    } else {
      marks += `<polyline fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" points="${inR.map(([x, v]) => `${X(x)},${Y(v)}`).join(" ")}"/>`;
      inR.forEach(([x, v]) => { marks += `<circle cx="${X(x)}" cy="${Y(v)}" r="3" fill="${color}" stroke="var(--surface)" stroke-width="1.5"/><circle class="hit" cx="${X(x)}" cy="${Y(v)}" r="10" data-tip="${clock(x)}<br><b>${f1(v)}</b> ${unit}"/>`; });
    }
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(unit)} per timme">${g}${marks}<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/></svg>`;
  }

  function renderWeather() {
    const keys = wxKeys(false), el = $("#weather");
    if (!D.weather || !Object.keys(D.weather).length) { el.innerHTML = `<p class="sub">Ingen väderdata – kör build.py utan --no-weather.</p>`; return; }
    if (keys.length !== 1) { el.innerHTML = `<p class="sub">Välj en natt och en lokal i filtret för att se timvärden. Sammanfattning per natt finns i jämförelsen nedan.</p>`; return; }
    const [night] = keys[0].split("|"), w = D.weather[keys[0]], s = w.summary || {};
    const sun = sunTimes(), range = nightRange(scoped(), sun);
    const pts = k => (w[k] || []).map((v, i) => [relMin(w.hours[i] + ":00", night), v]);
    const st = k => w.stations && w.stations[k] ? `${esc(w.stations[k].name)}, ${f1(w.stations[k].km)} km` : "ingen station";
    const tiles = [
      [s.tempSunset != null ? f1(s.tempSunset) + " °C" : "–", "vid solnedgång"],
      [s.tempMin != null ? f1(s.tempMin) + " °C" : "–", "lägsta under natten"],
      [s.windMean != null ? f1(s.windMean) + " m/s" : "–", `medelvind (max ${f1(s.windMax)})`],
      [s.precipSum != null ? f1(s.precipSum) + " mm" : "–", "nederbörd under natten"],
      [s.cloudMean != null ? s.cloudMean + " %" : "–", "molnighet"],
    ];
    const charts = [
      ["temp", "Temperatur", "°C", "var(--s2)", false],
      ["wind", "Vind", "m/s", "var(--s1)", false],
      ["precip", "Nederbörd", "mm", "var(--s3)", true],
    ].filter(([k]) => w[k] && !(k === "precip" && !(s.precipSum > 0))).map(([k, t, u, c, b]) => `<div class="chart"><h4><span class="sw" style="background:${c}"></span>${t} <span class="n">${u}</span></h4>${lineChart(pts(k), c, sun, range, u, b)}<p class="src">${st(k)}</p></div>`).join("");
    el.innerHTML = `<div class="tiles" style="margin-top:0">${tiles.map(([v, l]) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")}</div>
      <div class="multiples" style="margin-top:.75rem">${charts}</div>
      <p class="sub" style="margin-top:.5rem">${w.precip && !(s.precipSum > 0) ? "Ingen nederbörd under natten. " : ""}Molnighet: ${st("cloud")}.</p>`;
  }

  // ---------- jämförelse ----------
  function renderCompare() {
    const combos = [...new Set(D.detections.filter(d => state.site === "all" || d[1] === +state.site).map(d => `${d[5]}|${d[1]}`))].sort();
    const bySpBat = s => s.group === "bat";
    const rows = combos.map(k => {
      const [night, si] = k.split("|"), dets = D.detections.filter(d => d[5] === night && d[1] === +si && d[3] >= state.minProb);
      const bats = dets.filter(d => bySpBat(D.species[d[0]]));
      const batSp = new Set(bats.filter(d => D.species[d[0]].rank === "species").map(d => d[0]));
      const w = (D.weather || {})[k] || {}, s = w.summary || {};
      const ss = w.sunset ? relMin(w.sunset + ":00", night) : null;
      const first = bats.length ? relMin(bats[0][2], night) : null;
      return { k, night, si: +si, site: D.sites[+si].name, s, sunset: w.sunset ? w.sunset.slice(11) : "–",
        bats: bats.length, batSp: batSp.size, afterSs: first != null && ss != null ? first - ss : null,
        crick: dets.filter(d => D.species[d[0]].group === "bush-cricket").length, total: dets.length,
        rec: [...new Set(D.detections.filter(d => d[5] === night && d[1] === +si).map(d => d[7]))].filter(i => i >= 0 && (D.recorders || [])[i]).map(i => D.recorders[i].name).join(", ") };
    });
    const multiSite = new Set(rows.map(r => r.si)).size > 1, multiNight = new Set(rows.map(r => r.night)).size > 1;
    const multiRec = new Set(rows.map(r => r.rec)).size > 1;
    let html = `<div class="table-wrap"><table><thead><tr><th>Natt</th>${multiSite ? "<th>Lokal</th>" : ""}${multiRec ? "<th>Inspelare</th>" : ""}<th>Sol ned</th><th class="num">Temp sol ned</th><th class="num">Min temp</th><th class="num">Vind m/s</th><th class="num">Regn mm</th><th class="num">Moln %</th><th class="num">Fladdermöss</th><th class="num">Arter</th><th class="num">Första efter sol ned</th><th class="num">Vårtbitare</th></tr></thead><tbody>` +
      rows.map(r => `<tr data-night="${r.night}" style="cursor:pointer"><td>${nightLabel(r.night)}</td>${multiSite ? `<td>${esc(r.site)}</td>` : ""}${multiRec ? `<td>${esc(r.rec)}</td>` : ""}<td>${r.sunset}</td>
        <td class="num">${f1(r.s.tempSunset)}</td><td class="num">${f1(r.s.tempMin)}</td><td class="num">${f1(r.s.windMean)}</td><td class="num">${f1(r.s.precipSum)}</td><td class="num">${r.s.cloudMean ?? "–"}</td>
        <td class="num">${fmt(r.bats)}</td><td class="num">${r.batSp}</td><td class="num">${r.afterSs == null ? "–" : r.afterSs + " min"}</td><td class="num">${fmt(r.crick)}</td></tr>`).join("") + `</tbody></table></div>`;

    if (multiNight) {
      // fladdermusregistreringar per natt (en serie, ingen legend)
      const W = 640, H = 160, m = { l: 40, r: 8, t: 10, b: 34 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
      const byNight = [...new Set(rows.map(r => r.night))].map(n => [n, rows.filter(r => r.night === n).reduce((a, r) => a + r.bats, 0)]);
      const max = Math.max(1, ...byNight.map(b => b[1])), step = niceStep(max), top = Math.ceil(max / step) * step, bw = iw / byNight.length;
      let g = "";
      for (let v = 0; v <= top; v += step) g += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih - v / top * ih}" y2="${m.t + ih - v / top * ih}"/><text x="${m.l - 5}" y="${m.t + ih - v / top * ih + 3}" text-anchor="end">${fmt(v)}</text>`;
      byNight.forEach(([n, v], i) => {
        const x = m.l + i * bw, h = v / top * ih, tipT = `${nightLabel(n)}<br><b>${fmt(v)}</b> fladdermusregistreringar`;
        g += `<rect class="hit" x="${x}" y="${m.t}" width="${bw}" height="${ih}" data-tip="${tipT}"/>`;
        if (v) g += `<path class="bar" fill="var(--s1)" d="${roundTop(x + 2, m.t + ih - h, Math.max(1, bw - 4), Math.max(1, h), Math.min(4, (bw - 4) / 2))}" data-tip="${tipT}"/>`;
        if (byNight.length <= 16 || i % Math.ceil(byNight.length / 16) === 0) g += `<text x="${x + bw / 2}" y="${H - 18}" text-anchor="middle">${+n.slice(8)}/${+n.slice(5, 7)}</text>`;
      });
      html += `<div class="multiples" style="margin-top:.75rem"><div class="chart"><h4><span class="sw" style="background:var(--s1)"></span>Fladdermusregistreringar per natt</h4><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fladdermusregistreringar per natt">${g}<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/></svg></div>`;
      // temperatur vid solnedgång mot fladdermusaktivitet
      const sc = rows.filter(r => r.s.tempSunset != null);
      if (sc.length >= 4) {
        const tx = sc.map(r => r.s.tempSunset), x0 = Math.floor(Math.min(...tx)) - 1, x1 = Math.ceil(Math.max(...tx)) + 1;
        const ym = Math.max(1, ...sc.map(r => r.bats)), ys = niceStep(ym), yt = Math.ceil(ym / ys) * ys;
        const X = v => m.l + (v - x0) / (x1 - x0) * iw, Y = v => m.t + ih - v / yt * ih;
        let s2 = "";
        for (let v = 0; v <= yt; v += ys) s2 += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 5}" y="${Y(v) + 3}" text-anchor="end">${fmt(v)}</text>`;
        for (let v = Math.ceil(x0); v <= x1; v += Math.max(1, Math.round((x1 - x0) / 8))) s2 += `<text x="${X(v)}" y="${H - 18}" text-anchor="middle">${v}°</text>`;
        sc.forEach(r => { s2 += `<circle cx="${X(r.s.tempSunset)}" cy="${Y(r.bats)}" r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/><circle class="hit" cx="${X(r.s.tempSunset)}" cy="${Y(r.bats)}" r="12" data-tip="${nightLabel(r.night)}${multiSite ? " · " + esc(r.site) : ""}<br>${f1(r.s.tempSunset)} °C · <b>${fmt(r.bats)}</b> fladdermöss"/>`; });
        html += `<div class="chart"><h4><span class="sw" style="background:var(--s1)"></span>Fladdermöss mot temperatur vid solnedgång</h4><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fladdermusregistreringar mot temperatur">${s2}<line class="base" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/><text x="${W - m.r}" y="${H - 4}" text-anchor="end">temperatur vid solnedgång</text></svg></div>`;
      }
      html += `</div>`;
    }
    if (multiSite) {
      const sites = [...new Set(rows.map(r => r.si))];
      const pass = D.detections.filter(d => d[3] >= state.minProb && (state.night === "all" || d[5] === state.night));
      const sp = D.species.filter(s => isSpecies(s) && pass.some(d => d[0] === s.i));
      const cnt = (spi, si) => pass.filter(d => d[0] === spi && d[1] === si).length;
      const mx = Math.max(1, ...sp.flatMap(s => sites.map(si => cnt(s.i, si))));
      const lvl = v => v === 0 ? 0 : 1 + Math.min(4, Math.floor(Math.log(v) / Math.log(mx + 1) * 5));
      html += `<h3>Arter per lokal</h3><div class="table-wrap"><table><thead><tr><th>Art</th>${sites.map(si => `<th class="num">${esc(D.sites[si].name)}</th>`).join("")}</tr></thead><tbody>` +
        sp.map(s => `<tr><td><b>${esc(s.sv || s.sci)}</b> <i style="color:var(--ink-2)">${esc(s.sci)}</i></td>${sites.map(si => { const v = cnt(s.i, si); return `<td class="num"><span class="sw" style="background:var(--seq-${lvl(v)});width:14px;height:14px;vertical-align:-2px"></span> ${v ? fmt(v) : "–"}</td>`; }).join("")}</tr>`).join("") + `</tbody></table></div>`;
    }
    if (!multiNight && !multiSite) html += `<p class="sub" style="margin-top:.5rem">Diagram per natt, temperatur mot aktivitet och en art×lokal-tabell visas automatiskt när det finns fler nätter eller lokaler.</p>`;
    $("#compare").innerHTML = html;
    $("#compare").querySelectorAll("tr[data-night]").forEach(tr => tr.addEventListener("click", () => {
      state.night = tr.dataset.night; $("#night").value = state.night; render();
      document.getElementById("weather").scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  }

  // ---------- utrustning ----------
  function renderEquipment() {
    const recs = D.recorders || [], el = $("#equipment");
    const used = new Map();
    scoped().forEach(d => { const k = d[7] ?? -1; if (!used.has(k)) used.set(k, { nights: new Set(), sites: new Set(), n: 0 }); const u = used.get(k); u.nights.add(d[5]); u.sites.add(d[1]); u.n++; });
    const rows = [...used].filter(([k]) => k >= 0 && recs[k]);
    if (!rows.length) { el.innerHTML = `<p class="sub">Ingen inspelare angiven – lägg till i data/equipment.json.</p>`; return; }
    const F = [["type", "Typ"], ["recording", "Inspelning"], ["sample_rate", "Samplingsfrekvens"], ["frequency_range", "Frekvensomfång"], ["microphone", "Mikrofon"], ["trigger", "Trigger"], ["gps", "GPS"], ["power", "Ström"]];
    el.innerHTML = rows.map(([k, u]) => { const r = recs[k]; return `<div class="eq">
      <h3>${esc(r.name)}</h3>
      <div class="sub" style="margin:0">${fmt(u.n)} registreringar · ${u.nights.size} ${u.nights.size === 1 ? "natt" : "nätter"} · ${[...u.sites].map(i => esc(D.sites[i].name)).join(", ")}</div>
      <dl>${F.filter(([f]) => r[f]).map(([f, l]) => `<dt>${l}</dt><dd>${esc(r[f])}</dd>`).join("")}</dl>
      ${r.url ? `<p style="margin:.75rem 0 0"><a href="${esc(r.url)}" target="_blank" rel="noopener">Produktsida</a></p>` : ""}</div>`; }).join("");
  }

  function renderCredits() {
    $("#credits").innerHTML = D.species.filter(s => s.image).map(s => `<li>${esc(s.sv || s.sci)}: ${esc(s.image.artist || "okänd")}, <a href="${esc(s.image.page)}" target="_blank" rel="noopener">${esc(s.image.license || "Commons")}</a></li>`).join("");
  }
})();
