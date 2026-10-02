"""Stage 2 check: replay the live engine's own code on 2024–25.

Model: the bundle trained on 2015–2023 only, so 2024–25 are unseen. Target-day rain is the
ECMWF forecast issued ~24 h earlier, as in the forecast-mode evaluation. The recent-rain
history (previous 60 days) comes from three sources:

  A imd_final  IMD's final gridded rain, as used in training. Must reproduce the
               forecast-mode evaluation (PR-AUC 0.527), proving the live code is the same model.
  B imd_rt     IMD's real-time grid: what the live engine uses day to day.
  C ecmwf      ECMWF short-range estimates only: the live engine's fallback when IMD is late.

Done when B (and ideally C) score within 0.02 PR-AUC of A.
"""
import datetime as dt
import json
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from floodmind.config import INTERIM, PROCESSED, REPORTS
from floodmind.live import forecast
from floodmind.model import Ensemble
from floodmind.rain import POINTS, imd_realtime, points_to_wards, to_imd_days

model = Ensemble.load("upto2023")
static = pd.read_parquet(PROCESSED / "ward_static.parquet")
wards = gpd.read_file(INTERIM / "wards.gpkg")
ds = pd.read_parquet(PROCESSED / "dataset.parquet", columns=["ward_id", "date", "y", "w", "fc_d0_day1"])
ev = ds[ds.fc_d0_day1.notna() & (ds.date.dt.year >= 2024)]
targets = sorted(ev.date.unique())
target_rain = ev.rename(columns={"fc_d0_day1": "rain"})[["ward_id", "date", "rain"]]
print(f"{len(targets)} target days, {int(ev.y.sum())} flooded ward-days")

# A: IMD final (training source)
obs = pd.read_parquet(INTERIM / "rain_obs_daily.parquet").rename(columns={"rain_obs": "rain"})
src = {"imd_final": obs[obs.date.dt.year >= 2024]}

# B: IMD real-time (whatever has been backfilled)
rt = pd.concat([imd_realtime(dt.date(y, 7, 25), dt.date(y, 12, 31), budget_s=0) for y in (2024, 2025)])
if len(rt):
    src["imd_rt"] = rt
    cov = rt["date"].nunique() / (2 * 160)
    print(f"IMD real-time coverage: {rt['date'].nunique()} days ({cov:.0%} of Jul 25–Dec 31, 2024–25)")

# C: ECMWF short-range only (Previous Runs API, day-0 runs stitched)
rows = []
for k, p in POINTS.iterrows():
    for y in (2024, 2025):
        url = ("https://previous-runs-api.open-meteo.com/v1/forecast"
               f"?latitude={p.lat}&longitude={p.lon}&start_date={y}-07-25&end_date={y}-12-31"
               "&hourly=precipitation&models=ecmwf_ifs025&timezone=Asia%2FKolkata")
        for t in range(5):
            r = requests.get(url, timeout=120)
            if r.ok:
                break
            time.sleep(5 * (t + 1))
        g = to_imd_days(pd.DataFrame(r.json()["hourly"]), ["precipitation"]).rename(columns={"precipitation": "rain"})
        g["pt"] = k
        rows.append(g)
src["ecmwf"] = points_to_wards(pd.concat(rows), wards)


def score(name, past):
    preds = []
    for t in targets:
        X = forecast([t], past, target_rain[target_rain.date == t], model, static)[t]
        preds.append(X[["ward_id", "p"]].assign(date=t, rain_7d=X.rain_7d))
    p = pd.concat(preds).merge(ev, on=["ward_id", "date"])
    p = p.dropna(subset=["p"])
    return p, {"pr_auc": average_precision_score(p.y, p.p, sample_weight=p.w),
               "roc_auc": roc_auc_score(p.y, p.p, sample_weight=p.w),
               "brier": brier_score_loss(p.y, p.p, sample_weight=p.w),
               "n_ward_days": int(len(p))}


results, preds = {}, {}
for name, past in src.items():
    preds[name], results[name] = score(name, past)
    r = results[name]
    print(f"{name:10s} PR-AUC {r['pr_auc']:.3f}  ROC {r['roc_auc']:.3f}  Brier {r['brier']:.4f}  "
          f"({r['n_ward_days']} ward-days)")

ref = json.loads((REPORTS / "metrics.json").read_text())["forecast_mode_2024_25"]["ecmwf_24h_ahead"]["pr_auc"]
results["reference_forecast_mode_pr_auc"] = ref
for name in src:
    results[name]["gap_vs_reference"] = results[name]["pr_auc"] - ref
# How different are the recent-rain sources themselves? (7-day totals, same ward-days)
a = preds["imd_final"][["ward_id", "date", "rain_7d"]]
for name in [n for n in src if n != "imd_final"]:
    m = a.merge(preds[name][["ward_id", "date", "rain_7d"]], on=["ward_id", "date"], suffixes=("", "_x"))
    results[name]["rain_7d_corr_vs_imd_final"] = float(np.corrcoef(m.rain_7d, m.rain_7d_x)[0, 1])
    results[name]["rain_7d_ratio_vs_imd_final"] = float(m.rain_7d_x.sum() / max(m.rain_7d.sum(), 1e-9))
(REPORTS / "live_replay.json").write_text(json.dumps(results, indent=2, default=float))
print(json.dumps(results, indent=2, default=float))
