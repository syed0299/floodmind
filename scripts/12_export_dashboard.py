"""Bundle everything the dashboard shows into one JSON blob and inject it into the page.

All probabilities shown are out-of-sample: leave-one-season-out predictions for observed
rain, and a model trained on 2015–2023 for the 2024–25 forecast-mode runs. Both are mapped
through a Platt calibration (logistic on the logit) fitted on the out-of-fold predictions;
unlike isotonic steps it is strictly monotone, so ward rankings survive calibration.
"""
import json

import numpy as np
import pandas as pd

from floodmind.alerts import advisory, cap_xml
from floodmind.assimilate import LiveField, kernel
from floodmind.config import DATA, PROCESSED, REPORTS, ROOT
from floodmind.model import Ensemble

WEB = PROCESSED / "web"
EVENTS = [
    ("dec2015", "December 2015 deluge", "2015-11-29", "2015-12-05"),
    ("nov2021", "November 2021 rains", "2021-11-05", "2021-11-13"),
    ("dec2021", "Dec 30, 2021 cloudburst", "2021-12-29", "2022-01-01"),
    ("michaung2023", "Cyclone Michaung", "2023-12-02", "2023-12-07"),
    ("oct2024", "October 2024 red alert", "2024-10-13", "2024-10-18"),
    ("fengal2024", "Cyclone Fengal", "2024-11-28", "2024-12-03"),
    ("ditwah2025", "Cyclone Ditwah", "2025-11-28", "2025-12-05"),
]
STEPS = 8

oof = pd.read_parquet(PROCESSED / "oof_predictions.parquet")
fm = pd.read_parquet(PROCESSED / "forecast_mode_predictions.parquet")
deficit = pd.read_parquet(PROCESSED / "drain_deficit.parquet")
static = pd.read_parquet(PROCESSED / "ward_static.parquet").sort_values("ward_id")
wards_geo = json.loads((WEB / "wards.geojson").read_text())
live_cfg = json.loads((REPORTS / "live_eval.json").read_text())

calibrate = Ensemble.load("deployed").platt  # Platt fitted on all out-of-fold predictions
ward_ids = static.ward_id.to_numpy()
idx = {w: i for i, w in enumerate(ward_ids)}
names = {f["properties"]["ward_id"]: f["properties"]["name"] for f in wards_geo["features"]}
polys = {f["properties"]["ward_id"]: f["geometry"] for f in wards_geo["features"]}
pop = static["pop"].fillna(0).to_numpy() if "pop" in static else static.road_km.to_numpy()
K = kernel(static.lat, static.lon, live_cfg["length_km"], live_cfg["prior_var"])
rng = np.random.default_rng(42)


def arr(series, scale=100):
    s = series.reindex(ward_ids)
    return [None if pd.isna(v) else int(round(float(v) * scale)) for v in s]


def replay(p0, y, mode):
    """Probabilities after each of STEPS observations (passive citizen posts or active asks)."""
    f = LiveField(p0, K)
    steps = []
    order = rng.permutation(np.flatnonzero(y == 1)) if mode == "reports" else None
    for k in range(STEPS):
        if mode == "reports":
            if k >= len(order):
                break
            j, ans = int(order[k]), True
        else:
            j = f.next_query(pop)
            ans = bool(y[j])
        f.observe(j, ans)
        steps.append({"ward": int(ward_ids[j]), "flooded": ans,
                      "p": [int(round(v * 100)) for v in calibrate(f.p)]})
    nxt = f.query_scores(pop)
    top_next = [int(ward_ids[j]) for j in np.argsort(-nxt)[:3]]
    return steps, top_next


