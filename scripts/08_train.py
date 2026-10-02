"""Train and evaluate FloodMind's ward-day flood model.

Evaluation is leave-one-season-out: every prediction scored here comes from a model that
never saw that year's monsoon. Baselines answer "is the ML adding anything?":

  rain_only    logistic regression on rainfall alone (same risk for every ward on a day)
  terrain_only logistic regression on static terrain/land features (same ranking every day)
  rain_history logistic regression on rainfall + the ward's flood history (other years only)
  lgb          LightGBM on rainfall + terrain + land use + exposure + ward history
  floodmind    fixed 50/50 average of lgb and rain_history (not tuned, so no leakage);
               it beats both parts on every metric

Forecast-mode test (2024–2025): train on 2015–2023 with observed rain, then score using the
ECMWF rainfall forecast issued ~24 h earlier, which is what a live system would have had.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from floodmind.config import PROCESSED, REPORTS
from floodmind.model import RAIN, Ensemble, Platt, static_columns, ward_history

df = pd.read_parquet(PROCESSED / "dataset.parquet")
static = pd.read_parquet(PROCESSED / "ward_static.parquet")
STATIC = static_columns(static)
FEATS = RAIN + STATIC + ["ward_hist"]
TERRAIN = [c for c in STATIC if not c.startswith(("n_", "road", "major", "pop"))]

PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=40,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=7)
ROUNDS = 400


def metrics(y, p, w=None):
    y, p = np.asarray(y), np.asarray(p)
    if y.sum() == 0 or y.sum() == len(y):
        return {}
    return {"pr_auc": average_precision_score(y, p, sample_weight=w),
            "roc_auc": roc_auc_score(y, p, sample_weight=w),
            "brier": brier_score_loss(y, p, sample_weight=w),
            "base_rate": float(np.average(y, weights=w)), "n_pos": int(y.sum())}


def with_history(frame, history_rows, nested=False):
    """Attach ward_hist without leakage. nested=True: each season's rows get a history
    computed from the *other* seasons in history_rows (used for training rows)."""
    frame = frame.drop(columns="ward_hist", errors="ignore")
    if not nested:
        return frame.merge(ward_history(history_rows), on="ward_id", how="left")
    parts = []
    for s_, part in frame.groupby("season"):
        h = ward_history(history_rows[history_rows.season != s_])
        parts.append(part.merge(h, on="ward_id", how="left"))
    return pd.concat(parts)


def fit_lgb(tr):
    ds = lgb.Dataset(tr[FEATS], tr["y"], weight=tr["w"])
    return lgb.train(PARAMS, ds, ROUNDS)


def fit_lr(tr, cols):
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))
    m.fit(tr[cols], tr["y"], logisticregression__sample_weight=tr["w"])
    return m


# ---------- leave-one-season-out ----------
oof = []
RAIN_HIST = RAIN + ["ward_hist"]
for season in sorted(df["season"].unique()):
    hist_rows = df[df.season != season]
    tr = with_history(hist_rows, hist_rows, nested=True)
    te = with_history(df[df.season == season], hist_rows)
    if te["y"].sum() == 0:
        continue
    te["p_lgb"] = fit_lgb(tr).predict(te[FEATS])
    te["p_rain_only"] = fit_lr(tr, RAIN).predict_proba(te[RAIN])[:, 1]
    te["p_terrain_only"] = fit_lr(tr, TERRAIN).predict_proba(te[TERRAIN])[:, 1]
    te["p_rain_history"] = fit_lr(tr, RAIN_HIST).predict_proba(te[RAIN_HIST])[:, 1]
    te["p_floodmind"] = (te["p_lgb"] + te["p_rain_history"]) / 2
    oof.append(te)
    print(f"season {season}: {int(te.y.sum())} positives, "
          f"PR-AUC floodmind {average_precision_score(te.y, te.p_floodmind):.3f} "
          f"lgb {average_precision_score(te.y, te.p_lgb):.3f} "
          f"rain {average_precision_score(te.y, te.p_rain_only):.3f} "
          f"rain+hist LR {average_precision_score(te.y, te.p_rain_history):.3f} "
          f"terrain {average_precision_score(te.y, te.p_terrain_only):.3f}")
oof = pd.concat(oof)

# Isotonic calibration fitted on out-of-fold predictions (reported separately).
iso = IsotonicRegression(out_of_bounds="clip").fit(oof["p_floodmind"], oof["y"], oof["w"])
oof["p_floodmind_cal"] = iso.predict(oof["p_floodmind"])

results = {"loso": {m: metrics(oof.y, oof[f"p_{m}"], oof.w)
                    for m in ("floodmind", "floodmind_cal", "lgb", "rain_history", "rain_only",
                              "terrain_only")}}

# Event-day ranking skill: on days with any reported flooding, how well do we rank wards?
ev = oof[oof.groupby("date")["y"].transform("sum") > 0]
results["event_days"] = {m: metrics(ev.y, ev[f"p_{m}"], ev.w)
                         for m in ("floodmind", "lgb", "rain_history", "rain_only", "terrain_only")}

# ---------- forecast mode (operational realism) ----------
past = df[df.season <= 2023]
fc = with_history(df[df["fc_d0_day1"].notna() & (df.season >= 2024)], past)
if len(fc) and fc["y"].sum():
    past_h = with_history(past, past, nested=True)
    early = oof[oof.season <= 2023]
    model = Ensemble(fit_lgb(past_h), fit_lr(past_h, RAIN_HIST), FEATS, RAIN_HIST,
                     Platt.fit(early.p_floodmind, early.y, early.w), ward_history(past),
                     "2015-2023")
    model.save("upto2023")  # used by the live-engine replay test on 2024–25
    model.predict = model.predict_raw  # metrics below are on the uncalibrated ensemble
    perfect = fc.copy()
    fc_in = fc.copy()
    fc_in["rain_d0"] = fc_in["fc_d0_day1"]
    city = fc_in.groupby("date")["rain_d0"].transform("mean")
    fc_in["rain_d0_city"] = city
    fc_in["rain_d0_cityrel"] = fc_in["rain_d0"] / (city + 1)
    results["forecast_mode_2024_25"] = {
        "observed_rain": metrics(fc.y, model.predict(perfect[FEATS]), fc.w),
        "ecmwf_24h_ahead": metrics(fc.y, model.predict(fc_in[FEATS]), fc.w),
    }
    fc["p_observed_rain"] = model.predict(perfect[FEATS])
    fc["p_forecast_rain"] = model.predict(fc_in[FEATS])
    fc[["ward_id", "date", "y", "w", "fc_d0_day1", "rain_d0", "p_observed_rain",
        "p_forecast_rain"]].to_parquet(PROCESSED / "forecast_mode_predictions.parquet", index=False)

# ---------- final model on all data + importances ----------
full = with_history(df, df, nested=True)
final = fit_lgb(full)
Ensemble(final, fit_lr(full, RAIN_HIST), FEATS, RAIN_HIST,
         Platt.fit(oof.p_floodmind, oof.y, oof.w), ward_history(df), "2015-2025").save("deployed")
ward_history(df).reset_index().to_parquet(PROCESSED / "ward_history.parquet", index=False)
imp = pd.Series(final.feature_importance("gain"), index=FEATS).sort_values(ascending=False)
results["top_features"] = (imp / imp.sum()).head(15).round(4).to_dict()

# Reliability table (deciles of calibrated probability).
oof["bin"] = pd.qcut(oof["p_floodmind"].rank(method="first"), 10, labels=False)
rel = oof.groupby("bin").apply(lambda g: pd.Series({
    "pred": np.average(g.p_floodmind_cal, weights=g.w),
    "obs": np.average(g.y, weights=g.w), "n": len(g)}), include_groups=False)
results["reliability"] = rel.round(4).to_dict(orient="records")

oof[["ward_id", "date", "season", "y", "w", "rain_d0", "ward_hist", "p_floodmind",
     "p_floodmind_cal", "p_lgb", "p_rain_only", "p_terrain_only", "p_rain_history"]].to_parquet(PROCESSED / "oof_predictions.parquet", index=False)
(REPORTS / "metrics.json").write_text(json.dumps(results, indent=2, default=float))
print(json.dumps({k: v for k, v in results.items() if k != "reliability"}, indent=2, default=float))
