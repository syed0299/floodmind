"""The FloodMind server (Stages 3–4).

    python -m floodmind.server                # this laptop only: http://127.0.0.1:8791
    python -m floodmind.server --host 0.0.0.0 # also phones on the same Wi-Fi (report page)

Serves the dashboard, the latest forecast and the citizen-report page, refreshes the forecast
every few hours, and applies citizen reports to the forecast as they arrive. If a refresh
fails (no network, IMD down) it keeps serving the last good forecast and says so.
"""
import argparse
import datetime as dt
import io
import json
import threading
import time
import traceback

import qrcode
import qrcode.image.svg
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from floodmind.alerts import IST
from floodmind.config import PROCESSED, ROOT
from floodmind.live import LIVE, run
from floodmind.reports import DEPTHS, Corrector, RateLimited, ReportStore, current_window, lan_url

REFRESH_HOURS = 3.0
app = FastAPI(title="FloodMind")
_lock = threading.Lock()
_state = {"running": False, "last_attempt": None, "last_success": None, "last_error": None,
          "next_run": None}
_cfg = {"port": 8791, "lan": None}
store = ReportStore()
corrector = Corrector()
NO_STORE = {"Cache-Control": "no-store"}


def _now():
    return dt.datetime.now(IST)


def _latest():
    f = LIVE / "latest.json"
    return json.loads(f.read_text()) if f.exists() else None


def _age_minutes(fc):
    if not fc:
        return None
    return round((_now() - dt.datetime.fromisoformat(fc["issued_at"])).total_seconds() / 60)


def _refresh():
    if not _lock.acquire(blocking=False):
        return False
    _state.update(running=True, last_attempt=_now().isoformat(timespec="minutes"))
    try:
        run()
        _state.update(last_success=_now().isoformat(timespec="minutes"), last_error=None)
    except Exception as e:  # keep serving the last good forecast
        _state["last_error"] = f"{type(e).__name__}: {e}"[:300]
        traceback.print_exc()
    finally:
        _state["running"] = False
        _lock.release()
    return True


def _scheduler():
    age = _age_minutes(_latest())
    if age is None or age > REFRESH_HOURS * 60:
        _refresh()
    while True:
        _state["next_run"] = (_now() + dt.timedelta(hours=REFRESH_HOURS)).isoformat(timespec="minutes")
        time.sleep(REFRESH_HOURS * 3600)
        _refresh()


def _status():
    return {**_state, "age_minutes": _age_minutes(_latest()), "refresh_hours": REFRESH_HOURS,
            "server_time": _now().isoformat(timespec="minutes"),
            "report_url": f"{_cfg['lan']}/report" if _cfg["lan"] else None}


def _correction():
    window = current_window(_now())
    return corrector.apply(_latest(), store.for_window(window), window)


def _is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in ("127.0.0.1", "::1", "localhost")


# ---------- pages ----------
@app.get("/")
def index():
    return FileResponse(ROOT / "dashboard" / "index.html")


@app.get("/report")
def report_page():
    return FileResponse(ROOT / "dashboard" / "report.html", headers=NO_STORE)


# ---------- forecast ----------
@app.get("/api/latest")
def latest():
    return JSONResponse({"forecast": _latest(), "status": _status()}, headers=NO_STORE)


@app.get("/api/status")
def status():
    return _status()


@app.post("/api/run")
def run_now():
    if _state["running"]:
        return {"started": False, "reason": "a forecast run is already in progress", **_status()}
    threading.Thread(target=_refresh, daemon=True).start()
    return {"started": True, **_status()}


# ---------- citizen reports ----------
class ReportIn(BaseModel):
    ward_id: int
    flooded: bool
    depth_cm: int | None = Field(default=None, ge=0, le=300)
    device: str = Field(min_length=8, max_length=64)


@app.get("/api/wards")
def wards():
    return FileResponse(PROCESSED / "web" / "wards.geojson", media_type="application/geo+json")


@app.get("/api/correction")
def correction(request: Request):
    return JSONResponse({**_correction(), "can_reset": _is_local(request)}, headers=NO_STORE)


@app.post("/api/reports")
def add_report(r: ReportIn):
    if r.ward_id not in corrector.idx:
        raise HTTPException(422, "Unknown ward")
    depth = (r.depth_cm if r.depth_cm in DEPTHS else None) if r.flooded else 0
    i = corrector.idx[r.ward_id]
    before = _correction()["p_now"][i]  # this ward's chance just before this report
    try:
        store.add(r.ward_id, r.flooded, depth, r.device, _now())
    except RateLimited as e:
        raise HTTPException(429, str(e))
    c = _correction()
    return {"ok": True, "ward_id": r.ward_id, "p_before": before, "p_now": c["p_now"][i],
            "p_forecast": c["p_prior"][i], "n_reports": len(c["reports"])}


@app.post("/api/reports/reset")
def reset_reports(request: Request):
    if not _is_local(request):
        raise HTTPException(403, "Reports can only be cleared from the laptop running FloodMind")
    return {"cleared": store.clear_window(current_window(_now()))}


@app.get("/api/qr.svg")
def qr():
    url = f"{_cfg['lan']}/report" if _cfg["lan"] else f"http://127.0.0.1:{_cfg['port']}/report"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers=NO_STORE)


def main():
    ap = argparse.ArgumentParser(description="Serve the FloodMind dashboard, live forecasts and reports.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 lets phones on the same Wi-Fi open the report page")
    ap.add_argument("--port", type=int, default=8791)
    a = ap.parse_args()
    _cfg["port"] = a.port
    _cfg["lan"] = lan_url(a.port) if a.host == "0.0.0.0" else None
    threading.Thread(target=_scheduler, daemon=True).start()
    print(f"FloodMind dashboard: http://127.0.0.1:{a.port}  · forecast refresh every {REFRESH_HOURS:g} h")
    if _cfg["lan"]:
        print(f"Phones on this Wi-Fi can report at: {_cfg['lan']}/report")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
