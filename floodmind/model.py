"""FloodMind's forecast model, shared by training, the dashboard export and the live engine.

FloodMind = a fixed 50/50 average of LightGBM (all features) and a logistic regression on
rainfall + the ward's flood history, then Platt calibration. A saved bundle holds everything
needed to predict, so the live engine and the replay test run exactly the same model.
"""
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from floodmind.config import PROCESSED

# No day-of-year features: they learned news seasonality and missed the Dec 2021 cloudburst.
RAIN = ["rain_d0", "rain_dm1", "rain_3d", "rain_7d", "rain_30d", "rain_60d",
        "rain_d0_city", "rain_d0_cityrel"]


def static_columns(static: pd.DataFrame) -> list[str]:
    return [c for c in static.columns if c not in ("ward_id", "lon", "lat")]


def ward_history(rows: pd.DataFrame, k: float = 20.0) -> pd.Series:
    """Each ward's flood rate on city flood days, shrunk toward the city mean (k pseudo-days)."""
    ev = rows[rows.groupby("date")["y"].transform("max") == 1]
    g = ev.groupby("ward_id")["y"].agg(["sum", "count"])
    m = g["sum"].sum() / max(g["count"].sum(), 1)
    return ((g["sum"] + k * m) / (g["count"] + k)).rename("ward_hist")


class Platt:
    """Logistic calibration on the logit. Strictly monotone, so ward rankings survive it."""

    def __init__(self, a: float = 1.0, b: float = 0.0):
        self.a, self.b = a, b

    @staticmethod
    def _z(p):
        p = np.clip(np.asarray(p, float), 1e-5, 1 - 1e-5)
        return np.log(p / (1 - p))

    @classmethod
    def fit(cls, p, y, w=None):
        m = LogisticRegression(C=1e6).fit(cls._z(p).reshape(-1, 1), y, sample_weight=w)
        return cls(float(m.coef_[0, 0]), float(m.intercept_[0]))

    def __call__(self, p):
        return 1 / (1 + np.exp(-(self.a * self._z(p) + self.b)))


class Ensemble:
    def __init__(self, gbm, lr, feats, feats_lr, platt: Platt, history: pd.Series, trained_on: str):
        self.gbm, self.lr = gbm, lr
        self.feats, self.feats_lr = feats, feats_lr
        self.platt, self.history, self.trained_on = platt, history, trained_on

    def predict_raw(self, X: pd.DataFrame) -> np.ndarray:
        return (self.gbm.predict(X[self.feats]) + self.lr.predict_proba(X[self.feats_lr])[:, 1]) / 2

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.platt(self.predict_raw(X))

    def attach_history(self, X: pd.DataFrame) -> pd.DataFrame:
        return X.drop(columns="ward_hist", errors="ignore").merge(self.history, on="ward_id", how="left")

    def save(self, name: str):
        joblib.dump(self, PROCESSED / f"model_{name}.joblib")

    @staticmethod
    def load(name: str) -> "Ensemble":
        return joblib.load(PROCESSED / f"model_{name}.joblib")
