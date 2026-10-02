"""Loop 3: where does the city flood more than its rain and terrain explain?

1. A physics-only model (rainfall + terrain + land cover, no ward identity, no exposure
   proxies) is fit leave-one-season-out, so each prediction is out of sample.
2. Excess = observed flood-days minus expected, on days with >= 20 mm rain, as a z-score
   so wards with few rainy days are not over-ranked.
3. Reporting-bias check: central, well-covered wards may simply get reported more. We regress
   the excess on attention proxies (schools, hospitals, major roads, road density). If they
   explained much of it we would rank on the remainder; in practice R² is ~0.04, so we rank
   on the excess itself and report the check.
4. Trend: excess in 2015–2021 vs 2022–2025 (Chennai's large storm-drain programme ran
   2021–24), each measured relative to the city median for that period, because news
   coverage (and so Groundsource density) grew over time. A falling relative excess is
   consistent with drains working; it is not proof.
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from floodmind.config import PROCESSED, REPORTS

df = pd.read_parquet(PROCESSED / "dataset.parquet")
static = pd.read_parquet(PROCESSED / "ward_static.parquet")
RAIN = ["rain_d0", "rain_dm1", "rain_3d", "rain_7d", "rain_30d", "rain_60d",
        "rain_d0_city", "rain_d0_cityrel"]  # no day-of-year: it learned news seasonality and missed the Dec 2021 cloudburst
PHYS = [c for c in static.columns if c.startswith(("elev", "hand", "frac_", "sink", "slope",
                                                    "twi", "facc", "lc_", "dist_", "lake"))]
FEATS = RAIN + PHYS
PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=40,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=11)

parts = []
for s in sorted(df.season.unique()):
    tr, te = df[df.season != s], df[df.season == s].copy()
    m = lgb.train(PARAMS, lgb.Dataset(tr[FEATS], tr.y, weight=tr.w), 300)
    te["p_phys"] = m.predict(te[FEATS])
    parts.append(te[["ward_id", "date", "season", "y", "w", "rain_d0", "p_phys"]])
phys = pd.concat(parts)
phys.to_parquet(PROCESSED / "oof_physics_only.parquet", index=False)

wet = phys[phys.rain_d0 >= 20]


def excess(rows):
    g = rows.assign(r=rows.y - rows.p_phys, v=rows.p_phys * (1 - rows.p_phys))
    a = g.groupby("ward_id").agg(obs=("y", "sum"), exp=("p_phys", "sum"), var=("v", "sum"),
                                 days=("y", "size"))
    a["excess_rate"] = (a.obs - a.exp) / a.days
    a["z"] = (a.obs - a.exp) / np.sqrt(a["var"] + 1.0)
    return a


allp = excess(wet)
early = excess(wet[wet.season <= 2021])[["excess_rate"]].rename(columns={"excess_rate": "excess_2015_21"})
late = excess(wet[wet.season >= 2022])[["excess_rate"]].rename(columns={"excess_rate": "excess_2022_25"})
out = allp.join(early).join(late).reset_index()
for c in ("excess_2015_21", "excess_2022_25"):
    out[c] = out[c] - out[c].median()  # relative to the city in that period

att_cols = [c for c in ("n_schools", "n_hospitals", "major_road_km", "road_density") if c in static]
X = static.set_index("ward_id").reindex(out.ward_id)[att_cols].fillna(0).to_numpy()
reg = LinearRegression().fit(X, out["z"])
out["z_attention"] = reg.predict(X)
attention_r2 = float(reg.score(X, out["z"]))
out["deficit_score"] = out["z"] if attention_r2 < 0.2 else out["z"] - out["z_attention"]
out["trend"] = out["excess_2022_25"] - out["excess_2015_21"]
out["rank"] = out["deficit_score"].rank(ascending=False).astype(int)
out = out.sort_values("rank")
out.to_parquet(PROCESSED / "drain_deficit.parquet", index=False)

summary = {
    "wet_days_per_ward": int(out.days.median()),
    "attention_r2": attention_r2,
    "wards_improved": int((out.trend < -0.03).sum()),
    "wards_worsened": int((out.trend > 0.03).sum()),
    "top10": out.head(10)[["ward_id", "deficit_score", "excess_rate", "trend"]].round(3)
               .to_dict(orient="records"),
}
(REPORTS / "drain_deficit.json").write_text(pd.Series(summary).to_json(indent=2))
print(f"attention proxies explain R²={summary['attention_r2']:.2f} of raw excess")
print(f"improved: {summary['wards_improved']}, worsened: {summary['wards_worsened']}")
print(out.head(12)[["ward_id", "rank", "deficit_score", "z", "z_attention", "excess_rate",
                    "excess_2015_21", "excess_2022_25"]].round(3).to_string(index=False))
