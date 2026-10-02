"""Truth engine: fuse Groundsource polygons and curated news reports into ward-day labels.

Groundsource (Google, CC-BY-4.0) is news-derived: Gemini read articles, Google Maps geocoded
the place. Its authors report ~82% of events usable in location and time, so its positives
get weight 0.8. Polygons larger than 30 km² ("Chennai flooded") carry no ward-level
information; they only mark the day as a city-wide event.

A polygon is assigned to every ward holding >=25% of the polygon's area or covering >=20% of
the ward; tiny (point-like) polygons go to the ward that contains them.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from floodmind.config import CRS_METRIC, INTERIM, PROCESSED, RAW
from floodmind.gazetteer import load as load_gaz, lookup

wards = gpd.read_file(INTERIM / "wards.gpkg").to_crs(CRS_METRIC)
wards["ward_area"] = wards.area

# ---------- Groundsource ----------
gs = gpd.read_parquet(INTERIM / "groundsource_chennai.parquet").to_crs(CRS_METRIC)
gs["start"] = pd.to_datetime(gs["start_date"])
gs["end"] = pd.to_datetime(gs["end_date"])
gs = gs[gs["start"].dt.year >= 2015]
citywide = gs[gs["area_km2"] >= 30]
local = gs[gs["area_km2"] < 30].copy()
local["poly_area"] = local.area.clip(lower=1.0)

ov = gpd.overlay(local[["uuid", "start", "end", "poly_area", "geometry"]],
                 wards[["ward_id", "ward_area", "geometry"]], how="intersection",
                 keep_geom_type=False)
ov["a"] = ov.area
ov["share_poly"] = ov["a"] / ov["poly_area"]
ov["share_ward"] = ov["a"] / ov["ward_area"]
tiny = ov["poly_area"] < 2e4  # under 0.02 km²: effectively a point
keep = (ov["share_poly"] >= 0.25) | (ov["share_ward"] >= 0.20) | tiny
ov = ov[keep]
print(f"Groundsource: {local.uuid.nunique()} local polygons → {ov.uuid.nunique()} matched to wards, "
      f"{len(ov)} polygon-ward links; {len(citywide)} city-wide records")

rows = []
for r in ov.itertuples():
    days = pd.date_range(r.start, min(r.end, r.start + pd.Timedelta(days=3)), freq="D")
    rows += [(r.ward_id, d, 0.8, "groundsource") for d in days]
gs_lab = pd.DataFrame(rows, columns=["ward_id", "date", "conf", "source"])

# ---------- curated news reports ----------
news = pd.read_csv(RAW / "reports" / "news_reports.csv", parse_dates=["date"])
gaz = load_gaz()
hits = [lookup(n, gaz) for n in news["locality"]]
news["lat"] = [h[0] if h else np.nan for h in hits]
news["lon"] = [h[1] if h else np.nan for h in hits]
news["ward_id"] = [h[2] if h else np.nan for h in hits]
unmatched = news[news["lat"].isna()]["locality"].unique()
outside = news[news["lat"].notna() & news["ward_id"].isna()]["locality"].unique()
print(f"news: {len(news)} reports; not in gazetteer: {list(unmatched)}; outside GCC: {list(outside)}")
news.to_csv(PROCESSED / "news_reports_geocoded.csv", index=False)
nw = news.dropna(subset=["ward_id"])
nw_lab = pd.DataFrame({"ward_id": nw["ward_id"].astype(int), "date": nw["date"],
                       "conf": nw["confidence"].map({"high": 1.0, "medium": 0.7}).fillna(0.7),
                       "source": "news"})

labels = pd.concat([gs_lab, nw_lab])
labels.to_parquet(PROCESSED / "labels_by_source.parquet", index=False)
agg = labels.groupby(["ward_id", "date"]).agg(conf=("conf", "max"),
                                              n_sources=("source", "nunique")).reset_index()
agg.to_parquet(PROCESSED / "labels.parquet", index=False)

cw = citywide[["start", "end"]].copy()
cw_days = sorted({d for s, e in zip(cw.start, cw.end) for d in pd.date_range(s, e, freq="D")})
pd.DataFrame({"date": cw_days}).to_parquet(PROCESSED / "citywide_event_days.parquet", index=False)

print(f"labels: {len(agg):,} ward-days across {agg.date.nunique()} days, "
      f"{agg.ward_id.nunique()} wards ever flooded")
by_year = agg.groupby(agg.date.dt.year).size()
print("ward-days by year:", by_year.to_dict())
# Agreement check: of curated news ward-days, how many does Groundsource also have (±1 day)?
g = set(zip(gs_lab.ward_id, gs_lab.date))
agree = [any((w, d + pd.Timedelta(days=k)) in g for k in (-1, 0, 1))
         for w, d in zip(nw_lab.ward_id, nw_lab.date)]
print(f"news reports also present in Groundsource (±1 day): {np.mean(agree):.0%} of {len(agree)}")
