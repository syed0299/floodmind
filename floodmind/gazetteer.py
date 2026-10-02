"""Offline locality -> ward lookup built from OSM place names.

News reports name localities ("Velachery", "K.K. Nagar", "Pulianthope"), not coordinates.
We match normalised names against OSM suburb/neighbourhood/locality points inside the study
area, then assign the ward containing that point.
"""
import re

import geopandas as gpd
import osmnx as ox
import pandas as pd

from floodmind.config import BBOX, INTERIM

GAZ = INTERIM / "gazetteer.parquet"

# Common spelling variants in Chennai news coverage.
ALIASES = {
    "kk nagar": "k k nagar", "k.k. nagar": "k k nagar", "kodambakam": "kodambakkam",
    "t nagar": "t nagar", "t. nagar": "t nagar", "thyagaraya nagar": "t nagar",
    "pulianthope": "pulianthope", "puliyanthope": "pulianthope", "vyasarpadi": "vyasarpadi",
    "vysarpadi": "vyasarpadi", "mylapore": "mylapore", "mambalam": "west mambalam",
    "ashok nagar": "ashok nagar", "velacheri": "velachery", "pallikaranai": "pallikaranai",
    "perumbakkam": "perumbakkam", "madipakkam": "madipakkam", "tondiarpet": "tondiarpet",
    "royapuram": "royapuram", "otteri": "otteri", "perambur": "perambur",
    "kolathur": "kolathur", "korattur": "korattur", "ambattur": "ambattur",
    "anna nagar": "anna nagar", "nungambakkam": "nungambakkam", "saidapet": "saidapet",
    "adyar": "adyar", "besant nagar": "besant nagar", "thiruvanmiyur": "thiruvanmiyur",
    "taramani": "taramani", "guindy": "guindy", "valasaravakkam": "valasaravakkam",
    "virugambakkam": "virugambakkam", "vadapalani": "vadapalani", "egmore": "egmore",
    "chetpet": "chetpet", "kilpauk": "kilpauk", "purasawalkam": "purasaiwakkam",
    "purasaiwalkam": "purasaiwakkam", "manali": "manali", "ennore": "ennore",
    "tiruvottiyur": "thiruvottiyur", "thiruvotriyur": "thiruvottiyur",
    "madhavaram": "madhavaram", "kodungaiyur": "kodungaiyur", "sholinganallur": "sholinganallur",
    "semmencheri": "semmencheri", "ramapuram": "ramapuram", "mugalivakkam": "mugalivakkam",
    "porur": "porur", "alandur": "alandur", "nanganallur": "nanganallur",
    "jafferkhanpet": "jafferkhanpet", "ekkatuthangal": "ekkattuthangal",
    "ekkattuthangal": "ekkattuthangal", "kotturpuram": "kotturpuram",
}


def norm(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[\.\-,']", " ", s)
    s = re.sub(r"\b(chennai|area|areas|locality|road|main road|extension|ext)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def build():
    tags = {"place": ["suburb", "neighbourhood", "quarter", "locality", "village", "hamlet",
                      "town"]}
    g = ox.features_from_bbox(BBOX, tags)
    g = g[g["name"].notna()].copy()
    g["geometry"] = g.geometry.representative_point()
    names = []
    for _, r in g.iterrows():
        for col in ("name", "name:en", "alt_name", "old_name"):
            if col in g.columns and isinstance(r.get(col), str):
                for n in r[col].split(";"):
                    names.append({"name": n, "key": norm(n), "place": r["place"],
                                  "lon": r.geometry.x, "lat": r.geometry.y})
    gaz = pd.DataFrame(names).drop_duplicates(["key", "lat", "lon"])
    pts = gpd.GeoDataFrame(gaz, geometry=gpd.points_from_xy(gaz.lon, gaz.lat), crs=4326)
    wards = gpd.read_file(INTERIM / "wards.gpkg")
    pts = gpd.sjoin(pts, wards[["ward_id", "geometry"]], how="left", predicate="within")
    out = pd.DataFrame(pts.drop(columns=["geometry", "index_right"]))
    out.to_parquet(GAZ, index=False)
    return out


def load():
    return pd.read_parquet(GAZ) if GAZ.exists() else build()


def lookup(name: str, gaz: pd.DataFrame | None = None):
    """Return (lat, lon, ward_id or NaN) for a locality name, or None if unknown."""
    gaz = load() if gaz is None else gaz
    k = norm(name)
    hit = gaz[gaz["key"] == k]
    if hit.empty:
        hit = gaz[gaz["key"].str.startswith(k + " ") | (gaz["key"] == k.replace(" ", ""))]
    if hit.empty:
        return None
    # Prefer candidates inside GCC, then broader place types (suburb before hamlet).
    rank = {"suburb": 0, "quarter": 1, "neighbourhood": 2, "town": 3, "locality": 4,
            "village": 5, "hamlet": 6}
    hit = hit.assign(_out=hit["ward_id"].isna(), _rank=hit["place"].map(rank).fillna(9))
    r = hit.sort_values(["_out", "_rank"]).iloc[0]
    return float(r.lat), float(r.lon), r.ward_id


if __name__ == "__main__":
    gaz = build()
    print(f"{len(gaz)} names, {gaz.ward_id.notna().sum()} inside GCC wards")
    for t in ["Velachery", "K.K. Nagar", "Pulianthope", "Mudichur", "Pallikaranai", "Saidapet"]:
        print(t, lookup(t, gaz))
