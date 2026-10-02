"""Does live correction help? Replays held-out flood days.

Prior = out-of-fold FloodMind probabilities (the model never saw that year). Three ways to
get k observations on each flood day, scored only on wards that were NOT observed:

  passive  k citizens in truly flooded wards post "flooded here" (how social media behaves)
  random   k randomly chosen wards are asked and answer truthfully (flooded / dry)
  active   FloodMind chooses which ward to ask next (population x uncertainty), k times

Kernel length scale and prior variance are tuned on 2015–2020 and reported on 2021–2025.
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from floodmind.assimilate import LiveField, kernel
from floodmind.config import INTERIM, PROCESSED, REPORTS

oof = pd.read_parquet(PROCESSED / "oof_predictions.parquet")
wards = gpd.read_file(INTERIM / "wards.gpkg").sort_values("ward_id").reset_index(drop=True)
static = pd.read_parquet(PROCESSED / "ward_static.parquet").set_index("ward_id")
pop = static.reindex(wards.ward_id)["pop"].to_numpy() if "pop" in static else \
    static.reindex(wards.ward_id)["road_km"].to_numpy()  # road length as exposure proxy
idx = {w: i for i, w in enumerate(wards.ward_id)}

days = oof.groupby("date")["y"].sum()
days = days[days >= 10].index  # substantial flood days
rng = np.random.default_rng(0)


PRIOR = {"frame": oof, "col": "p_floodmind"}


def day_arrays(d):
    src = PRIOR["frame"]
    g = src[src.date == d].set_index("ward_id").reindex(wards.ward_id)
    return g[PRIOR["col"]].to_numpy(), g["y"].fillna(0).to_numpy().astype(int)


def score(p, y, mask):
    yy, pp = y[mask], p[mask]
    if yy.sum() == 0 or yy.sum() == len(yy):
        return np.nan, np.nan, np.nan
    return average_precision_score(yy, pp), roc_auc_score(yy, pp), float(np.mean((pp - yy) ** 2))


def run_day(d, K, k, strategy):
    p0, y = day_arrays(d)
    f = LiveField(p0, K)
    if strategy == "passive":
        pos = np.flatnonzero(y == 1)
        for j in rng.choice(pos, size=min(k, len(pos) - 1), replace=False):
            f.observe(j, True)
    elif strategy == "random":
        for j in rng.choice(len(y), size=k, replace=False):
            f.observe(j, bool(y[j]))
    elif strategy == "active":
        for _ in range(k):
            j = f.next_query(pop)
            f.observe(j, bool(y[j]))
    mask = np.ones(len(y), bool)
    mask[[j for j, _ in f.observed]] = False
    return score(p0, y, mask), score(f.p, y, mask)


def evaluate(day_list, length_km, prior_var, k, strategy):
    K = kernel(wards.lat, wards.lon, length_km, prior_var)
    rows = [run_day(d, K, k, strategy) for d in day_list]
    before = tuple(np.nanmean([r[0][i] for r in rows]) for i in range(3))
    after = tuple(np.nanmean([r[1][i] for r in rows]) for i in range(3))
    return before, after


tune = [d for d in days if d.year <= 2020]
test = [d for d in days if d.year >= 2021]
print(f"flood days: {len(tune)} tuning (2015–20), {len(test)} test (2021–25)")

best = None
for L in (1.0, 2.0, 3.0, 5.0):
    for v in (1.0, 2.0, 4.0):
        _, after = evaluate(tune, L, v, 5, "passive")
        if best is None or after[0] > best[0]:
            best = (after[0], L, v)
_, L, V = best
print(f"tuned: length scale {L} km, prior variance {V}")

results = {"length_km": L, "prior_var": V, "n_test_days": len(test), "by_k": {}}
for k in (3, 5, 10, 20):
    res = {}
    for strat in ("passive", "random", "active"):
        before, after = evaluate(test, L, V, k, strat)
        res[strat] = {"pr_auc_before": before[0], "pr_auc_after": after[0],
                      "roc_before": before[1], "roc_after": after[1],
                      "brier_before": before[2], "brier_after": after[2]}
    results["by_k"][k] = res
    print(f"k={k:>2}: " + " | ".join(
        f"{s} PR-AUC {r['pr_auc_before']:.3f}→{r['pr_auc_after']:.3f}" for s, r in res.items()))

# Starting from what a live system would have had: the 24 h-ahead forecast (2024–25).
fm = pd.read_parquet(PROCESSED / "forecast_mode_predictions.parquet")
PRIOR.update(frame=fm, col="p_forecast_rain")
fc_days = [d for d, n in fm.groupby("date")["y"].sum().items() if n >= 10]
results["forecast_prior"] = {"n_days": len(fc_days), "by_k": {}}
for k in (5, 10):
    res = {}
    for strat in ("passive", "active", "random"):
        before, after = evaluate(fc_days, L, V, k, strat)
        res[strat] = {"pr_auc_before": before[0], "pr_auc_after": after[0],
                      "roc_before": before[1], "roc_after": after[1],
                      "brier_before": before[2], "brier_after": after[2]}
    results["forecast_prior"]["by_k"][k] = res
    print(f"forecast prior, k={k}: " + " | ".join(
        f"{s} PR {r['pr_auc_before']:.3f}→{r['pr_auc_after']:.3f} Brier {r['brier_before']:.3f}→{r['brier_after']:.3f}"
        for s, r in res.items()))

(REPORTS / "live_eval.json").write_text(json.dumps(results, indent=2, default=float))
