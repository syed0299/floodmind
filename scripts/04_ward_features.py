"""Static per-ward features: terrain, land cover, population, roads, facilities, water proximity."""
import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds

from floodmind.config import BBOX, CRS_METRIC, INTERIM, PROCESSED, RAW, WORLDCOVER, WORLDPOP

wards = gpd.read_file(INTERIM / "wards.gpkg")
wm = wards.to_crs(CRS_METRIC)
ids = wards["ward_id"].to_numpy()
feat = wards[["ward_id", "area_km2", "lon", "lat"]].copy()


def ward_index_raster(shape, transform, gdf):
    """Raster of row positions (0..n-1) in gdf, -1 outside any ward."""
    return rasterize(((g, i) for i, g in enumerate(gdf.geometry)), out_shape=shape,
                     transform=transform, fill=-1, dtype="int32")


def zonal(values, zone, n, how="mean", q=None):
    ok = (zone >= 0) & np.isfinite(values)
    z, v = zone[ok], values[ok]
    if how == "mean":
        return np.bincount(z, v, n) / np.maximum(np.bincount(z, minlength=n), 1)
    if how == "sum":
        return np.bincount(z, v, n)
    out = np.full(n, np.nan)  # percentile
    order = np.argsort(z, kind="stable")
    z, v = z[order], v[order]
    bounds = np.searchsorted(z, np.arange(n + 1))
    for i in range(n):
        seg = v[bounds[i]:bounds[i + 1]]
        if len(seg):
            out[i] = np.percentile(seg, q)
    return out


n = len(wards)

# --- terrain (30 m UTM) ---
T = INTERIM / "terrain"
with rasterio.open(T / "dtm.tif") as s:
    tshape, ttr = s.shape, s.transform
zone = ward_index_raster(tshape, ttr, wm)
r = {k: rasterio.open(T / f"{k}.tif").read(1) for k in
     ("dtm", "hand", "sink_depth", "facc", "slope", "twi", "channels")}
feat["elev_mean"] = zonal(r["dtm"], zone, n)
feat["elev_p10"] = zonal(r["dtm"], zone, n, "pct", 10)
feat["hand_mean"] = zonal(r["hand"], zone, n)
feat["hand_p10"] = zonal(r["hand"], zone, n, "pct", 10)
feat["frac_hand_lt1"] = zonal((r["hand"] < 1).astype(float), zone, n)
feat["frac_hand_lt3"] = zonal((r["hand"] < 3).astype(float), zone, n)
feat["sink_frac"] = zonal((r["sink_depth"] > 0.2).astype(float), zone, n)
feat["sink_mean_depth"] = zonal(r["sink_depth"], zone, n)
feat["slope_mean"] = zonal(r["slope"], zone, n)
feat["twi_mean"] = zonal(r["twi"], zone, n)
feat["twi_p90"] = zonal(r["twi"], zone, n, "pct", 90)
feat["facc_logmax"] = np.log1p(zonal(r["facc"], zone, n, "pct", 99))
feat["frac_channel"] = zonal(r["channels"], zone, n)

# --- land cover (ESA WorldCover 10 m, lon/lat) ---
classes = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
           80: "water", 90: "wetland", 95: "mangrove"}
with rasterio.open(WORLDCOVER) as s:
    win = from_bounds(*BBOX, s.transform)
    lc = s.read(1, window=win)
    lctr = s.window_transform(win)
zl = ward_index_raster(lc.shape, lctr, wards)
tot = np.maximum(np.bincount(zl[zl >= 0], minlength=n), 1)
for code, name in classes.items():
    m = (zl >= 0) & (lc == code)
    feat[f"lc_{name}"] = np.bincount(zl[m], minlength=n) / tot

# --- population (WorldPop 2020 constrained, ~100 m) ---
if WORLDPOP.exists():
    try:
        with rasterio.open(WORLDPOP) as s:
            win = from_bounds(*BBOX, s.transform)
            pop = s.read(1, window=win).astype(float)
            ptr = s.window_transform(win)
            pop[pop == s.nodata] = 0
        zp = ward_index_raster(pop.shape, ptr, wards)
        feat["pop"] = zonal(pop, zp, n, "sum")
        feat["pop_density"] = feat["pop"] / feat["area_km2"]
    except rasterio.errors.RasterioIOError as e:
        print("WorldPop not readable yet:", e)

# --- roads & facilities (OSM) ---
roads = gpd.read_file(RAW / "osm" / "roads.gpkg").to_crs(CRS_METRIC)
rj = gpd.overlay(roads[["highway", "geometry"]], wm[["ward_id", "geometry"]], how="intersection",
                 keep_geom_type=True)
rj["km"] = rj.length / 1000
major = rj["highway"].str.contains("primary|secondary|trunk|motorway")
feat = feat.merge(rj.groupby("ward_id")["km"].sum().rename("road_km"), on="ward_id", how="left")
feat = feat.merge(rj[major].groupby("ward_id")["km"].sum().rename("major_road_km"), on="ward_id", how="left")

fac = gpd.read_file(RAW / "osm" / "facilities.gpkg").to_crs(CRS_METRIC)
fac["geometry"] = fac.geometry.representative_point()
fj = gpd.sjoin(fac, wm[["ward_id", "geometry"]], predicate="within")
for kind, amen in {"hospitals": ["hospital", "clinic"], "schools": ["school", "college"],
                   "emergency": ["fire_station", "police"],
                   "shelters": ["shelter", "community_centre"]}.items():
    c = fj[fj["amenity"].isin(amen)].groupby("ward_id").size().rename(f"n_{kind}")
    feat = feat.merge(c, on="ward_id", how="left")

# --- distance from ward to water features ---
ww = gpd.read_file(RAW / "osm" / "waterways.gpkg").to_crs(CRS_METRIC)
wb = gpd.read_file(RAW / "osm" / "waterbodies.gpkg").to_crs(CRS_METRIC)
wb = wb[wb.geometry.type.isin(["Polygon", "MultiPolygon"])]
wb = wb[wb.area > 1e4]  # lakes/tanks larger than 1 ha
coast = ox.features_from_bbox(BBOX, {"natural": "coastline"}).to_crs(CRS_METRIC)
targets = {
    "dist_river": ww[ww["waterway"] == "river"],
    "dist_canal": ww[ww["waterway"] == "canal"],
    "dist_drain": ww[ww["waterway"].isin(["drain", "stream", "ditch"])],
    "dist_lake": wb,
    "dist_coast": coast,
}
cent = wm.geometry.centroid
for name, g in targets.items():
    u = g.geometry.union_all()
    feat[name] = cent.distance(u).to_numpy() / 1000  # km
feat["lake_area_1km"] = [wb.clip(c.buffer(1000)).area.sum() / 1e6 for c in cent]

feat = feat.fillna({c: 0 for c in feat.columns if c.startswith(("n_", "road", "major_"))})
feat["road_density"] = feat["road_km"] / feat["area_km2"]
feat.to_parquet(PROCESSED / "ward_static.parquet", index=False)
print(feat.shape)
print(feat.describe().T[["mean", "min", "max"]].round(3).to_string())
