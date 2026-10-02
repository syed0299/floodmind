"""Assemble the ward × day training table for 2015–2025 (all months).

Time convention: IMD day D is the 24 h ending 08:30 IST on D. Flooding seen on calendar day
C overlaps IMD days C (the night before) and C+1 (the daytime of C), so a report dated C
marks both as positive.

Weights encode how much we trust a "no flood" label: on days when floods were reported
somewhere in the city, an unreported ward may simply have gone unreported, so it counts half.
"""
import numpy as np
import pandas as pd

from floodmind.config import INTERIM, PROCESSED

obs = pd.read_parquet(INTERIM / "rain_obs_daily.parquet").sort_values(["ward_id", "date"])
g = obs.groupby("ward_id")["rain_obs"]
obs["rain_d0"] = obs["rain_obs"]
obs["rain_dm1"] = g.shift(1)
for n in (3, 7, 30, 60):
    obs[f"rain_{n}d"] = g.transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum())

obs["season"] = obs["date"].dt.year
obs["doy_sin"] = np.sin(2 * np.pi * obs["date"].dt.dayofyear / 365.25)
obs["doy_cos"] = np.cos(2 * np.pi * obs["date"].dt.dayofyear / 365.25)
obs = obs.dropna(subset=["rain_dm1"]).copy()
city = obs.groupby("date")["rain_d0"].transform("mean")
obs["rain_d0_city"] = city
obs["rain_d0_cityrel"] = obs["rain_d0"] / (city + 1)

fc = pd.read_parquet(INTERIM / "rain_fc_daily.parquet")[["ward_id", "date", "fc_d0_day1",
                                                         "fc_d0_analysis"]]
df = obs.merge(fc, on=["ward_id", "date"], how="left")
df = df.merge(pd.read_parquet(PROCESSED / "ward_static.parquet").drop(columns=["lon", "lat"]),
              on="ward_id", how="left")

labels = pd.read_parquet(PROCESSED / "labels.parquet")  # ward_id, date (calendar), conf
lab = pd.concat([labels.assign(date=labels["date"] + pd.Timedelta(days=k)) for k in (0, 1)])
lab = lab.groupby(["ward_id", "date"])["conf"].max().rename("conf").reset_index()
df = df.merge(lab, on=["ward_id", "date"], how="left")
df["y"] = df["conf"].notna().astype(int)

citywide = set(pd.read_parquet(PROCESSED / "citywide_event_days.parquet")["date"])
event_day = (df.groupby("date")["y"].transform("max") == 1) | df["date"].isin(citywide)
df["w"] = np.where(df["y"] == 1, df["conf"].fillna(1.0), np.where(event_day, 0.5, 1.0))
df = df.drop(columns=["conf", "rain_obs"])

df.to_parquet(PROCESSED / "dataset.parquet", index=False)
print(f"{len(df):,} ward-days, {df.y.sum():,} positive, "
      f"{df.loc[df.y == 1, 'date'].nunique()} event days, seasons {sorted(df.season.unique())}")
print(df.groupby("season")["y"].agg(["sum", "mean"]).round(4).T.to_string())
