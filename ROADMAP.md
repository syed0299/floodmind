# FloodMind roadmap

Each stage ends with something that works and can be shown. Build them in order; a stage starts only when the one before it meets its "done when".

Deadline: competition submission on 7 October 2026.

## Phase A: real-time system for the competition (3–6 October)

### Stage 1: Historical foundation · DONE (2 Oct)
- Data pipeline, truth engine (Groundsource + news), ward × day model, leave-one-year-out tests.
- Live-correction maths and evaluation, drain diagnosis, replay dashboard, pitch deck, README.
- **Done when:** every number is out-of-sample and `./run_all.sh` rebuilds it all. ✓

### Stage 2: Live forecast engine · DONE (2 Oct)
- `floodmind/live.py`: fetch tomorrow's ECMWF rain forecast and the last 60 days of rain for Chennai, build the same features, predict all 200 wards, save `forecast_<time>.json` and append to a forecast log.
- Recent observed rain: check whether IMD's near-real-time grid is downloadable. If not, use ECMWF analysis and correct its bias against IMD using the 2024–25 overlap.
- Replay the exact live code path on 2024–25 so the 0.527 PR-AUC claim still holds for the code that runs live.
- **Done when:** one command produces today's forecast in under a minute, and the 2024–25 replay of that command scores within 0.02 of 0.527. ✓
  - Replay (`scripts/13_live_replay.py`, model trained on 2015–2023 only): IMD final history 0.527 (identical to the evaluation), IMD real-time history 0.526, ECMWF-only fallback 0.526.
  - IMD's real-time server answers one request at a time (~15 s each), so the engine fetches newest days first within a 90 s budget and fills the rest from ECMWF, and says which days it filled.

### Stage 3: Live dashboard · DONE (3 Oct)
- A small local server (FastAPI) serves the latest forecast. The dashboard gets a "Today" view next to the past-event replays, shows when it was last updated, and refreshes itself.
- If the network fails at the venue, it shows the last saved forecast and says so.
- **Done when:** opening the dashboard shows today's real forecast for Chennai, and pulling the network cable still leaves a working demo. ✓
  - `python -m floodmind.server` serves the dashboard and `/api/latest`, refreshes every 3 h, and has a Refresh button (`POST /api/run`). If a refresh fails it keeps serving the last good forecast and the status pill says so.
  - Redesign: four views (Today, Replay a flood, Drain check, Scorecard) on one interactive ward map; mild coral palette built from three base colours with CSS relative colours; light and dark themes; works at phone width.
  - Without a server (opened as a file, or the shared link) the page shows the forecast snapshot from build time, labelled as a snapshot.

### Stage 4: Citizen reports and live correction · DONE (3 Oct)
- A report form: pick a ward on the map, choose "flooded" or "dry", optional water depth. No names or phone numbers are stored.
- Reports go into a local SQLite file. Each report updates its ward and its neighbours on the map within seconds, and "ask here next" suggestions update with it.
- Basic checks: one report per device per ward per hour, and a reset button for the demo.
- **Done when:** a judge can submit a report from their phone and watch the map change. ✓
  - `/report` phone page (English and Tamil): search or tap a ward, flooded or dry, optional depth; replies with that ward's chance before and after the report.
  - The dashboard's Today view checks for new reports every 4 s: corrected map, report rings, "ask here next", report feed, QR code, advisories from the corrected map, and a laptop-only reset.
  - Tested: a knee-deep report in Velachery moved it 2% → 84% and its neighbours up with distance; repeat reports are rejected; dry reports can no longer raise a ward's chance (a bug the test caught, fixed and re-evaluated).

### Stage 5: Advisories and handoff · BUILT, Tamil review pending
- Every run writes Tamil and English advisories plus CAP 1.2 XML for wards at high risk.
- A native Tamil speaker reviews the templates.
- **Done when:** each forecast run produces reviewed advisories and valid CAP files.
  - Built: every live run and every report update produces Tamil/English advisories and CAP 1.2 XML from the map being shown.
  - Pending (you): a native speaker fills in [TAMIL_REVIEW.md](TAMIL_REVIEW.md); I then apply the corrections.

### Stage 6: Demo hardening and submission · DONE on my side (3 Oct); rehearsal is yours
- Rehearsed 5-minute demo: today's forecast → submit a report → map updates → past cyclone replay → drain list.
- Fill the deck placeholders, add one slide on the live mode, update the README, create a clean git repository.
- **Done when:** the full demo runs twice in a row without help, online and offline.
  - Done: `python -m floodmind.preflight` (13 checks, all passing), [DEMO.md](DEMO.md) (5-minute script, backup paths, judge Q&A), full rebuild from raw data reproduces every result file exactly, deck updated (new "Running now" slide, plain-language accuracy), README final pass, shared dashboard refreshed.
  - Yours: fill the deck placeholders, test the phone page on the venue Wi-Fi, rehearse twice. Git repository: not created (say the word if you want one).

## Phase B: prove it in a real monsoon (mid-October to December 2026)

### Stage 7: Shadow mode
- Run the live engine every few hours through the northeast monsoon on an always-on machine (a small cloud server, or a scheduled GitHub Action).
- Publish nothing. Log every forecast and score it each week against reported floods.
- **Done when:** a full season of logged forecasts is scored, giving the first truly live accuracy numbers.

### Stage 8: Sharper inputs
- NASA IMERG rain at 0.1° (needs a free Earthdata account, created by you).
- Request Chennai's 117 rain-gauge feed from the Tamil Nadu authorities.
- Move from daily to 6-hourly forecasts once the rain data allows it.
- **Done when:** forecasts run every 6 hours and beat the daily model on the shadow-mode log.

## Phase C: research depth (2027)

### Stage 9: Street-level depth
- Run 2D flood simulations over the Chennai elevation model, train a fast neural surrogate, and calibrate it with reports and photo-estimated depths.
- **Done when:** depth maps for past events match reported depths better than ward-level risk does.

### Stage 10: Decisions
- Flood-aware routing on the OpenStreetMap road graph, and pre-positioning of pumps, boats and relief across forecast scenarios.
- **Done when:** plans are scored on past events against simple rules (for example "send to the most-flooded ward").

### Stage 11: Scale and partnership
- Transfer test: train on Chennai, run in a city with no flood forecasting.
- Pilot with the Greater Chennai Corporation or the state disaster authority, including CAP alerts into SACHET.
- **Done when:** a second city has held-out results and one agency has used the drain list or the forecasts.

## Decisions only you can make

| Stage | Decision |
|---|---|
| 4 | Whether judges may submit reports from their own phones (needs the laptop and phones on the same Wi-Fi) |
| 5 | Who reviews the Tamil text |
| 7 | Where shadow mode runs (your laptop, a cloud server, or GitHub Actions) |
| 8 | Creating a NASA Earthdata account; contacting Tamil Nadu for gauge data |
| 11 | Which agency to approach, and when |
