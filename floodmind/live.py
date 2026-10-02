"""Stage 2: the live forecast engine.

    python -m floodmind.live          # issue a forecast now

1. Recent rain (the last 60 days the model needs): IMD's real-time 0.25° grid, the same
   gauge-based family the model was trained on. Days IMD has not published yet are filled
   from ECMWF's short-range estimate, and the output says which days those were.
2. Coming rain: the latest ECMWF IFS 0.25° run via Open-Meteo, for the two IMD days ahead.
3. The same features as training -> the deployed model -> calibrated flood chance per ward.
4. Writes data/live/latest.json, a timestamped copy, and appends to data/live/forecast_log.csv.

`forecast()` takes its inputs as plain tables, so scripts/13_live_replay.py can run the
exact same feature and model code on archived 2024–25 inputs.
"""
import argparse
import datetime as dt
import json

import geopandas as gpd
import numpy as np
import pandas as pd

from floodmind.alerts import IST, advisory, cap_xml
from floodmind.config import DATA, INTERIM, PROCESSED
from floodmind.model import Ensemble
from floodmind.rain import ecmwf_live, imd_realtime, points_to_wards

LIVE = DATA / "live"
HISTORY_DAYS = 60
ADVISE_AT = 0.30  # advisories for wards at or above this chance


def build_features(target: pd.Timestamp, past: pd.DataFrame, target_rain: pd.DataFrame,
                   static: pd.DataFrame) -> pd.DataFrame:
    """Features for IMD day `target`, exactly as in scripts/07_dataset.py.

    past: ward_id, date, rain for the days before target (any source).
    target_rain: ward_id, rain for the target day (the forecast).
    """
    piv = past.pivot_table(index="date", columns="ward_id", values="rain")
    piv = piv.reindex(pd.date_range(target - pd.Timedelta(days=HISTORY_DAYS), target - pd.Timedelta(days=1)))
    f = pd.DataFrame({"ward_id": piv.columns})
    f["rain_dm1"] = piv.iloc[-1].to_numpy()
    for n in (3, 7, 30, 60):
        f[f"rain_{n}d"] = piv.iloc[-n:].sum(min_count=1).to_numpy()
    f = f.merge(target_rain[["ward_id", "rain"]].rename(columns={"rain": "rain_d0"}), on="ward_id")
    city = f["rain_d0"].mean()
    f["rain_d0_city"] = city
    f["rain_d0_cityrel"] = f["rain_d0"] / (city + 1)
    return f.merge(static.drop(columns=["lon", "lat"]), on="ward_id", how="left")


def forecast(targets, past, target_rain, model: Ensemble, static) -> dict[pd.Timestamp, pd.DataFrame]:
    """Flood chance per ward for each target IMD day. Later targets use earlier targets'
    forecast rain as their recent rain."""
    out, past = {}, past.copy()
    for t in sorted(targets):
        tr = target_rain[target_rain.date == t]
        X = model.attach_history(build_features(t, past[past.date < t], tr, static))
        X["p"] = model.predict(X)
        out[t] = X
        past = pd.concat([past[past.date != t], tr[["ward_id", "date", "rain"]]])
    return out


def target_days(now: dt.datetime) -> list[pd.Timestamp]:
    """The IMD day in progress (ends 08:30 next) and the one after it."""
    first = now.date() if now.time() < dt.time(8, 30) else now.date() + dt.timedelta(days=1)
    return [pd.Timestamp(first), pd.Timestamp(first + dt.timedelta(days=1))]


def _window(t: pd.Timestamp) -> str:
    s = t - pd.Timedelta(days=1)
    return f"08:30 {s:%-d %b} → 08:30 {t:%-d %b} IST"


