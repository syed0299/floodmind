"""Accuracy in plain words, from the held-out predictions (nothing here was seen in training).

Two settings:
  hindsight  leave-one-year-out predictions 2015–2025 with the rain that actually fell
  live       2024–25 with the ECMWF rain forecast issued ~24 h earlier and a model trained
             on 2015–2023 only: what the live system would really have said

Questions answered:
  * When FloodMind says a ward is at >=55% (or >=30%), how often was flooding reported there?
  * Of the ward-days where flooding was reported, how many had it flagged?
  * Does a forecast of about X% come true about X% of the time? (calibration)
  * City level: on days when 10+ wards flooded, did it flag anything? On days it flagged
    something, did the city actually flood?
"""
import json

import numpy as np
import pandas as pd

from floodmind.config import PROCESSED, REPORTS
from floodmind.model import Ensemble

oof = pd.read_parquet(PROCESSED / "oof_predictions.parquet")
fm = pd.read_parquet(PROCESSED / "forecast_mode_predictions.parquet")
sets = {
    # Platt calibration fitted on all out-of-fold predictions (2 parameters).
    "hindsight": oof.assign(p=Ensemble.load("deployed").platt(oof.p_floodmind))[["ward_id", "date", "y", "p"]],
    # Calibration fitted on 2015–2023 only, so 2024–25 stay fully unseen.
    "live": fm.assign(p=Ensemble.load("upto2023").platt(fm.p_forecast_rain))[["ward_id", "date", "y", "p"]],
}


def ward_level(d, thr):
    flag = d.p >= thr
    return {"threshold": thr,
            "flagged_ward_days": int(flag.sum()),
            "precision": float(d.y[flag].mean()) if flag.any() else None,   # flagged -> flooded
            "recall": float(flag[d.y == 1].mean())}                         # flooded -> flagged


def calibration(d):
    bins = [0, 0.05, 0.15, 0.3, 0.5, 0.7, 1.0]
    d = d.assign(b=pd.cut(d.p, bins, include_lowest=True))
    g = d.groupby("b", observed=True).agg(said=("p", "mean"), happened=("y", "mean"), n=("y", "size"))
    return [{"said": round(r.said, 3), "happened": round(r.happened, 3), "n": int(r.n)} for r in g.itertuples()]


def city_level(d, thr=0.55, flood_wards=10):
    day = d.groupby("date").agg(flooded=("y", "sum"), top=("p", "max"))
    flood_day, flagged = day.flooded >= flood_wards, day.top >= thr
    return {"flood_days": int(flood_day.sum()), "days": int(len(day)),
            "flood_days_flagged": float(flagged[flood_day].mean()),          # hit rate
            "flagged_days_that_flooded": float(flood_day[flagged].mean()) if flagged.any() else None,
            "flagged_days_with_any_flooding": float((day.flooded[flagged] > 0).mean()) if flagged.any() else None,
            "quiet_days_flagged": float(flagged[day.flooded == 0].mean())}  # false alarms on dry days


out = {}
for name, d in sets.items():
    out[name] = {"ward_days": int(len(d)), "flooded_ward_days": int(d.y.sum()),
                 "ward_55": ward_level(d, 0.55), "ward_30": ward_level(d, 0.30),
                 "calibration": calibration(d), "city": city_level(d),
                 "city_grid": {f"{fw}+ wards, flag at {thr:.0%}": city_level(d, thr, fw)
                               for fw in (10, 50) for thr in (0.30, 0.55)}}
(REPORTS / "accuracy_plain.json").write_text(json.dumps(out, indent=2, default=float))

for name, r in out.items():
    print(f"\n== {name}: {r['ward_days']:,} ward-days, {r['flooded_ward_days']:,} flooded")
    for k in ("ward_55", "ward_30"):
        w = r[k]
        print(f"  ward flagged at >= {w['threshold']:.0%}: {w['flagged_ward_days']:,} ward-days; "
              f"flooding reported in {w['precision']:.0%} of them; caught {w['recall']:.0%} of all flooded ward-days")
    c = r["city"]
    print(f"  city: {c['flood_days']} days with 10+ flooded wards; flagged (any ward >= 55%) on {c['flood_days_flagged']:.0%} of them; "
          f"of flagged days {c['flagged_days_that_flooded']:.0%} had 10+ flooded wards and "
          f"{c['flagged_days_with_any_flooding']:.0%} had some flooding; dry days flagged: {c['quiet_days_flagged']:.1%}")
    for k, c in r["city_grid"].items():
        print(f"    {k}: {c['flood_days']} flood days, caught {c['flood_days_flagged']:.0%}; "
              f"flagged days that flooded {c['flagged_days_that_flooded']:.0%}; dry days flagged {c['quiet_days_flagged']:.1%}")
    print("  calibration (said -> happened, n):", ", ".join(f"{b['said']:.0%}->{b['happened']:.0%} ({b['n']:,})" for b in r["calibration"]))
