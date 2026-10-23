"""Calcule, pour chaque bureau de vote, où la gauche a le plus de voix à gagner.

    python build.py            # tous les départements qui ont des contours de bureaux
    python build.py 59 62      # départements choisis

Entrées (cache/, téléchargées depuis data.gouv.fr) :
    pr17_t1.txt      présidentielle 2017, 1er tour, par bureau
    pr22_t1.txt      présidentielle 2022, 1er tour, par bureau
    eu24.csv         européennes 2024, par bureau
    lg24_t1.csv      législatives 2024, 1er tour, par bureau
    contours.parquet contours des bureaux de vote (Etalab / Insee, répertoire électoral unique)
Sortie : site/data/<dep>.json (indicateurs) et site/data/<dep>-contours.json (GeoJSON simplifié).
"""
import csv
import json
import shutil
import statistics
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
OUT = ROOT / "site" / "data"
SOURCES = {
    "pr17_t1.txt": "https://static.data.gouv.fr/resources/election-presidentielle-des-23-avril-et-7-mai-2017-resultats-definitifs-du-1er-tour-par-bureaux-de-vote/20170427-100955/PR17_BVot_T1_FE.txt",
    "pr22_t1.txt": "https://static.data.gouv.fr/resources/election-presidentielle-des-10-et-24-avril-2022-resultats-definitifs-du-1er-tour/20220414-152542/resultats-par-niveau-burvot-t1-france-entiere.txt",
    "eu24.csv": "https://static.data.gouv.fr/resources/resultats-des-elections-europeennes-du-9-juin-2024/20240613-154804/resultats-definitifs-par-bureau-de-vote.csv",
    "lg24_t1.csv": "https://static.data.gouv.fr/resources/elections-legislatives-des-30-juin-et-7-juillet-2024-resultats-definitifs-du-1er-tour/20240710-171445/resultats-definitifs-par-bureau-de-vote.csv",
    "contours.parquet": "https://data-pipeline-open.s3.sbg.io.cloud.ovh.net/reu/contours-france-entiere-latest-v2.parquet",
    "nat1.zip": "https://www.insee.fr/fr/statistiques/fichier/8202752/TD_NAT1_2021_csv.zip",
}
# Non-inscrits : l'Insee regroupe les 15-24 ans ; on en compte 7 sur 10 comme majeurs (18-24 ans).
PART_MAJEURS_15_24 = 0.7
COMMUNE_MIN = 2000  # sous ce nombre de Français majeurs, l'estimation des non-inscrits est trop fragile
# Outre-mer : codes « Z » des fichiers de la présidentielle → codes Insee des départements.
OUTRE_MER = {"ZA": "971", "ZB": "972", "ZC": "973", "ZD": "974", "ZS": "975", "ZM": "976"}

# Périmètre de la gauche : LFI, PS, écologistes, PCF.
GAUCHE = {
    "pr17": {"MÉLENCHON", "HAMON"},
    "pr22": {"MÉLENCHON", "HIDALGO", "JADOT", "ROUSSEL"},
    "eu24": {"LFI", "LUG", "LVEC", "LCOM"},     # LFI, Réveiller l'Europe (PS-PP), Europe Écologie, Gauche unie (PCF)
    "lg24": {"UG"},                            # Union de la gauche (Nouveau Front populaire)
}
RN = {"pr17": {"LE PEN"}, "pr22": {"LE PEN"}, "eu24": {"LRN"}, "lg24": {"RN", "UXD"}}
SERRE = 0.10          # écart gauche / RN sous lequel un bureau est « serré » (législatives 2024)
NOMS = {}  # code département -> nom, rempli à la lecture des résultats
ECART_INSCRITS = 0.25
INSCRITS_MAX = 4000   # au-delà, ce n'est pas un bureau de quartier (bureau spécial, comme « JUS1 » à Paris) : exclu des classements # au-delà, le bureau a probablement changé de périmètre entre 2017 et 2022


def num(x):
    return int(x or 0)


def dep_of(bv):
    """Département d'un bureau, d'après le code Insee de sa commune (59350_0626 → 59, 97411_0001 → 974)."""
    return bv[:3] if bv.startswith("97") else bv[:2]


def telecharge():
    CACHE.mkdir(exist_ok=True)
    for nom, url in SOURCES.items():
        if not (CACHE / nom).exists():
            print(f"Téléchargement {url}")
            urllib.request.urlretrieve(url, CACHE / nom)