def outline(wid):
    g = polys[wid]
    ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
    return [(lat, lon) for lon, lat in ring[:: max(1, len(ring) // 40)]]


events = []
for key, title, a, b in EVENTS:
    days = []
    for d in pd.date_range(a, b):
        o = oof[oof.date == d].set_index("ward_id")
        if o.empty:
            continue
        p_obs = pd.Series(calibrate(o.p_floodmind), index=o.index)
        y = o.y.reindex(ward_ids).fillna(0).astype(int).to_numpy()
        f = fm[fm.date == d].set_index("ward_id")
        day = {"date": d.strftime("%Y-%m-%d"), "rain_city": round(float(o.rain_d0.mean()), 1),
               "p_obs": arr(p_obs), "y": [int(v) for v in y],
               "rain": arr(o.rain_d0, 1), "n_flooded": int(y.sum())}
        if not f.empty:
            day["p_fc"] = arr(pd.Series(calibrate(f.p_forecast_rain), index=f.index))
            day["rain_fc_city"] = round(float(f.fc_d0_day1.mean()), 1)
        # Live replays start from the forecast prior when one exists (that is the live case).
        prior = np.array(day.get("p_fc") or day["p_obs"], float) / 100
        prior = np.clip(prior, 0.01, 0.99)
        if y.sum() >= 3:
            day["replay_reports"], day["next_after_reports"] = replay(prior, y, "reports")
            day["replay_asks"], day["next_after_asks"] = replay(prior, y, "asks")
        top = np.argsort(-prior)[:5]
        day["advisories"] = [dict(ward=int(ward_ids[j]), **advisory(int(ward_ids[j]),
                                  names.get(int(ward_ids[j]), ""), float(prior[j]))) for j in top]
        j0 = int(ward_ids[top[0]])
        day["cap"] = cap_xml(j0, names.get(j0, ""), float(prior[top[0]]), outline(j0),
                             issued=pd.Timestamp(d - pd.Timedelta(days=1)).to_pydatetime()
                             .replace(hour=8, minute=30, tzinfo=None).astimezone())
        days.append(day)
    events.append({"key": key, "title": title, "days": days,
                   "has_forecast": any("p_fc" in d for d in days)})
    print(f"{key}: {len(days)} days")

dfc = deficit.set_index("ward_id")
data = {
    "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
    "wards": wards_geo,
    "waterways": json.loads((WEB / "waterways.geojson").read_text()),
    "lakes": json.loads((WEB / "lakes.geojson").read_text()),
    "events": events,
    "deficit": {int(w): {"score": round(float(r.deficit_score), 2), "rank": int(r["rank"]),
                         "excess": round(float(r.excess_rate), 3),
                         "trend": None if pd.isna(r.trend) else round(float(r.trend), 3)}
                for w, r in dfc.iterrows()},
    "metrics": json.loads((REPORTS / "metrics.json").read_text()),
    "liveEval": live_cfg,
    "liveReplay": json.loads((REPORTS / "live_replay.json").read_text())
                  if (REPORTS / "live_replay.json").exists() else None,
    "deficit_summary": json.loads((REPORTS / "drain_deficit.json").read_text()),
    "wardHist": {int(w): round(float(v), 3) for w, v in
                 pd.read_parquet(PROCESSED / "ward_history.parquet").set_index("ward_id")["ward_hist"].items()},
    # Last live forecast at build time: what the page shows when no server is reachable.
    "now": json.loads((DATA / "live" / "latest.json").read_text())
           if (DATA / "live" / "latest.json").exists() else None,
}
blob = json.dumps(data, separators=(",", ":"))
(WEB / "floodmind_data.json").write_text(blob)

tpl = (ROOT / "dashboard" / "template.html").read_text()
out = tpl.replace("/*__FLOODMIND_DATA__*/", f"window.FLOODMIND = {blob};")
# artifact.html: page body only (the artifact host adds the document skeleton).
# index.html: complete document for opening locally / offline at the venue.
(ROOT / "dashboard" / "artifact.html").write_text(out)
(ROOT / "dashboard" / "index.html").write_text(
    '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n' + out + "\n</html>\n")
print(f"dashboard data {len(blob) / 1024:.0f} KB → dashboard/index.html, dashboard/artifact.html")
