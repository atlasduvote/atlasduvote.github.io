// Carte à deux niveaux : la France par département, puis les bureaux de vote dès qu'on zoome.
// Les bureaux sont chargés département par département, seulement pour la zone affichée.
(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const nq = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[-'’]/g, " ").trim();
  const pct = v => v == null ? "–" : (100 * v).toFixed(1).replace(".", ",") + " %";
  const fmt = n => n == null ? "–" : Math.round(n).toLocaleString("fr-FR");
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const numero = id => { const n = id.split("_")[1]; return /^\d+$/.test(n) ? String(+n) : n; };
  const ord = n => n + (n === 1 ? "er" : "e");
  const ZOOM_BUREAUX = 9;  // à partir de ce zoom, on affiche les bureaux plutôt que les départements

  const IND = {
    reserve: { titre: "bureaux à mobiliser", unite: "voix", val: b => b.reserve, palette: "s",
               legende: "Voix de gauche en réserve chez les abstentionnistes", depLegende: "Voix en réserve, total du département" },
    bascule: { titre: "bureaux qui ont le plus basculé", unite: "voix", val: b => b.bascule, palette: "b",
               legende: "Voix passées au RN depuis 2017 (estimation)", depLegende: "Voix basculées, total du département" },
    inscription: { titre: "communes où inscrire", unite: "personnes", communes: true, palette: "t", pourcent: true,
               val: b => comDe(b)?.taux ?? null,
               legende: "Part des Français majeurs non inscrits dans leur commune (estimation)", depLegende: "Non-inscrits estimés, total du département" },
    serre:   { titre: "bureaux serrés, par réserve de voix", unite: "voix", val: b => b.serre ? b.reserve : null, palette: "s",
               legende: "Bureaux serrés : réserve de mobilisation", depLegende: "Nombre de bureaux serrés" },
  };

  // Profil Insee : [niveau de vie, ménages pauvres, 18-39 ans, 65 ans et plus, logements sociaux, propriétaires, habitants]
  const QUARTIERS = {
    populaire: p => p[1] >= 0.25, jeune: p => p[2] >= 0.45, hlm: p => p[4] != null && p[4] >= 0.4, seniors: p => p[3] >= 0.35,
  };
  const garde = b => { const q = $("quartier").value; return !q || (b.profil && QUARTIERS[q](b.profil)); };
  let ind = "reserve", france = null, depCouche = null, selection = null, communesIndex = null;
  const charges = {};          // dep -> { bureaux, communes, couche, parId }
  const enCours = {};          // dep -> promesse de chargement
  const comDe = b => charges[b.dep]?.communes[b.id.slice(0, 5)];

  const map = L.map("carte", { zoomSnap: 0.5, preferCanvas: true, minZoom: 4 });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
  }).addTo(map);
  const modeBureaux = () => map.getZoom() >= ZOOM_BUREAUX;

  // Couleurs : cinq classes de même effectif. Les bornes des bureaux sont calculées sur toute la France
  // (fichier france.json), pour que deux départements voisins se lisent avec la même échelle.
  const classe = (v, bornes) => v == null ? null : bornes.slice(0, 4).filter(b => v > b).length + 1;
  const teinte = k => k ? css(`--${IND[ind].palette}${k}`) : null;
  function bornesDeps() {
    const v = Object.values(france.departements).map(d => d[ind]).sort((a, b) => a - b);
    const q = [0.2, 0.4, 0.6, 0.8].map(x => v[Math.floor(x * (v.length - 1))]);
    return [...q, v[0], v[v.length - 1]];
  }
  const styleBureau = f => {
    const b = charges[f.properties.dep]?.parId[f.properties.id];
    const c = teinte(classe(b ? IND[ind].val(b) : null, france.bornes[ind]));
    const visible = c && (IND[ind].communes || garde(b));
    return { color: css("--line"), weight: 0.4, fillColor: c || css("--bg"), fillOpacity: visible ? 0.72 : c ? 0.1 : 0.15 };
  };
  const styleDep = f => {
    const c = teinte(classe(france.departements[f.properties.dep]?.[ind], bornesDeps()));
    return { color: css("--fg"), weight: 0.6, fillColor: c || css("--bg"), fillOpacity: modeBureaux() ? 0 : 0.75 };
  };

  function legende() {
    const bureaux = modeBureaux(), bornes = bureaux ? france.bornes[ind] : bornesDeps();
    const f = v => bureaux && IND[ind].pourcent ? pct(v) : fmt(v);
    $("legende").innerHTML = `<b>${esc(bureaux ? IND[ind].legende : IND[ind].depLegende)}</b>
      <div class="ech">${[1, 2, 3, 4, 5].map(k => `<i style="background:var(--${IND[ind].palette}${k})"></i>`).join("")}</div>
      <div class="bornes">${[bornes[4], bornes[1], bornes[3], bornes[5]].map(v => `<span>${f(v)}</span>`).join("")}</div>
      ${bureaux ? "" : `<p class="note">Zoomez pour voir les bureaux de vote.</p>`}`;
  }

  // Bureaux chargés et visibles à l'écran.
  function visibles() {
    const vue = map.getBounds(), out = [];
    for (const [dep, c] of Object.entries(charges)) {
      if (!c.couche) continue;
      c.couche.eachLayer(l => { if (vue.intersects(l.getBounds())) { const b = c.parId[l.feature.properties.id]; if (b) out.push(b); } });
    }
    return out;
  }

  function lignes() {
    const q = nq($("commune").value);
    const national = !modeBureaux();
    if (IND[ind].communes) {
      let list;
      if (national) list = france.top.inscription.map(c => ({ ...c, id: c.code }));
      else {
        const vus = new Map();
        for (const b of visibles()) { const c = comDe(b); if (c && c.non_inscrits != null) vus.set(b.id.slice(0, 5), { ...c, id: b.id.slice(0, 5), code: b.id.slice(0, 5), dep: b.dep, v: c.non_inscrits }); }
        list = [...vus.values()];
      }
      return list.filter(c => !q || nq(c.nom).includes(q)).sort((a, b) => b.v - a.v).slice(0, 15);
    }
    const list = national
      ? france.top[ind].map(b => ({ ...b }))
      : visibles().map(b => ({ ...b, v: IND[ind].val(b) })).filter(b => b.v != null);
    return list.filter(b => (!q || nq(b.commune).includes(q)) && garde(b)).sort((a, b) => b.v - a.v).slice(0, 15);
  }

  function liste() {
    const top = lignes(), national = !modeBureaux();
    $("titre-liste").textContent = `Les 15 ${IND[ind].titre} ${national ? "en France" : "de la zone affichée"}`;
    $("liste").innerHTML = top.length ? top.map((x, i) => IND[ind].communes
      ? `<li><button data-commune="${x.code}" data-dep="${x.dep}"><span class="rg">${i + 1}</span><span>${esc(x.nom)}<small>${pct(x.taux)} des ${fmt(x.adultes)} Français majeurs</small></span><span class="val">${fmt(x.v)}</span></button></li>`
      : `<li><button data-id="${x.id}" data-dep="${x.dep}"><span class="rg">${i + 1}</span><span>${esc(x.commune || "?")} · bureau ${numero(x.id)}<small>${fmt(x.inscrits)} inscrits · abstention ${pct(x.abst22)}${national ? ` · ${esc(france.departements[x.dep]?.nom || x.dep)}` : ""}</small></span><span class="val">${fmt(x.v)}</span></button></li>`).join("")
      : `<li class="note">Rien à afficher ici. Déplacez la carte ou changez le filtre.</li>`;
  }

  function detail(b) {
    const ligne = (nom, k) => `<tr><td>${nom}</td><td>${pct(b.gauche[k])}</td><td>${pct(b.rn[k])}</td></tr>`;
    const c = comDe(b);
    $("detail").hidden = false;
    $("detail").innerHTML = `<h3>${esc(b.commune || "?")} · bureau ${numero(b.id)}</h3>
      <span class="note">${esc(france.departements[b.dep]?.nom || "")} · ${fmt(b.inscrits)} inscrits · abstention 2022 : ${pct(b.abst22)}${b.serre ? " · bureau serré" : ""}</span>
      <div class="chiffres">
        <div><b>${fmt(b.reserve)}</b><span>${b.reserve == null ? "bureau atypique, hors classement" : `voix en réserve · ${ord(b.rang_reserve)} du département`}</span></div>
        <div><b>${fmt(b.bascule)}</b><span>${b.bascule == null ? "pas de comparaison possible avec 2017" : `voix basculées · ${ord(b.rang_bascule)} du département`}</span></div>
      </div>
      ${c?.non_inscrits ? `<p class="note">Dans la commune : environ ${fmt(c.non_inscrits)} Français majeurs non inscrits sur ses listes (${pct(c.taux)}).</p>` : ""}
      ${profil(b.profil)}
      <table><thead><tr><th>Élection</th><th>Gauche</th><th>RN</th></tr></thead><tbody>
        ${ligne("Présidentielle 2017", "2017")}${ligne("Présidentielle 2022", "2022")}${ligne("Européennes 2024", "euro24")}${ligne("Législatives 2024", "legis24")}
      </tbody></table>`;
  }

  function profil(p) {
    if (!p) return `<p class="note">Profil Insee non disponible pour ce bureau.</p>`;
    const f = france.profil || [];
    const l = (nom, v, m, fn) => `<tr><td>${nom}</td><td>${fn(v)}</td><td>${fn(m)}</td></tr>`;
    const euros = v => v == null ? "–" : fmt(v) + " €";
    return `<table><thead><tr><th>Profil du quartier (Insee 2021)</th><th>Bureau</th><th>France</th></tr></thead><tbody>
      ${l("Niveau de vie moyen par an", p[0], f[0], euros)}${l("Ménages pauvres", p[1], f[1], pct)}
      ${l("18-39 ans parmi les majeurs", p[2], f[2], pct)}${l("65 ans et plus parmi les majeurs", p[3], f[3], pct)}
      ${l("Logements sociaux", p[4], f[4], pct)}${l("Ménages propriétaires", p[5], f[5], pct)}</tbody></table>`;
  }

  function charge(dep) {
    if (charges[dep]) return Promise.resolve(charges[dep]);
    if (enCours[dep]) return enCours[dep];
    return enCours[dep] = Promise.all([fetch(`data/${dep}.json`).then(r => r.json()), fetch(`data/${dep}-contours.json`).then(r => r.json())])
      .then(([d, geo]) => {
        const c = { bureaux: d.bureaux.map(b => ({ ...b, dep })), communes: d.communes || {} };
        c.parId = Object.fromEntries(c.bureaux.map(b => [b.id, b]));
        geo.features.forEach(f => { f.properties.dep = dep; });
        charges[dep] = c;  // avant de créer la couche : le style de chaque bureau lit ses données ici
        c.couche = L.geoJSON(geo, {
          style: styleBureau,
          onEachFeature: (f, l) => {
            const b = c.parId[f.properties.id];
            l.bindTooltip(b ? `${esc(b.commune)} · bureau ${numero(b.id)}` : "Bureau sans résultats", { sticky: true });
            l.on("click", () => choisit(f.properties.id, dep, false));
          },
        });
        if (modeBureaux()) c.couche.addTo(map);
        delete enCours[dep];
        return c;
      });
  }

  async function choisit(id, dep, zoom) {
    const c = await charge(dep), b = c.parId[id]; if (!b) return;
    if (selection) selection.couche.resetStyle(selection.l);
    let l = null; c.couche.eachLayer(x => { if (x.feature.properties.id === id) l = x; });
    if (zoom && l) map.fitBounds(l.getBounds(), { maxZoom: 16, padding: [40, 40] });
    if (l) { selection = { l, couche: c.couche }; l.setStyle({ weight: 3, color: css("--serre") }); l.bringToFront(); }
    detail(b);
  }

  // À chaque déplacement : en vue rapprochée, charger les départements visibles et afficher leurs bureaux.
  function miseAJour() {
    const bureaux = modeBureaux(), vue = map.getBounds();
    depCouche.setStyle(styleDep);
    for (const [dep, d] of Object.entries(france.departements)) {
      const dedans = vue.intersects(L.latLngBounds([d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]));
      if (bureaux && dedans) charge(dep).then(() => { if (modeBureaux()) { charges[dep].couche.addTo(map); liste(); } });
      else if (charges[dep]?.couche && map.hasLayer(charges[dep].couche) && (!bureaux || !dedans)) map.removeLayer(charges[dep].couche);
    }
    legende();
    liste();
  }

  function redessine() {
    for (const c of Object.values(charges)) c.couche.setStyle(styleBureau);
    if (selection) selection.l.setStyle({ weight: 3, color: css("--serre") });
    depCouche.setStyle(styleDep);
    legende();
    liste();
  }

  $("quartier").addEventListener("change", redessine);
  $("indicateurs").addEventListener("click", e => {
    const b = e.target.closest("button[data-ind]"); if (!b) return;
    ind = b.dataset.ind;
    document.querySelectorAll("#indicateurs button").forEach(x => x.setAttribute("aria-checked", x === b));
    redessine();
  });

  // Filtre par commune : filtre la liste, et si le nom correspond à une commune, la carte s'y rend.
  let tempo;
  $("commune").addEventListener("input", () => {
    liste();
    clearTimeout(tempo);
    tempo = setTimeout(async () => {
      const q = nq($("commune").value); if (q.length < 3) return;
      communesIndex = communesIndex || await fetch("data/communes.json").then(r => r.json());
      const trouve = communesIndex.find(([nom]) => nq(nom) === q) || communesIndex.find(([nom]) => nq(nom).startsWith(q));
      if (!trouve) return;
      const [nom, dep] = trouve, c = await charge(dep);
      const zone = L.featureGroup();
      c.couche.eachLayer(l => { if (c.parId[l.feature.properties.id]?.commune === nom) zone.addLayer(l); });
      if (zone.getLayers().length) map.fitBounds(zone.getBounds(), { padding: [30, 30], maxZoom: 14 });
    }, 500);
  });

  $("liste").addEventListener("click", async e => {
    const b = e.target.closest("button[data-id]"); if (b) return choisit(b.dataset.id, b.dataset.dep, true);
    const cb = e.target.closest("button[data-commune]"); if (!cb) return;
    const c = await charge(cb.dataset.dep), zone = L.featureGroup();
    c.couche.eachLayer(l => { if (l.feature.properties.id.startsWith(cb.dataset.commune + "_")) zone.addLayer(l); });
    if (zone.getLayers().length) map.fitBounds(zone.getBounds(), { padding: [30, 30] });
  });

  $("dep").addEventListener("change", e => {
    const d = france.departements[e.target.value];
    if (!d) return map.fitBounds([[41.3, -5.2], [51.1, 9.6]]);
    map.fitBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]]);
  });

  // Liste prête à coller dans un groupe WhatsApp de bénévoles.
  $("copier").addEventListener("click", () => {
    const top = lignes();
    const texte = `${$("titre-liste").textContent} :\n` + top.map((x, i) => IND[ind].communes
      ? `${i + 1}. ${x.nom} – environ ${fmt(x.v)} non-inscrits (${pct(x.taux)})`
      : `${i + 1}. ${x.commune} – bureau ${numero(x.id)} (${fmt(x.v)} ${IND[ind].unite})`).join("\n");
    navigator.clipboard?.writeText(texte).then(() => { $("copie-note").textContent = "Liste copiée."; })
      .catch(() => { $("copie-note").textContent = texte; });
  });

  Promise.all([fetch("data/france.json").then(r => r.json()), fetch("data/departements.json").then(r => r.json())]).then(([f, geo]) => {
    france = f;
    const codes = Object.keys(france.departements);
    $("dep").innerHTML = `<option value="">France entière</option>` +
      codes.map(c => `<option value="${c}">${c} · ${esc(france.departements[c].nom)}</option>`).join("");
    depCouche = L.geoJSON(geo, {
      style: styleDep,
      onEachFeature: (feat, l) => {
        const d = france.departements[feat.properties.dep];
        l.bindTooltip(`${esc(d.nom)} : ${fmt(d[ind])}`, { sticky: true });
        l.on("mouseover", () => l.setTooltipContent(`${esc(d.nom)} : ${fmt(d[ind])} ${ind === "serre" ? "bureaux serrés" : IND[ind].unite}`));
        l.on("click", () => { if (!modeBureaux()) map.fitBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]]); });
      },
    }).addTo(map);
    map.fitBounds([[41.3, -5.2], [51.1, 9.6]]);
    map.on("moveend", miseAJour);
    miseAJour();
  });
})();