def lire_presidentielle(fichier, election, deps):
    """Fichiers 2017 et 2022 : 21 colonnes fixes, puis 7 colonnes par candidat."""
    res = {}
    with open(CACHE / fichier, encoding="latin-1") as f:
        r = csv.reader(f, delimiter=";")
        next(r)
        for row in r:
            code = row[0].zfill(2)
            commune = row[4].zfill(3)
            if code in OUTRE_MER:
                if code == "ZM" and fichier.startswith("pr17"):
                    commune = "6" + commune[1:]  # Mayotte : communes numérotées 5xx en 2017, 6xx ensuite
                insee = "97" + commune
            elif code.startswith("Z"):
                continue  # territoires sans contours de bureaux, Français de l'étranger
            else:
                insee = code + commune
            bv = f"{insee}_{row[6].zfill(4)}"
            dep = dep_of(bv)
            if deps and dep not in deps:
                continue
            NOMS[dep] = row[1]
            exp = num(row[18])
            voix = {row[i + 2]: num(row[i + 4]) for i in range(21, len(row) - 6, 7)}
            res[bv] = {"nom": row[5], "inscrits": num(row[7]), "abst": num(row[8]), "exp": exp,
                       "gauche": sum(v for k, v in voix.items() if k in GAUCHE[election]),
                       "rn": sum(v for k, v in voix.items() if k in RN[election])}
    return res


def lire_europeennes(deps):
    res = {}
    with open(CACHE / "eu24.csv", encoding="utf-8") as f:
        r = csv.reader(f, delimiter=";")
        next(r)
        for row in r:
            bv = f"{row[4].zfill(5)}_{row[6].zfill(4)}"
            if deps and dep_of(bv) not in deps:
                continue
            listes = {}
            for i in range(21, len(row) - 4, 8):
                if row[i + 1]:
                    listes[row[i + 1]] = listes.get(row[i + 1], 0) + num(row[i + 4])
            res[bv] = {"inscrits": num(row[7]), "abst": num(row[10]), "exp": num(row[12]),
                       "gauche": sum(v for k, v in listes.items() if k in GAUCHE["eu24"]),
                       "rn": sum(v for k, v in listes.items() if k in RN["eu24"])}
    return res


