"""Pre-flight check before a demo.

    python -m floodmind.preflight

Checks everything the live demo depends on and prints one line per check with what to do
if it fails. It changes nothing.
"""
import datetime as dt
import json
import socket

import requests

from floodmind.alerts import IST
from floodmind.config import PROCESSED, ROOT
from floodmind.live import LIVE
from floodmind.reports import ReportStore, current_window, lan_url

OK, WARN, FAIL = "ok  ", "WARN", "FAIL"
results = []


def check(status, what, fix=""):
    results.append(status)
    print(f"[{status}] {what}" + (f"\n        → {fix}" if fix and status != OK else ""))


def main(port=8791):
    now = dt.datetime.now(IST)
    print(f"FloodMind pre-flight · {now:%d %b %Y %H:%M} IST\n")

    for f in ("model_deployed.joblib", "ward_static.parquet", "ward_history.parquet", "web/wards.geojson"):
        p = PROCESSED / f
        check(OK if p.exists() else FAIL, f"model file {f}", "run ./run_all.sh")
    for f in ("index.html", "report.html"):
        p = ROOT / "dashboard" / f
        check(OK if p.exists() else FAIL, f"dashboard/{f}", "run scripts/12_export_dashboard.py")

    latest = LIVE / "latest.json"
    if latest.exists():
        fc = json.loads(latest.read_text())
        age_h = (now - dt.datetime.fromisoformat(fc["issued_at"])).total_seconds() / 3600
        covers = [t["date"] for t in fc["targets"]]
        check(OK if age_h < 6 else WARN, f"latest forecast issued {age_h:.1f} h ago, covers {', '.join(covers)}",
              "the server refreshes it on start; or run: python -m floodmind.live")
        check(OK if current_window(now) in covers else WARN,
              f"forecast covers the window in progress ({current_window(now)})",
              "press Refresh on the dashboard once the server is running")
    else:
        check(FAIL, "no live forecast yet", "run: python -m floodmind.live")

    for name, url in (("Open-Meteo (rain forecast)", "https://api.open-meteo.com/v1/forecast?latitude=13&longitude=80.2&hourly=precipitation&forecast_days=1"),
                      ("IMD real-time rain", "https://imdpune.gov.in/")):
        try:
            r = requests.get(url, timeout=15)
            check(OK if r.ok else WARN, f"{name} reachable (HTTP {r.status_code})", "the demo still works on the last saved forecast")
        except requests.RequestException as e:
            check(WARN, f"{name} not reachable ({type(e).__name__})", "the demo still works on the last saved forecast")

    n = len(ReportStore().for_window(current_window(now)))
    check(OK if n == 0 else WARN, f"{n} citizen reports stored for the current window",
          "use 'Clear demo reports' on the dashboard to start clean")

    with socket.socket() as s:
        free = s.connect_ex(("127.0.0.1", port)) != 0
    check(OK if free else WARN, f"port {port} {'is free' if free else 'is already in use'}",
          "FloodMind may already be running (open http://127.0.0.1:%d), or start with --port 8792" % port)

    lan = lan_url(port)
    check(OK if lan else WARN, f"phones on this Wi-Fi will use: {lan}/report" if lan else "no Wi-Fi address found",
          "join the venue Wi-Fi or a phone hotspot, then start with --host 0.0.0.0")

    print("\nStart the demo with:  .venv/bin/python -m floodmind.server --host 0.0.0.0")
    print("All checks passed." if all(r == OK for r in results) else
          f"{results.count(FAIL)} failed, {results.count(WARN)} warnings. See the arrows above.")


if __name__ == "__main__":
    main()
