"""Construit data/profils.json : le profil social de chaque bureau de vote (Insee, Filosofi 2021).

Chaque carreau de 200 m est rattaché au bureau de vote qui contient son centre, puis les carreaux
d'un même bureau sont additionnés. Couvre la métropole, la Martinique et La Réunion (seules zones
publiées par l'Insee).

À relancer seulement si l'Insee publie un nouveau millésime :
    python scripts/profils.py
"""
import csv
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer
from shapely import STRtree, points, wkb

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
SOURCE = "https://www.insee.fr/fr/statistiques/fichier/8735162/Filosofi2021_carreaux_200m_csv.zip"
CHAMPS = ["ind", "men", "men_pauv", "men_prop", "ind_snv", "log_soc",
          "log_av45", "log_45_70", "log_70_90", "log_ap90", "log_inc",
          "ind_18_24", "ind_25_39", "ind_40_54", "ind_55_64", "ind_65_79", "ind_80p"]
ID = re.compile(r"CRS(\d+)RES200mN(\d+)E(\d+)")


def carreaux():
    """Centre de chaque carreau (longitude, latitude) et ses effectifs."""
    if not (CACHE / "filo21.zip").exists():
        urllib.request.urlretrieve(SOURCE, CACHE / "filo21.zip")
    transfos = {}
    with zipfile.ZipFile(CACHE / "filo21.zip") as z:
        for nom in z.namelist():
            xs, ys, vals, crs = [], [], [], None
            for row in csv.DictReader(io.TextIOWrapper(z.open(nom), encoding="utf-8")):
                crs, n, e = ID.match(row["idcar_200m"]).groups()
                xs.append(int(e) + 100)
                ys.append(int(n) + 100)
                vals.append([float(row[c] or 0) for c in CHAMPS])
            t = transfos.setdefault(crs, Transformer.from_crs(f"EPSG:{crs}", "EPSG:4326", always_xy=True))
            lon, lat = t.transform(np.array(xs), np.array(ys))
            print(f"{nom} : {len(xs)} carreaux (EPSG:{crs})")
            yield lon, lat, np.array(vals)


def main():
    t = pq.read_table(CACHE / "contours.parquet", columns=["codeBureauVote", "geom"])
    codes = t["codeBureauVote"].to_pylist()
    arbre = STRtree([wkb.loads(g) for g in t["geom"].to_pylist()])
    totaux = np.zeros((len(codes), len(CHAMPS)))
    hors = 0
    for lon, lat, vals in carreaux():
        pts, polys = arbre.query(points(lon, lat), predicate="intersects")
        # Un centre sur une frontière peut toucher deux bureaux : on garde le premier.
        _, premier = np.unique(pts, return_index=True)
        np.add.at(totaux, polys[premier], vals[pts[premier]])
        hors += len(lon) - len(premier)
    print(f"{hors} carreaux hors de tout bureau (interstices entre contours)")

    i = {c: k for k, c in enumerate(CHAMPS)}
    profils = {}
    for code, v in zip(codes, totaux):
        adultes = v[i["ind_18_24"]:i["ind_80p"] + 1].sum()
        logements = v[i["log_av45"]:i["log_inc"] + 1].sum()
        if v[i["ind"]] < 50 or v[i["men"]] < 20:
            continue  # trop peu d'habitants recensés : profil peu fiable
        profils[code] = [
            round(v[i["ind_snv"]] / v[i["ind"]]),                                   # niveau de vie moyen (€ par an)
            round(v[i["men_pauv"]] / v[i["men"]], 3),                               # ménages pauvres
            round((v[i["ind_18_24"]] + v[i["ind_25_39"]]) / adultes, 3) if adultes else None,  # 18-39 ans parmi les majeurs
            round((v[i["ind_65_79"]] + v[i["ind_80p"]]) / adultes, 3) if adultes else None,    # 65 ans et plus
            round(v[i["log_soc"]] / logements, 3) if logements else None,           # logements sociaux
            round(v[i["men_prop"]] / v[i["men"]], 3),                               # ménages propriétaires
            round(v[i["ind"]]),                                                     # habitants
        ]
    t = totaux.sum(axis=0)
    adultes = t[i["ind_18_24"]:i["ind_80p"] + 1].sum()
    france = [round(t[i["ind_snv"]] / t[i["ind"]]), round(t[i["men_pauv"]] / t[i["men"]], 3),
              round((t[i["ind_18_24"]] + t[i["ind_25_39"]]) / adultes, 3), round((t[i["ind_65_79"]] + t[i["ind_80p"]]) / adultes, 3),
              round(t[i["log_soc"]] / t[i["log_av45"]:i["log_inc"] + 1].sum(), 3), round(t[i["men_prop"]] / t[i["men"]], 3), round(t[i["ind"]])]
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "profils.json").write_text(json.dumps({"champs": ["niveau_vie", "pauvrete", "jeunes", "seniors", "log_soc", "proprietaires", "habitants"],
                                                            "france": france, "bureaux": profils}, separators=(",", ":")), encoding="utf-8")
    print(f"{len(profils)} bureaux avec un profil ; moyennes : {france}")


if __name__ == "__main__":
    main()
