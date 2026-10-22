"""Calcule, pour chaque bureau de vote, où la gauche a le plus de voix à gagner.

    python build.py            # départements listés dans DEPARTEMENTS
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
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
OUT = ROOT / "site" / "data"
DEPARTEMENTS = ["59"]

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
ECART_INSCRITS = 0.25 # au-delà, le bureau a probablement changé de périmètre entre 2017 et 2022


def num(x):
    return int(x or 0)


def lire_presidentielle(fichier, election, deps):
    """Fichiers 2017 et 2022 : 21 colonnes fixes, puis 7 colonnes par candidat."""
    res = {}
    with open(CACHE / fichier, encoding="latin-1") as f:
        r = csv.reader(f, delimiter=";")
        next(r)
        for row in r:
            dep = row[0].zfill(2)
            if dep not in deps:
                continue
            NOMS[dep] = row[1]
            bv = f"{dep}{row[4].zfill(3)}_{row[6].zfill(4)}"
            exp = num(row[18])
            voix = {row[i + 2]: num(row[i + 4]) for i in range(21, len(row) - 6, 7)}
            res[bv] = {"inscrits": num(row[7]), "abst": num(row[8]), "exp": exp,
                       "gauche": sum(v for k, v in voix.items() if k in GAUCHE[election]),
                       "rn": sum(v for k, v in voix.items() if k in RN[election])}
    return res


def lire_europeennes(deps):
    res = {}
    with open(CACHE / "eu24.csv", encoding="utf-8") as f:
        r = csv.reader(f, delimiter=";")
        next(r)
        for row in r:
            if row[2] not in deps:
                continue
            bv = f"{row[4]}_{row[6].zfill(4)}"
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
            dep = row["Code département"].zfill(2)
            if dep not in deps:
                continue
            bv = f"{row['Code commune'].zfill(5)}_{row['Code BV'].zfill(4)}"
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


def part(d, cle):
    return d[cle] / d["exp"] if d and d["exp"] else None


def contours(deps):
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from shapely import wkb
    from shapely.geometry import mapping
    t = pq.read_table(CACHE / "contours.parquet", columns=["codeDepartement", "codeBureauVote", "nomCommune", "geom"])
    t = t.filter(pc.is_in(t["codeDepartement"], value_set=__import__("pyarrow").array(deps)))
    out = {}
    for code, nom, geom in zip(t["codeBureauVote"].to_pylist(), t["nomCommune"].to_pylist(), t["geom"].to_pylist()):
        g = wkb.loads(geom).simplify(0.00008, preserve_topology=True)
        gj = mapping(g)
        arrondi = lambda c: [[round(x, 5), round(y, 5)] for x, y in c]
        if gj["type"] == "Polygon":
            gj = {"type": "MultiPolygon", "coordinates": [[arrondi(r) for r in gj["coordinates"]]]}
        else:
            gj = {"type": "MultiPolygon", "coordinates": [[arrondi(r) for r in p] for p in gj["coordinates"]]}
        out[code] = (nom, gj)
    return out


def main():
    deps = [d.zfill(2) for d in sys.argv[1:]] or DEPARTEMENTS
    OUT.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copytree(ROOT / "static", OUT.parent, dirs_exist_ok=True)
    pr17 = lire_presidentielle("pr17_t1.txt", "pr17", deps)
    pr22 = lire_presidentielle("pr22_t1.txt", "pr22", deps)
    eu24 = lire_europeennes(deps)
    lg24 = lire_legislatives(deps)
    geo = contours(deps)
    print(f"bureaux : 2017 {len(pr17)}, 2022 {len(pr22)}, euro 2024 {len(eu24)}, légis 2024 {len(lg24)}, contours {len(geo)}")

    for dep in deps:
        bureaux = []
        for bv, b22 in pr22.items():
            if not bv.startswith(dep):
                continue
            b17, be, bl = pr17.get(bv), eu24.get(bv), lg24.get(bv)
            g = {k: part(d, "gauche") for k, d in (("2017", b17), ("2022", b22), ("euro24", be), ("legis24", bl))}
            rn = {k: part(d, "rn") for k, d in (("2017", b17), ("2022", b22), ("euro24", be), ("legis24", bl))}
            # Le bureau a-t-il gardé le même périmètre depuis 2017 ? Sinon la comparaison n'a pas de sens.
            comparable = bool(b17) and abs(b17["inscrits"] - b22["inscrits"]) <= ECART_INSCRITS * b22["inscrits"]
            reserve = round(b22["abst"] * (g["2022"] or 0))
            rn_recent = rn["legis24"] if rn["legis24"] is not None else rn["2022"]
            bascule = round(b22["exp"] * max(0, rn_recent - rn["2017"]) * g["2017"]) if comparable and rn_recent is not None else None
            serre = (bl is not None and g["legis24"] is not None and abs(g["legis24"] - rn["legis24"]) < SERRE)
            parts_g = [v for v in g.values() if v is not None]
            nom, _ = geo.get(bv, (None, None))
            bureaux.append({
                "id": bv, "commune": nom, "inscrits": b22["inscrits"],
                "abst22": round(b22["abst"] / b22["inscrits"], 3) if b22["inscrits"] else None,
                "gauche": {k: round(v, 3) if v is not None else None for k, v in g.items()},
                "rn": {k: round(v, 3) if v is not None else None for k, v in rn.items()},
                "reserve": reserve, "bascule": bascule, "serre": serre, "comparable": comparable,
                "volatilite": round(statistics.pstdev(parts_g), 3) if len(parts_g) > 1 else None,
                "contour": bv in geo,
            })
        # Noms de commune manquants (bureau sans contour) : on les reprend des résultats 2022.
        for b in bureaux:
            b["rang_reserve"] = None
        for i, b in enumerate(sorted(bureaux, key=lambda b: -b["reserve"]), 1):
            b["rang_reserve"] = i
        for i, b in enumerate(sorted([b for b in bureaux if b["bascule"] is not None], key=lambda b: -b["bascule"]), 1):
            b["rang_bascule"] = i
        (OUT / f"{dep}.json").write_text(json.dumps({"dep": dep, "bureaux": bureaux}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        feats = [{"type": "Feature", "properties": {"id": code}, "geometry": gj}
                 for code, (nom, gj) in geo.items() if code.startswith(dep)]
        (OUT / f"{dep}-contours.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
        sans = sum(1 for b in bureaux if not b["contour"])
        print(f"{dep} : {len(bureaux)} bureaux, {sum(1 for b in bureaux if b['comparable'])} comparables depuis 2017, "
              f"{sum(1 for b in bureaux if b['serre'])} serrés, {sans} sans contour, "
              f"réserve totale {sum(b['reserve'] for b in bureaux):,} voix")


def index():
    """Liste des départements déjà calculés, pour le menu du site."""
    codes = sorted(p.stem for p in OUT.glob("*.json") if p.stem.isalnum() and not p.stem.endswith("contours") and p.stem != "index")
    anciens = {d["code"]: d["nom"] for d in json.loads((OUT / "index.json").read_text(encoding="utf-8"))} if (OUT / "index.json").exists() else {}
    (OUT / "index.json").write_text(json.dumps([{"code": c, "nom": NOMS.get(c) or anciens.get(c, c)} for c in codes], ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
    index()
