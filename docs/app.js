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

  let D, map, siteLayer;
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
    renderLede(pass); renderTiles(pass); renderMap(pass); renderActivity(pass); renderTaxonomy(pass); renderTable(all);
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
      const html = `<b>${esc(s.name)}</b><br>${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}${s.note ? `<br>${esc(s.note)}` : ""}
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
    const c = counts(pass), all = counts(scoped());
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
      return `<button class="card${n ? "" : " dim"}" data-sp="${s.i}" aria-label="${esc(s.sv || s.sci)}, ${n} detektioner">
        <div class="img" ${img} role="img" aria-label=""></div>
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
    ].filter(Boolean).join("");
    const g = groupOf(s.group);
    $("#dlgBody").innerHTML = `${img}<div class="dlg-content">
      <h2 id="dlgTitle">${esc(s.sv || s.sci)}</h2>
      <div class="sub">${isSpecies(s) ? `<i>${esc(s.sci)}</i> · ` : ""}${esc(s.en)}${s.code ? ` · BTO-kod ${esc(s.code)}` : ""}</div>
      <div class="sub">${path}</div>
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

  function renderCredits() {
    $("#credits").innerHTML = D.species.filter(s => s.image).map(s => `<li>${esc(s.sv || s.sci)}: ${esc(s.image.artist || "okänd")}, <a href="${esc(s.image.page)}" target="_blank" rel="noopener">${esc(s.image.license || "Commons")}</a></li>`).join("");
  }
})();
