(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const nq = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const pct = v => v == null ? "–" : (100 * v).toFixed(1).replace(".", ",") + " %";
  const fmt = n => n == null ? "–" : n.toLocaleString("fr-FR");
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const numero = id => String(+id.split("_")[1]);
  const ord = n => n + (n === 1 ? "er" : "e");

  const IND = {
    reserve: { titre: "Les 15 bureaux à mobiliser", unite: "voix", val: b => b.reserve, palette: "s",
               legende: "Voix de gauche en réserve chez les abstentionnistes" },
    bascule: { titre: "Les 15 bureaux qui ont le plus basculé", unite: "voix", val: b => b.bascule, palette: "b",
               legende: "Voix passées au RN depuis 2017 (estimation)" },
    serre:   { titre: "Bureaux serrés, par réserve de voix", unite: "voix", val: b => b.serre ? b.reserve : null, palette: "s",
               legende: "Bureaux serrés : réserve de mobilisation" },
  };
  let communes = {};
  const com = b => communes[b.id.slice(0, 5)];
  IND.inscription = { titre: "Les 15 communes où inscrire", unite: "personnes", communes: true,
    val: b => com(b)?.taux ?? null, palette: "t", pourcent: true,
    legende: "Part des Français majeurs non inscrits dans leur commune (estimation)" };
  let ind = "reserve", bureaux = [], parId = {}, couche = null, breaks = [], selection = null, deps = [];

  const map = L.map("carte", { zoomSnap: 0.5, preferCanvas: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
  }).addTo(map);

  // Cinq classes de même effectif (quantiles) : chaque couleur couvre un cinquième des bureaux.
  function calculeBornes() {
    const v = bureaux.map(IND[ind].val).filter(x => x != null).sort((a, b) => a - b);
    breaks = [0.2, 0.4, 0.6, 0.8].map(q => v[Math.floor(q * (v.length - 1))]);
    breaks.min = v[0]; breaks.max = v[v.length - 1];
  }
  const couleur = v => {
    if (v == null) return null;
    const k = breaks.filter(b => v > b).length + 1;
    return css(`--${IND[ind].palette}${k}`);
  };
  const style = f => {
    const b = parId[f.properties.id], v = b ? IND[ind].val(b) : null, c = couleur(v);
    return { color: css("--line"), weight: 0.4, fillColor: c || css("--bg"), fillOpacity: c ? 0.72 : 0.15 };
  };

  function legende() {
    const p = IND[ind].palette;
    $("legende").innerHTML = `<b>${esc(IND[ind].legende)}</b>
      <div class="ech">${[1, 2, 3, 4, 5].map(k => `<i style="background:var(--${p}${k})"></i>`).join("")}</div>
      <div class="bornes">${[breaks.min, breaks[1], breaks[3], breaks.max].map(v => `<span>${IND[ind].pourcent ? pct(v) : fmt(v)}</span>`).join("")}</div>`;
  }

  function filtres() {
    const q = nq($("commune").value.trim());
    return bureaux.filter(b => IND[ind].val(b) != null && (!q || nq(b.commune).includes(q)))
      .sort((a, b) => IND[ind].val(b) - IND[ind].val(a)).slice(0, 15);
  }

  function topCommunes() {
    const q = nq($("commune").value.trim());
    return Object.entries(communes).filter(([, c]) => c.non_inscrits != null && (!q || nq(c.nom).includes(q)))
      .sort((a, b) => b[1].non_inscrits - a[1].non_inscrits).slice(0, 15);
  }

  function liste() {
    if (IND[ind].communes) {
      const top = topCommunes();
      $("titre-liste").textContent = IND[ind].titre;
      $("liste").innerHTML = top.length ? top.map(([code, c], i) => `<li><button data-commune="${code}">
        <span class="rg">${i + 1}</span><span>${esc(c.nom)}<small>${pct(c.taux)} des ${fmt(c.adultes)} Français majeurs</small></span>
        <span class="val">${fmt(c.non_inscrits)}</span></button></li>`).join("")
        : `<li class="note">Aucune commune ne correspond (estimation faite pour les communes de plus de 2 000 Français majeurs).</li>`;
      return;
    }
    const top = filtres();
    $("titre-liste").textContent = IND[ind].titre;
    $("liste").innerHTML = top.length ? top.map((b, i) => `<li><button data-id="${b.id}">
      <span class="rg">${i + 1}</span><span>${esc(b.commune || "?")} · bureau ${numero(b.id)}<small>${fmt(b.inscrits)} inscrits · abstention ${pct(b.abst22)}</small></span>
      <span class="val">${fmt(IND[ind].val(b))}</span></button></li>`).join("")
      : `<li class="note">Aucun bureau ne correspond.</li>`;
  }

  function detail(b) {
    const ligne = (nom, k) => `<tr><td>${nom}</td><td>${pct(b.gauche[k])}</td><td>${pct(b.rn[k])}</td></tr>`;
    $("detail").hidden = false;
    $("detail").innerHTML = `<h3>${esc(b.commune || "?")} · bureau ${numero(b.id)}</h3>
      <span class="note">${fmt(b.inscrits)} inscrits · abstention 2022 : ${pct(b.abst22)}${b.serre ? " · bureau serré" : ""}</span>
      <div class="chiffres">
        <div><b>${fmt(b.reserve)}</b><span>voix en réserve · ${ord(b.rang_reserve)} du département</span></div>
        <div><b>${fmt(b.bascule)}</b><span>${b.bascule == null ? "périmètre modifié depuis 2017" : `voix basculées · ${ord(b.rang_bascule)} du département`}</span></div>
      </div>
      ${com(b)?.non_inscrits != null ? `<p class="note">Dans la commune : environ ${fmt(com(b).non_inscrits)} Français majeurs non inscrits sur ses listes (${pct(com(b).taux)}).</p>` : ""}
      <table><thead><tr><th>Élection</th><th>Gauche</th><th>RN</th></tr></thead><tbody>
        ${ligne("Présidentielle 2017", "2017")}${ligne("Présidentielle 2022", "2022")}${ligne("Européennes 2024", "euro24")}${ligne("Législatives 2024", "legis24")}
      </tbody></table>`;
  }

  function choisit(id, zoom) {
    const b = parId[id]; if (!b) return;
    if (selection) couche.resetStyle(selection);
    couche.eachLayer(l => { if (l.feature.properties.id === id) selection = l; });
    if (selection) {
      selection.setStyle({ weight: 3, color: css("--serre") });
      selection.bringToFront();
      if (zoom) map.fitBounds(selection.getBounds(), { maxZoom: 16, padding: [40, 40] });
    }
    detail(b);
  }

  function redessine() {
    calculeBornes();
    if (couche) couche.setStyle(style);
    if (selection) selection.setStyle({ weight: 3, color: css("--serre") });
    legende();
    liste();
  }

  async function charge(dep) {
    const [d, geo] = await Promise.all([fetch(`data/${dep}.json`).then(r => r.json()), fetch(`data/${dep}-contours.json`).then(r => r.json())]);
    bureaux = d.bureaux; communes = d.communes || {}; parId = Object.fromEntries(bureaux.map(b => [b.id, b])); selection = null;
    $("detail").hidden = true;
    if (couche) map.removeLayer(couche);
    calculeBornes();
    couche = L.geoJSON(geo, {
      style,
      onEachFeature: (f, l) => {
        const b = parId[f.properties.id];
        l.bindTooltip(b ? `${esc(b.commune)} · bureau ${numero(b.id)}` : "Bureau sans résultats", { sticky: true });
        l.on("click", () => choisit(f.properties.id, false));
      },
    }).addTo(map);
    map.fitBounds(couche.getBounds());
    legende();
    liste();
  }

  $("indicateurs").addEventListener("click", e => {
    const b = e.target.closest("button[data-ind]"); if (!b) return;
    ind = b.dataset.ind;
    document.querySelectorAll("#indicateurs button").forEach(x => x.setAttribute("aria-checked", x === b));
    redessine();
  });
  $("commune").addEventListener("input", liste);
  $("liste").addEventListener("click", e => {
    const b = e.target.closest("button[data-id]"); if (b) return choisit(b.dataset.id, true);
    const c = e.target.closest("button[data-commune]"); if (!c) return;
    const zone = L.featureGroup(); couche.eachLayer(l => { if (l.feature.properties.id.startsWith(c.dataset.commune + "_")) zone.addLayer(l); });
    if (zone.getLayers().length) map.fitBounds(zone.getBounds(), { padding: [30, 30] });
  });
  $("dep").addEventListener("change", e => charge(e.target.value));

  // Liste prête à coller dans un groupe WhatsApp de bénévoles.
  $("copier").addEventListener("click", () => {
    if (IND[ind].communes) {
      const texte = `${IND[ind].titre} :\n` + topCommunes().map(([, c], i) => `${i + 1}. ${c.nom} – environ ${fmt(c.non_inscrits)} non-inscrits (${pct(c.taux)})`).join("\n");
      return navigator.clipboard?.writeText(texte).then(() => { $("copie-note").textContent = "Liste copiée."; }).catch(() => { $("copie-note").textContent = texte; });
    }
    const top = filtres();
    const texte = `${IND[ind].titre} :\n` + top.map((b, i) => `${i + 1}. ${b.commune} – bureau ${numero(b.id)} (${fmt(IND[ind].val(b))} ${IND[ind].unite})`).join("\n");
    const ok = () => { $("copie-note").textContent = "Liste copiée."; };
    navigator.clipboard?.writeText(texte).then(ok).catch(() => { $("copie-note").textContent = texte; });
  });

  fetch("data/index.json").then(r => r.json()).then(list => {
    deps = list;
    $("dep").innerHTML = deps.map(d => `<option value="${d.code}">${d.code} · ${esc(d.nom)}</option>`).join("");
    charge(deps[0].code);
  });
})();
