"""Stage 4: citizen reports and the live correction they drive.

Reports live in a local SQLite file. Each holds a ward, flooded or dry, an optional water
depth, a time, and a one-way hash of a random per-browser id (used only for rate limits).
No names, phone numbers or locations are stored.

The correction is the same Gaussian-field update that was evaluated on held-out floods
(floodmind/assimilate.py, length scale and variance from reports/live_eval.json): the latest
forecast is the prior, and each report shifts its ward and the wards around it.
"""
import datetime as dt
import hashlib
import json
import socket
import sqlite3
import threading

import geopandas as gpd
import numpy as np
import pandas as pd

from floodmind.alerts import IST, advisory, cap_xml
from floodmind.assimilate import LiveField, kernel
from floodmind.config import INTERIM, PROCESSED, REPORTS
from floodmind.live import LIVE

DB = LIVE / "reports.sqlite"
DEPTHS = {0: "dry", 10: "ankle-deep", 45: "knee-deep", 90: "waist-deep", 120: "above the waist"}
PER_WARD_WINDOW = dt.timedelta(hours=1)
PER_DEVICE_HOURLY = 30


class RateLimited(Exception):
    pass


def current_window(now: dt.datetime) -> str:
    """The IMD day in progress: the 24 h ending at the next 08:30 IST."""
    d = now.date() if now.time() < dt.time(8, 30) else now.date() + dt.timedelta(days=1)
    return d.isoformat()


def lan_url(port: int) -> str | None:
    """This machine's address on the local network (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address; connect() on UDP sends nothing
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else f"http://{ip}:{port}"
    except OSError:
        return None


class ReportStore:
    def __init__(self, path=DB):
        LIVE.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            window TEXT NOT NULL,
            ward_id INTEGER NOT NULL,
            flooded INTEGER NOT NULL,
            depth_cm INTEGER,
            device TEXT NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_reports_window ON reports(window)")
        self.db.commit()

    @staticmethod
    def _device_hash(device: str) -> str:
        return hashlib.sha256(("floodmind:" + device).encode()).hexdigest()[:16]

    def add(self, ward_id: int, flooded: bool, depth_cm: int | None, device: str, now: dt.datetime):
        dev = self._device_hash(device)
        since_ward = (now - PER_WARD_WINDOW).isoformat()
        since_hour = (now - dt.timedelta(hours=1)).isoformat()
        with self._lock:
            c = self.db.cursor()
            if c.execute("SELECT 1 FROM reports WHERE device=? AND ward_id=? AND created_at>?",
                         (dev, ward_id, since_ward)).fetchone():
                raise RateLimited("You already reported this ward in the last hour. Thank you!")
            n = c.execute("SELECT COUNT(*) FROM reports WHERE device=? AND created_at>?",
                          (dev, since_hour)).fetchone()[0]
            if n >= PER_DEVICE_HOURLY:
                raise RateLimited("Too many reports from this device in the last hour.")
            c.execute("INSERT INTO reports (created_at, window, ward_id, flooded, depth_cm, device) "
                      "VALUES (?,?,?,?,?,?)",
                      (now.isoformat(timespec="seconds"), current_window(now), ward_id,
                       int(flooded), depth_cm, dev))
            self.db.commit()

    def for_window(self, window: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id, created_at, ward_id, flooded, depth_cm FROM reports "
                                   "WHERE window=? ORDER BY id", (window,)).fetchall()
        return [{"id": r[0], "time": r[1], "ward_id": r[2], "flooded": bool(r[3]), "depth_cm": r[4]}
                for r in rows]

    def clear_window(self, window: str) -> int:
        with self._lock:
            n = self.db.execute("DELETE FROM reports WHERE window=?", (window,)).rowcount
            self.db.commit()
        return n


class Corrector:
    """Applies the window's reports to the latest forecast for that window."""

    def __init__(self):
        wards = gpd.read_file(INTERIM / "wards.gpkg").sort_values("ward_id").reset_index(drop=True)
        self.ids = wards["ward_id"].to_numpy()
        self.idx = {int(w): i for i, w in enumerate(self.ids)}
        cfg = json.loads((REPORTS / "live_eval.json").read_text())
        self.length_km, self.prior_var = cfg["length_km"], cfg["prior_var"]
        self.K = kernel(wards["lat"], wards["lon"], self.length_km, self.prior_var)
        static = pd.read_parquet(PROCESSED / "ward_static.parquet").set_index("ward_id")
        self.pop = static.reindex(self.ids)["pop"].fillna(0).to_numpy()
        gj = json.loads((PROCESSED / "web" / "wards.geojson").read_text())
        self.names = {f["properties"]["ward_id"]: f["properties"]["name"] for f in gj["features"]}
        self.rings = {}
        for f in gj["features"]:
            g = f["geometry"]
            ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
            self.rings[f["properties"]["ward_id"]] = [(lat, lon) for lon, lat in ring[:: max(1, len(ring) // 40)]]

    def prior(self, forecast: dict | None, window: str) -> tuple[np.ndarray, str | None]:
        if forecast:
            t = next((t for t in forecast["targets"] if t["date"] == window), forecast["targets"][0])
            m = dict(zip(t["ward_id"], t["p"]))
            return np.array([m.get(int(w), 5) / 100 for w in self.ids], float), t["date"]
        return np.full(len(self.ids), 0.05), None

    def apply(self, forecast: dict | None, reports: list[dict], window: str) -> dict:
        p0, used = self.prior(forecast, window)
        f = LiveField(np.clip(p0, 0.01, 0.99), self.K)
        for r in reports:
            # Deeper water is stronger evidence: halve the observation noise at knee depth or more.
            obs_var = 0.25 if r["flooded"] and (r["depth_cm"] or 0) >= 45 else 0.5
            f.observe(self.idx[r["ward_id"]], r["flooded"], obs_var=obs_var)
        scores = f.query_scores(self.pop)
        ask = [int(self.ids[j]) for j in np.argsort(-scores)[:3] if np.isfinite(scores[j])]
        # Advisories from the corrected map, so they match what the reports show.
        p_now = f.p
        top = [j for j in np.argsort(-p_now) if p_now[j] >= 0.30][:5]
        adv = [dict(ward=int(self.ids[j]), p=round(float(p_now[j]), 3),
                    **advisory(int(self.ids[j]), self.names.get(int(self.ids[j]), ""), float(p_now[j])))
               for j in top]
        cap = (cap_xml(adv[0]["ward"], self.names.get(adv[0]["ward"], ""), adv[0]["p"],
                       self.rings.get(adv[0]["ward"], []), issued=dt.datetime.now(IST)) if adv else None)
        return {
            "window": window,
            "forecast_target": used,
            "ward_id": [int(w) for w in self.ids],
            "p_prior": [int(round(v * 100)) for v in p0],
            "p_now": [int(round(v * 100)) for v in f.p],
            "reports": reports,
            "n_flooded": sum(r["flooded"] for r in reports),
            "n_dry": sum(not r["flooded"] for r in reports),
            "ask_next": ask,
            "advisories": adv,
            "cap": cap,
            "length_km": self.length_km,
        }