def run(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(IST)
    targets = target_days(now)
    static = pd.read_parquet(PROCESSED / "ward_static.parquet")
    wards = gpd.read_file(INTERIM / "wards.gpkg")
    model = Ensemble.load("deployed")

    # Recent rain: IMD real-time first, ECMWF for any day IMD has not published.
    start = targets[0] - pd.Timedelta(days=HISTORY_DAYS + 1)
    imd_rt = imd_realtime(start.date(), targets[0].date())
    ec = points_to_wards(ecmwf_live(past_days=HISTORY_DAYS + 1, forecast_days=3), wards)
    need = pd.date_range(start, targets[0] - pd.Timedelta(days=1))
    imd_days = set(imd_rt["date"]) if len(imd_rt) else set()
    fallback = [d for d in need if d not in imd_days]
    past = pd.concat([imd_rt[imd_rt.date.isin(need)],
                      ec[ec.date.isin(fallback)][["ward_id", "date", "rain"]]])
    target_rain = ec[ec.date.isin(targets)]
    missing = [t for t in targets if target_rain[target_rain.date == t]["rain"].isna().any()]
    if missing:
        raise RuntimeError(f"ECMWF forecast incomplete for {missing}; try again later")

    res = forecast(targets, past, target_rain, model, static)

    # City-mean rain for the last 14 days and the days ahead, for the dashboard's rain strip.
    recent = past[past.date >= targets[0] - pd.Timedelta(days=14)].groupby("date")["rain"].mean()
    recent_rain = [{"date": d.strftime("%Y-%m-%d"), "mm": round(float(v), 1),
                    "source": "ecmwf" if d in fallback else "imd"} for d, v in recent.items()]
    recent_rain += [{"date": t.strftime("%Y-%m-%d"), "mm": round(float(X.rain_d0.mean()), 1),
                     "source": "forecast"} for t, X in res.items()]

    names = {}
    web = PROCESSED / "web" / "wards.geojson"
    polys = {}
    if web.exists():
        gj = json.loads(web.read_text())
        names = {f["properties"]["ward_id"]: f["properties"]["name"] for f in gj["features"]}
        polys = {f["properties"]["ward_id"]: f["geometry"] for f in gj["features"]}
    pop = static.set_index("ward_id")["pop"] if "pop" in static else None

    out = {
        "issued_at": now.isoformat(timespec="minutes"),
        "model": {"name": "deployed", "trained_on": model.trained_on},
        "inputs": {
            "recent_rain": "IMD real-time 0.25° gridded rainfall",
            "imd_days_used": int(len(need) - len(fallback)),
            "ecmwf_fallback_days": [d.strftime("%Y-%m-%d") for d in fallback],
            "forecast_rain": "ECMWF IFS 0.25° (Open-Meteo), latest run",
        },
        "recent_rain": recent_rain,
        "targets": [],
    }
    log_rows = []
    for t, X in res.items():
        X = X.sort_values("ward_id")
        p = X["p"].to_numpy()
        high = X[X.p >= 0.55]
        top = X.sort_values("p", ascending=False)
        adv = [dict(ward=int(r.ward_id), p=round(float(r.p), 3),
                    **advisory(int(r.ward_id), names.get(int(r.ward_id), ""), float(r.p)))
               for r in top.itertuples() if r.p >= ADVISE_AT][:5]
        cap = None
        if adv:
            w0 = adv[0]["ward"]
            g = polys.get(w0)
            ring = (g["coordinates"][0] if g and g["type"] == "Polygon" else
                    g["coordinates"][0][0] if g else [])
            cap = cap_xml(w0, names.get(w0, ""), adv[0]["p"],
                          [(lat, lon) for lon, lat in ring[:: max(1, len(ring) // 40)]], issued=now)
        out["targets"].append({
            "date": t.strftime("%Y-%m-%d"),
            "window": _window(t),
            "rain_city_mm": round(float(X.rain_d0.mean()), 1),
            "rain_max_mm": round(float(X.rain_d0.max()), 1),
            "ward_id": X.ward_id.astype(int).tolist(),
            "p": [int(round(v * 100)) for v in p],
            "rain": [round(float(v), 1) for v in X.rain_d0],
            "rain_7d": [round(float(v), 1) for v in X.rain_7d],
            "summary": {
                "wards_high": int(len(high)),
                "wards_elevated": int(((X.p >= 0.30) & (X.p < 0.55)).sum()),
                "people_high": int(pop.reindex(high.ward_id).sum()) if pop is not None else None,
                "mean_chance": round(float(p.mean()), 3),
            },
            "advisories": adv,
            "cap": cap,
        })
        log_rows.append(pd.DataFrame({"issued_at": out["issued_at"], "target_date": out["targets"][-1]["date"],
                                      "ward_id": X.ward_id.astype(int), "p": np.round(p, 4),
                                      "rain_fc": np.round(X.rain_d0, 2), "rain_7d": np.round(X.rain_7d, 2)}))

    (LIVE / "forecasts").mkdir(parents=True, exist_ok=True)
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (LIVE / "latest.json").write_text(blob)
    (LIVE / "forecasts" / f"forecast_{now:%Y%m%dT%H%M}.json").write_text(blob)
    log = LIVE / "forecast_log.csv"
    pd.concat(log_rows).to_csv(log, mode="a", header=not log.exists(), index=False)
    return out


def main():
    ap = argparse.ArgumentParser(description="Issue a FloodMind forecast for Chennai's 200 wards.")
    ap.parse_args()
    out = run()
    print(f"issued {out['issued_at']} · recent rain: {out['inputs']['imd_days_used']} IMD days, "
          f"ECMWF fallback for {out['inputs']['ecmwf_fallback_days'] or 'none'}")
    for t in out["targets"]:
        s = t["summary"]
        print(f"  {t['window']}: city rain {t['rain_city_mm']} mm (max {t['rain_max_mm']}), "
              f"mean chance {s['mean_chance']:.0%}, {s['wards_high']} wards ≥55%, "
              f"{s['wards_elevated']} wards 30–55%")
        for a in t["advisories"][:3]:
            print("   ", a["en"])


if __name__ == "__main__":
    main()
