"""Export light-weight GeoJSON layers for the dashboard (no external map tiles needed)."""
import json

import geopandas as gpd
import pandas as pd

from floodmind.config import CRS_METRIC, INTERIM, PROCESSED, RAW
from floodmind.gazetteer import load as load_gaz

OUT = PROCESSED / "web"
OUT.mkdir(exist_ok=True)


def dump(gdf, name, tol_m, props):
    g = gdf.to_crs(CRS_METRIC)
    g["geometry"] = g.geometry.simplify(tol_m, preserve_topology=True)
    g = g.to_crs(4326)[props + ["geometry"]]
    js = json.loads(g.to_json(drop_id=True))
    for f in js["features"]:  # trim coordinate precision (~1 m)
        f["geometry"] = json.loads(json.dumps(f["geometry"]),
                                   parse_float=lambda x: round(float(x), 5))
    (OUT / f"{name}.geojson").write_text(json.dumps(js, separators=(",", ":")))
    print(name, len(g), f"{(OUT / f'{name}.geojson').stat().st_size / 1024:.0f} KB")


wards = gpd.read_file(INTERIM / "wards.gpkg")
static = pd.read_parquet(PROCESSED / "ward_static.parquet")
gaz = load_gaz()
# Name each ward after the most prominent OSM place inside it (suburb > neighbourhood > ...).
rank = {"suburb": 0, "quarter": 1, "neighbourhood": 2, "town": 3, "locality": 4, "village": 5}
gz = gaz[gaz.ward_id.notna()].assign(r=lambda d: d.place.map(rank).fillna(9))
gz = gz.sort_values(["ward_id", "r"]).drop_duplicates("ward_id")
names = dict(zip(gz.ward_id.astype(int), gz.name))
wards["name"] = wards.ward_id.map(names).fillna("")
# Wards with no OSM place inside take the nearest named place within 1.5 km.
pts = gpd.GeoDataFrame(gaz, geometry=gpd.points_from_xy(gaz.lon, gaz.lat), crs=4326).to_crs(CRS_METRIC)
cent = wards.to_crs(CRS_METRIC).geometry.centroid
for i in wards.index[wards["name"] == ""]:
    d = pts.distance(cent[i])
    if d.min() <= 1500:
        wards.loc[i, "name"] = "near " + pts.loc[d.idxmin(), "name"]
keep = ["pop", "pop_density", "elev_mean", "frac_hand_lt1", "sink_frac", "lc_built",
        "n_hospitals", "n_schools", "n_shelters", "road_km"]
keep = [c for c in keep if c in static]
wards = wards.merge(static[["ward_id"] + keep], on="ward_id", how="left")
for c in keep:
    wards[c] = wards[c].round(3)
dump(wards, "wards", 25, ["ward_id", "name", "area_km2"] + keep)

ww = gpd.read_file(RAW / "osm" / "waterways.gpkg")
ww = ww[ww.waterway.isin(["river", "canal"])]
ww = ww.clip(wards.total_bounds)
dump(ww, "waterways", 20, ["name", "waterway"])

wb = gpd.read_file(RAW / "osm" / "waterbodies.gpkg")
wb = wb[wb.geometry.type.isin(["Polygon", "MultiPolygon"])]
wb = wb[wb.to_crs(CRS_METRIC).area > 5e4].clip(wards.total_bounds)
dump(wb, "lakes", 20, ["name"])
