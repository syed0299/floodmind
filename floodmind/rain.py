"""Rainfall inputs on FloodMind's time convention, shared by training checks and the live engine.

IMD day D = the 24 h ending 08:30 IST on D. IMD grids are mapped to wards with the same
inverse-distance weighting used to build the training data (four nearest land cells).
Open-Meteo hourly totals end on the hour, so shifting by +15 h 30 min puts the hours
from 08:30 on D-1 to 08:30 on D onto day D.
"""
import datetime as dt
import time

import geopandas as gpd
import imdlib as imd
import numpy as np
import pandas as pd
import requests

from floodmind.config import INTERIM, RAW

IMD_BOX = dict(lat=slice(12.4, 13.8), lon=slice(79.6, 80.6))
IMD_RT_DIR = RAW / "rain" / "imd_rt"
IMD_RT_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
IMD_GRID_BYTES = 69660  # one day of the 0.25° India grid (135 x 129 float32)
# ECMWF 0.25° sample points spanning the city; each ward takes the nearest.
POINTS = pd.DataFrame({"lat": [13.18, 13.18, 12.95, 12.95], "lon": [80.20, 80.29, 80.18, 80.26]})


def _wards():
    return gpd.read_file(INTERIM / "wards.gpkg")


def imd_to_wards(da, wards=None) -> pd.DataFrame:
    """IMD rain DataArray (time, lat, lon) -> long table ward_id, date, rain."""
    wards = _wards() if wards is None else wards
    sub = da.sel(**IMD_BOX)
    sub = sub.where(sub > -1)
    grid = sub.to_dataframe(name="rain").reset_index().dropna(subset=["rain"])
    cells = grid[["lat", "lon"]].drop_duplicates().to_numpy()
    wxy = wards[["lat", "lon"]].to_numpy()
    d = np.hypot((wxy[:, None, 0] - cells[None, :, 0]) * 111, (wxy[:, None, 1] - cells[None, :, 1]) * 108)
    nn = np.argsort(d, axis=1)[:, :4]
    W = np.zeros_like(d)
    for i in range(len(wxy)):
        w = 1 / np.maximum(d[i, nn[i]], 1.0) ** 2
        W[i, nn[i]] = w / w.sum()
    key = {tuple(c): j for j, c in enumerate(map(tuple, cells))}
    grid["j"] = [key[(a, b)] for a, b in zip(grid["lat"], grid["lon"])]
    piv = grid.pivot_table(index="time", columns="j", values="rain").reindex(columns=range(len(cells)))
    piv = piv.T.fillna(piv.mean(axis=1)).T
    out = pd.DataFrame(piv.to_numpy() @ W.T, index=piv.index, columns=wards["ward_id"])
    out = out.stack().rename("rain").reset_index().rename(columns={"time": "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out


def _imd_rt_file(d: pd.Timestamp):
    return IMD_RT_DIR / f"rain_ind0.25_{d:%y_%m_%d}.grd"


def _fetch_imd_day(d: pd.Timestamp) -> bool:
    """Same request imdlib makes, but with timeouts so a slow IMD server cannot hang a run."""
    try:
        r = requests.post(IMD_RT_URL, data={"rain": d.strftime("%d%m%Y")}, timeout=(10, 40))
        if r.ok and len(r.content) == IMD_GRID_BYTES:
            _imd_rt_file(d).write_bytes(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def imd_realtime(start: dt.date, end: dt.date, budget_s: float = 90) -> pd.DataFrame:
    """IMD real-time 0.25° daily rain for [start, end], cached on disk. Days IMD has not
    published yet, or that do not arrive within the time budget, are absent from the result."""
    IMD_RT_DIR.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(start, end)
    ok = lambda d: _imd_rt_file(d).exists() and _imd_rt_file(d).stat().st_size == IMD_GRID_BYTES
    # IMD's server answers one request at a time (~15 s each) and stalls under parallel load,
    # so fetch sequentially, newest first: the last few days matter most to the model.
    missing = sorted((d for d in days if not ok(d)), reverse=True)
    t0, got, tried = time.monotonic(), 0, 0
    for d in missing:
        if time.monotonic() - t0 > budget_s:
            break
        tried += 1
        got += _fetch_imd_day(d)
    if missing:
        print(f"IMD real-time: fetched {got} of {len(missing)} missing days "
              f"({len(missing) - tried} left for a later run)")
    have = [d for d in days if ok(d)]
    if not have:
        return pd.DataFrame(columns=["ward_id", "date", "rain"])
    parts, run = [], [have[0]]
    # open_real_data reads a contiguous range; read runs of consecutive available days.
    for d in have[1:] + [None]:
        if d is not None and (d - run[-1]).days == 1:
            run.append(d)
            continue
        ds = imd.open_real_data("rain", str(run[0].date()), str(run[-1].date()), str(IMD_RT_DIR))
        parts.append(imd_to_wards(ds.get_xarray()["rain"]))
        run = [d] if d is not None else []
    return pd.concat(parts, ignore_index=True)


def to_imd_days(hourly: pd.DataFrame, cols, min_hours=20) -> pd.DataFrame:
    h = hourly.copy()
    h["date"] = (pd.to_datetime(h["time"]) + pd.Timedelta(hours=15, minutes=30)).dt.normalize()
    return h.groupby("date")[cols].sum(min_count=min_hours).reset_index()


def _get(url, tries=5):
    for k in range(tries):
        r = requests.get(url, timeout=120)
        if r.ok:
            return r.json()
        time.sleep(3 * (k + 1))
    r.raise_for_status()


def ecmwf_live(past_days=14, forecast_days=3) -> pd.DataFrame:
    """Latest ECMWF IFS 0.25° run from Open-Meteo: per point, IMD-day rain for recent past
    days (short-range forecasts stitched together) and the coming days."""
    rows = []
    for k, p in POINTS.iterrows():
        js = _get("https://api.open-meteo.com/v1/forecast"
                  f"?latitude={p.lat}&longitude={p.lon}&hourly=precipitation&models=ecmwf_ifs025"
                  f"&past_days={past_days}&forecast_days={forecast_days}&timezone=Asia%2FKolkata")
        g = to_imd_days(pd.DataFrame(js["hourly"]), ["precipitation"])
        g["pt"] = k
        rows.append(g)
    return pd.concat(rows).rename(columns={"precipitation": "rain"})


def points_to_wards(per_point: pd.DataFrame, wards=None) -> pd.DataFrame:
    """Give each ward the value of its nearest ECMWF sample point."""
    wards = _wards() if wards is None else wards
    wxy = wards[["lat", "lon"]].to_numpy()
    near = np.argmin(np.hypot(wxy[:, None, 0] - POINTS.lat.to_numpy()[None],
                              wxy[:, None, 1] - POINTS.lon.to_numpy()[None]), axis=1)
    m = pd.DataFrame({"ward_id": wards["ward_id"], "pt": near})
    return m.merge(per_point, on="pt").drop(columns="pt")
