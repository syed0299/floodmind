"""Per-ward daily rainfall for the northeast-monsoon seasons (Oct–Dec) 2015–2025.

Observed: IMD 0.25° gauge-based gridded rainfall. IMD's day D is the 24 h ending 08:30 IST
on D. Cells over the sea are NaN, so each ward gets an inverse-distance-weighted mix of the
nearest valid land cells.

Forecast: ECMWF IFS 0.25° via Open-Meteo's Previous Runs API (archived from 2024).
`fc_d0_day1` is what the model run from ~24 h earlier predicted for the same 08:30–08:30
window, i.e. what an operational system would actually have known.
"""
import time

import imdlib as imd
import numpy as np
import pandas as pd
import requests
import geopandas as gpd

from floodmind.config import INTERIM, PROCESSED, RAW

YEARS = range(2015, 2026)
IMD_DIR = RAW / "rain" / "imd"
wards = gpd.read_file(INTERIM / "wards.gpkg")

# ---------- observed (IMD) ----------
frames = []
for y in YEARS:
    if not (IMD_DIR / "rain" / f"{y}.grd").exists():
        print("missing IMD", y)
        continue
    ds = imd.open_data("rain", y, y, "yearwise", str(IMD_DIR)).get_xarray()
    sub = ds["rain"].sel(lat=slice(12.4, 13.8), lon=slice(79.6, 80.6))
    sub = sub.where(sub > -1)  # IMD uses -999 for missing
    frames.append(sub.to_dataframe().reset_index())
grid = pd.concat(frames)
grid = grid.dropna(subset=["rain"])
cells = grid[["lat", "lon"]].drop_duplicates().to_numpy()
print(f"IMD land cells used: {len(cells)}")

# IDW weights from each ward centroid to its 4 nearest valid cells.
wxy = wards[["lat", "lon"]].to_numpy()
d = np.hypot((wxy[:, None, 0] - cells[None, :, 0]) * 111,
             (wxy[:, None, 1] - cells[None, :, 1]) * 108)
nn = np.argsort(d, axis=1)[:, :4]
W = np.zeros_like(d)
for i in range(len(wxy)):
    w = 1 / np.maximum(d[i, nn[i]], 1.0) ** 2
    W[i, nn[i]] = w / w.sum()

cell_key = {tuple(c): j for j, c in enumerate(map(tuple, cells))}
grid["j"] = [cell_key[(a, b)] for a, b in zip(grid["lat"], grid["lon"])]
piv = grid.pivot_table(index="time", columns="j", values="rain").reindex(columns=range(len(cells)))
piv = piv.T.fillna(piv.mean(axis=1)).T  # rare gaps: use that day's regional mean
ward_rain = pd.DataFrame(piv.to_numpy() @ W.T, index=piv.index, columns=wards["ward_id"])
obs = ward_rain.stack().rename("rain_obs").reset_index().rename(columns={"time": "date"})
obs["date"] = pd.to_datetime(obs["date"]).dt.normalize()
obs.to_parquet(INTERIM / "rain_obs_daily.parquet", index=False)
print(f"observed: {obs.date.min().date()} → {obs.date.max().date()}, {len(obs):,} ward-days")

# ---------- forecast (ECMWF IFS, archived 24 h-ahead) ----------
# Four points spanning the city; wards take the nearest point.
pts = pd.DataFrame({"lat": [13.18, 13.18, 12.95, 12.95], "lon": [80.20, 80.29, 80.18, 80.26]})
rows = []
for k, p in pts.iterrows():
    for y in (2024, 2025):
        url = ("https://previous-runs-api.open-meteo.com/v1/forecast"
               f"?latitude={p.lat}&longitude={p.lon}&start_date={y}-09-25&end_date={y}-12-31"
               "&hourly=precipitation,precipitation_previous_day1,precipitation_previous_day2"
               "&models=ecmwf_ifs025&timezone=Asia%2FKolkata")
        for attempt in range(5):
            r = requests.get(url, timeout=120)
            if r.ok:
                break
            time.sleep(5 * (attempt + 1))
        r.raise_for_status()
        h = pd.DataFrame(r.json()["hourly"])
        h["time"] = pd.to_datetime(h["time"])
        # Shift so hours 08:30(D-1)..08:30(D) fall on IMD day D (hourly totals end on the hour).
        h["date"] = (h["time"] + pd.Timedelta(hours=15, minutes=30)).dt.normalize()
        g = h.groupby("date")[["precipitation", "precipitation_previous_day1",
                               "precipitation_previous_day2"]].sum(min_count=20)
        g["pt"] = k
        rows.append(g.reset_index())
        time.sleep(1)
fc = pd.concat(rows).rename(columns={"precipitation": "fc_d0_analysis",
                                     "precipitation_previous_day1": "fc_d0_day1",
                                     "precipitation_previous_day2": "fc_d0_day2"})
near = np.argmin(np.hypot(wxy[:, None, 0] - pts.lat.to_numpy()[None],
                          wxy[:, None, 1] - pts.lon.to_numpy()[None]), axis=1)
wmap = pd.DataFrame({"ward_id": wards["ward_id"], "pt": near})
fcw = wmap.merge(fc, on="pt").drop(columns="pt")
fcw.to_parquet(INTERIM / "rain_fc_daily.parquet", index=False)
print(f"forecast: {fcw.date.min().date()} → {fcw.date.max().date()}, {len(fcw):,} ward-days")

# Quick sanity check against known events (city mean).
chk = obs.groupby("date")["rain_obs"].mean()
for day in ["2015-12-02", "2021-11-07", "2021-12-31", "2023-12-04", "2023-12-05",
            "2024-10-16", "2024-12-01", "2025-12-02"]:
    v = chk.get(pd.Timestamp(day), np.nan)
    f = fcw[fcw.date == pd.Timestamp(day)][["fc_d0_analysis", "fc_d0_day1"]].mean()
    print(f"  {day}: IMD {v:6.1f} mm | ECMWF analysis {f.iloc[0]:6.1f} | 24h-ahead {f.iloc[1]:6.1f}")