def lire_legislatives(deps):
    res = {}
    with open(CACHE / "lg24_t1.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            bv = f"{row['Code commune'].zfill(5)}_{row['Code BV'].zfill(4)}"
            if deps and dep_of(bv) not in deps:
                continue
            g = rn = 0
            for i in range(1, 30):
                nu = row.get(f"Nuance candidat {i}")
                if not nu:
                    break
                v = num(row[f"Voix {i}"])
                g += v if nu in GAUCHE["lg24"] else 0
                rn += v if nu in RN["lg24"] else 0
            res[bv] = {"inscrits": num(row["Inscrits"]), "abst": num(row["Abstentions"]),
                       "exp": num(row["Exprimés"]), "gauche": g, "rn": rn}
    return res


def lire_insee():
    """Français majeurs par commune (recensement 2021, tableau NAT1)."""
    import io
    import zipfile
    adultes = {}
    with zipfile.ZipFile(CACHE / "nat1.zip") as z:
        nom = next(n for n in z.namelist() if n.endswith(".csv"))
        for row in csv.DictReader(io.TextIOWrapper(z.open(nom), encoding="utf-8"), delimiter=";"):
            if row["NIVGEO"] != "COM" or row["INATC"] != "1" or row["AGE4"] == "00":
                continue
            poids = PART_MAJEURS_15_24 if row["AGE4"] == "15" else 1
            adultes[row["CODGEO"]] = adultes.get(row["CODGEO"], 0) + poids * float(row["NB"] or 0)
    return adultes


def part(d, cle):
    return d[cle] / d["exp"] if d and d["exp"] else None


def contours(deps):
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import mapping
    t = pq.read_table(CACHE / "contours.parquet", columns=["codeBureauVote", "nomCommune", "geom"])
    out = {}
    for code, nom, geom in zip(t["codeBureauVote"].to_pylist(), t["nomCommune"].to_pylist(), t["geom"].to_pylist()):
        if deps and dep_of(code) not in deps:
            continue
        g = wkb.loads(geom).simplify(0.00008, preserve_topology=True)
        gj = mapping(g)
        arrondi = lambda c: [[round(x, 5), round(y, 5)] for x, y in c]
        if gj["type"] == "Polygon":
            gj = {"type": "MultiPolygon", "coordinates": [[arrondi(r) for r in gj["coordinates"]]]}
        else:
            gj = {"type": "MultiPolygon", "coordinates": [[arrondi(r) for r in p] for p in gj["coordinates"]]}
        out[code] = (nom, gj, g)
    return out


def main():
    deps = [d.zfill(2) for d in sys.argv[1:]]  # vide : tous
    telecharge()
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "static", OUT.parent, dirs_exist_ok=True)
    pr17 = lire_presidentielle("pr17_t1.txt", "pr17", deps)
    pr22 = lire_presidentielle("pr22_t1.txt", "pr22", deps)
    eu24 = lire_europeennes(deps)
    lg24 = lire_legislatives(deps)
    geo = contours(deps)
    adultes = lire_insee()
    inscrits_commune = {}
    for bv, b in pr22.items():
        inscrits_commune[bv[:5]] = inscrits_commune.get(bv[:5], 0) + b["inscrits"]
    print(f"bureaux : 2017 {len(pr17)}, 2022 {len(pr22)}, euro 2024 {len(eu24)}, légis 2024 {len(lg24)}, contours {len(geo)}")

    from shapely.geometry import mapping
    france, tous, toutes_communes, formes = {}, [], {}, []
    for dep in sorted({dep_of(c) for c in geo}):
        bureaux = []
        for bv, b22 in pr22.items():
            if dep_of(bv) != dep:
                continue
            b17, be, bl = pr17.get(bv), eu24.get(bv), lg24.get(bv)
            g = {k: part(d, "gauche") for k, d in (("2017", b17), ("2022", b22), ("euro24", be), ("legis24", bl))}
            rn = {k: part(d, "rn") for k, d in (("2017", b17), ("2022", b22), ("euro24", be), ("legis24", bl))}
            # Le bureau a-t-il gardé le même périmètre depuis 2017 ? Sinon la comparaison n'a pas de sens.
            comparable = (bool(b17) and rn["2017"] is not None
                          and abs(b17["inscrits"] - b22["inscrits"]) <= ECART_INSCRITS * b22["inscrits"])
            atypique = b22["inscrits"] > INSCRITS_MAX
            if atypique:
                comparable = False
            reserve = None if atypique else round(b22["abst"] * (g["2022"] or 0))
            rn_recent = rn["legis24"] if rn["legis24"] is not None else rn["2022"]
            bascule = round(b22["exp"] * max(0, rn_recent - rn["2017"]) * g["2017"]) if comparable and rn_recent is not None else None
            serre = (bl is not None and g["legis24"] is not None and abs(g["legis24"] - rn["legis24"]) < SERRE)
            parts_g = [v for v in g.values() if v is not None]
            nom = (geo[bv][0] if bv in geo else None) or b22["nom"]
            bureaux.append({
                "id": bv, "commune": nom, "inscrits": b22["inscrits"],
                "abst22": round(b22["abst"] / b22["inscrits"], 3) if b22["inscrits"] else None,
                "gauche": {k: round(v, 3) if v is not None else None for k, v in g.items()},
                "rn": {k: round(v, 3) if v is not None else None for k, v in rn.items()},
                "reserve": reserve, "bascule": bascule, "serre": serre, "comparable": comparable,
                "volatilite": round(statistics.pstdev(parts_g), 3) if len(parts_g) > 1 else None,
                "contour": bv in geo,
            })
        for i, b in enumerate(sorted([b for b in bureaux if b["reserve"] is not None], key=lambda b: -b["reserve"]), 1):
            b["rang_reserve"] = i
        for i, b in enumerate(sorted([b for b in bureaux if b["bascule"] is not None], key=lambda b: -b["bascule"]), 1):
            b["rang_bascule"] = i
        # Non-inscrits estimés, par commune : Français majeurs (Insee 2021) moins inscrits (2022).
        communes = {}
        for b in bureaux:
            c = b["id"][:5]
            if c in communes or c not in adultes:
                continue
            a, i = round(adultes[c]), inscrits_commune.get(c, 0)
            communes[c] = {"nom": b["commune"], "adultes": a, "inscrits": i,
                           "non_inscrits": max(0, a - i) if a >= COMMUNE_MIN else None,
                           "taux": round(max(0, a - i) / a, 3) if a >= COMMUNE_MIN else None}
        (OUT / f"{dep}.json").write_text(json.dumps({"dep": dep, "bureaux": bureaux, "communes": communes}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        feats = [{"type": "Feature", "properties": {"id": code}, "geometry": gj}
                 for code, (nom, gj, _) in geo.items() if dep_of(code) == dep]
        (OUT / f"{dep}-contours.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
        # Vue France : contour du département, totaux, et bureaux / communes pour les classements nationaux.
        forme = contour_departement([g for code, (_, _, g) in geo.items() if dep_of(code) == dep])
        formes.append({"type": "Feature", "properties": {"dep": dep}, "geometry": mapping(forme)})
        xmin, ymin, xmax, ymax = forme.bounds
        france[dep] = {"nom": NOMS.get(dep, dep), "bbox": [round(ymin, 3), round(xmin, 3), round(ymax, 3), round(xmax, 3)],
                       "bureaux": len(bureaux), "reserve": sum(b["reserve"] or 0 for b in bureaux),
                       "bascule": sum(b["bascule"] or 0 for b in bureaux), "serre": sum(1 for b in bureaux if b["serre"]),
                       "inscription": sum(c["non_inscrits"] or 0 for c in communes.values())}
        tous += [dict(b, dep=dep) for b in bureaux]
        for code, c in communes.items():
            toutes_communes[code] = dict(c, dep=dep)
        sans = sum(1 for b in bureaux if not b["contour"])
        print(f"{dep} : {len(bureaux)} bureaux, {sum(1 for b in bureaux if b['comparable'])} comparables depuis 2017, "
              f"{sum(1 for b in bureaux if b['serre'])} serrés, {sans} sans contour, "
              f"réserve {sum(b['reserve'] or 0 for b in bureaux):,} voix")
    if not deps:
        ecrit_france(france, tous, toutes_communes, formes)


def contour_departement(geoms):
    """Réunit les bureaux d'un département en un contour léger : on comble les interstices entre bureaux,
    on supprime les trous et les îlots minuscules, puis on simplifie."""
    from shapely import unary_union
    from shapely.geometry import MultiPolygon, Polygon
    u = unary_union([g.buffer(0.002) for g in geoms]).buffer(-0.002)
    polys = [Polygon(p.exterior) for p in (u.geoms if hasattr(u, "geoms") else [u])]
    grand = max(p.area for p in polys)
    polys = [p for p in polys if p.area > grand * 0.002]
    return MultiPolygon(polys).simplify(0.008, preserve_topology=True)


def ecrit_france(france, tous, toutes_communes, formes):
    """Fichiers de la vue nationale : départements, classements et index des communes."""
    if not france:
        return
    court = lambda b, v: {"id": b["id"], "dep": b["dep"], "commune": b["commune"], "inscrits": b["inscrits"], "abst22": b["abst22"], "v": v}
    top = {
        "reserve": [court(b, b["reserve"]) for b in sorted([b for b in tous if b["reserve"] is not None], key=lambda b: -b["reserve"])[:300]],
        "bascule": [court(b, b["bascule"]) for b in sorted([b for b in tous if b["bascule"] is not None], key=lambda b: -b["bascule"])[:300]],
        "serre": [court(b, b["reserve"]) for b in sorted([b for b in tous if b["serre"] and b["reserve"] is not None], key=lambda b: -b["reserve"])[:300]],
        "inscription": [{"code": k, "dep": c["dep"], "nom": c["nom"], "adultes": c["adultes"], "taux": c["taux"], "v": c["non_inscrits"]}
                        for k, c in sorted([x for x in toutes_communes.items() if x[1]["non_inscrits"]], key=lambda x: -x[1]["non_inscrits"])[:300]],
    }
    # Bornes nationales des cinq classes de couleur, pour que tous les départements partagent la même échelle.
    def bornes(valeurs):
        v = sorted(x for x in valeurs if x is not None)
        return [v[int(q * (len(v) - 1))] for q in (0.2, 0.4, 0.6, 0.8)] + [v[0], v[-1]]
    taux = {k: c["taux"] for k, c in toutes_communes.items()}
    echelles = {
        "reserve": bornes(b["reserve"] for b in tous),
        "bascule": bornes(b["bascule"] for b in tous),
        "serre": bornes(b["reserve"] for b in tous if b["serre"]),
        "inscription": bornes(taux.get(b["id"][:5]) for b in tous),
    }
    (OUT / "france.json").write_text(json.dumps({"departements": france, "top": top, "bornes": echelles}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "departements.json").write_text(json.dumps({"type": "FeatureCollection", "features": formes}, separators=(",", ":")), encoding="utf-8")
    # Index des communes pour la recherche : nom → département (le site charge ensuite le bon département).
    idx = sorted({(b["commune"], b["dep"]) for b in tous if b["commune"]})
    (OUT / "communes.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def index():
    """Liste des départements déjà calculés, pour le menu du site."""
    codes = sorted((p.stem for p in OUT.glob("*.json") if p.stem.isalnum() and p.stem != "index"),
                   key=lambda c: (len(c) > 2, c.replace("2A", "20.1").replace("2B", "20.2")))
    anciens = {d["code"]: d["nom"] for d in json.loads((OUT / "index.json").read_text(encoding="utf-8"))} if (OUT / "index.json").exists() else {}
    (OUT / "index.json").write_text(json.dumps([{"code": c, "nom": NOMS.get(c) or anciens.get(c, c)} for c in codes], ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
    index()
