# FloodMind

**A flood forecasting system for Chennai that learns from every flood.**

FloodMind forecasts the chance of flooding in each of Chennai's 200 GCC wards for the next day. It corrects that forecast as citizen reports arrive during the storm, and it ranks the wards whose drainage is failing. Every number in this README and on the dashboard comes from data the model was not trained on.

| | Google Flood Hub (urban flash floods, 2026) | Tamil Nadu RTFF & SDSS (2025, ₹107 crore) | **FloodMind** |
|---|---|---|---|
| Spatial unit | 20 km × 20 km cells | River, lake and drain levels; street-level inundation for selected vulnerable areas | All 200 GCC wards (median 1.5 km²) |
| Inputs | Global weather + news-derived flood history | 390 field sensors, 5 weather models, hydrodynamic models | Open data only, no sensors |
| Live observations | Not documented | Rain, water-level and gate sensors | Citizen reports + targeted questions |
| Explains *why* a place floods | No | Not documented | Ranks drainage shortfall by ward |
| Published accuracy | Global evaluation | Not public | Held-out scorecard per ward-day |

FloodMind is meant to complement both: a city-wide, ward-level layer that any Indian city can run from open data, and a verification and crowd layer for systems like Tamil Nadu's.

**Presenting it?** Follow [DEMO.md](DEMO.md): pre-flight check, a 5-minute script, backup paths and answers to likely questions. Tamil wording for review is in [TAMIL_REVIEW.md](TAMIL_REVIEW.md); the build plan is in [ROADMAP.md](ROADMAP.md).

## Results (all out-of-sample)

Every year from 2015 to 2025 was held out in turn and scored by a model that never saw that year. The labels are 23,536 ward-days of reported flooding.

**Next-day ward flood forecast, all days**

| Model | PR-AUC | ROC AUC | Brier |
|---|---|---|---|
| **FloodMind** (fixed 50/50 average of the next two) | **0.477** | **0.933** | **0.0176** |
| LightGBM, all features | 0.459 | 0.930 | 0.0180 |
| Logistic: rain + ward flood history | 0.466 | 0.928 | 0.0181 |
| Logistic: rain only | 0.442 | 0.920 | 0.0186 |
| Logistic: terrain only | 0.026 | 0.502 | 0.0256 |

The base rate is 2.6% of ward-days, so FloodMind's PR-AUC is 18× chance. Accuracy is not reported because "never flood" would score 97%.

**In plain words** (`scripts/14_accuracy_plain.py`), using only the rain forecast issued the day before, as a live system would (2024–25, model trained on 2015–2023):

| Question | Answer |
|---|---|
| When FloodMind says a ward is at high risk (55%+), how often was flooding reported there? | **76%**, about 3 times in 4 |
| What share of flooded ward-days did it flag as high risk? | 15% (31% at the 30% advisory level) |
| Major storms in 2024–25 that got advisories (30%+) | all 6; 4 reached high risk |
| Dry days with a false high-risk flag | 1.2% (3.5% at the advisory level) |

It is a cautious forecaster: right when it raises the alarm, but it misses many smaller floods, and it struggles on the first day of a storm when the rain forecast is wrong. That is the gap the citizen-report loop fills.

**On flood days, which wards?** FloodMind 0.557 PR-AUC (base rate 0.216), rain only 0.518, terrain only 0.238.

**With the forecast a live system would have had (2024–25):** using the ECMWF rainfall forecast issued 24 h earlier, PR-AUC is 0.527, against 0.582 with observed rain. Most of the skill survives real lead time.

**Live correction (262 held-out flood days, 2021–25).** Scores are on wards not yet heard from.

| Starting point | Observations | PR-AUC | Brier |
|---|---|---|---|
| Out-of-sample forecast with observed rain | 5 citizen reports | 0.40 → **0.54** | 0.174 → **0.158** |
| | 10 citizen reports | 0.38 → **0.56** | 0.160 → **0.157** |
| Forecast issued 24 h earlier (67 flood days, 2024–25) | 5 citizen reports | 0.43 → **0.58** | 0.204 → **0.176** |
| | 10 citizen reports | 0.41 → **0.60** | 0.190 → **0.163** |

When FloodMind chooses which ward to ask instead of asking at random, it gains more in most settings (for example +0.043 vs +0.023 PR-AUC at 5 questions with observed rain, about 1.9×). The edge is modest and not universal: from the 24 h forecast at 5 questions, random asking did slightly better. Citizen reports help most because they come from where flooding is. Reports are one-sided: "flooded" never lowers a ward's chance, and "dry" never raises it.

**Drain diagnosis:** wards are ranked by how much more often they flood on wet days than rainfall, terrain and land cover predict. The top of the list includes Egmore, Ekkattuthangal, Poompuhar Nagar, Santhome, T. Nagar, Saidapet and Velachery, which overlaps the government system's own vulnerable-area list. Media-attention proxies explain R² = 0.04 of the excess, so the ranking is not just "well-reported areas".

## Findings worth knowing

1. **Terrain alone predicts almost nothing about where reported floods happen** (ROC 0.50). Yet a ward's flood rate is very persistent: even-year and odd-year rates correlate at Spearman 0.84. Chennai's flood geography comes from drainage and history, not from elevation. That is why the drain-diagnosis loop exists.
2. **Groundsource agrees with independent reporting.** All 29 of our hand-curated news reports inside GCC also appear in Google's Groundsource within a day.
3. **We traded 4% of aggregate PR-AUC for safety.** With day-of-year features, the model scored higher overall but gave the 30 Dec 2021 cloudburst (103 mm, which IMD also missed) a 3% chance, because floods "usually" come earlier in the season. We removed those features. The same day now gets 38%.
4. **Rain forecasts can miss badly.** For Cyclone Ditwah (2 Dec 2025), ECMWF predicted 22 mm a day ahead and 153 mm fell. The live loop is built for exactly that failure.

## How it works

```
Open data ─► Truth engine ─► Forecast ─► Live correction ─► Advisories (EN/TA, CAP 1.2)
   │          Groundsource     ward × day     Gaussian field         │
   │          + news reports   LightGBM +     update + active        ▼
   │                           logistic       sensing          Drain diagnosis
   └─ IMD rain · ECMWF forecasts · Copernicus DEM · WorldCover · WorldPop · OSM
```

- **Truth engine** (`scripts/06_labels.py`): 7,028 locality-scale Groundsource flood polygons for Chennai since 2015 (typically under 1 km²) plus curated news reports, mapped to wards and days.
- **Forecast** (`scripts/08_train.py`): rainfall (day, 1/3/7/30/60-day antecedent), terrain (sinks, height above drainage, wetness), land cover, exposure, and each ward's flood history computed only from other years.
- **Live correction** (`floodmind/assimilate.py`): ward risks are treated as a Gaussian field correlated over about 2 km, tuned on 2015–20 only. A report updates its ward and the wards around it. Active sensing asks where population × uncertainty would shrink most.
- **Drain diagnosis** (`scripts/11_drain_deficit.py`): observed minus physics-only expected flood-days, as a z-score, with a before/after check around the 2022–24 storm-drain works.
- **Advisories** (`floodmind/alerts.py`): fixed Tamil and English templates, and CAP 1.2 XML (the format SACHET ingests) with status `Exercise`.

## Run it

```bash
brew install uv            # or: pip install uv
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt && uv pip install --python .venv -e .
./scripts/00_download.sh   # ~1.7 GB of open data, no accounts needed
./run_all.sh               # 10–15 minutes; rebuilds every number and the dashboard
.venv/bin/python -m floodmind.preflight   # checks everything the live demo needs
open dashboard/index.html  # works offline with the last forecast snapshot (fonts fall back if there is no network)
```

## Live forecast

```bash
.venv/bin/python -m floodmind.live
```

Issues a forecast for the IMD day in progress (to 08:30 tomorrow) and the one after, for all 200 wards, in about a minute. Recent rain comes from IMD's real-time grid. Any day IMD has not published yet is filled from ECMWF, and the output lists those days. Coming rain comes from the latest ECMWF run. Output goes to `data/live/latest.json`, a timestamped copy and `data/live/forecast_log.csv`.

To run the dashboard with live forecasts and citizen reports:

```bash
.venv/bin/python -m floodmind.server          # http://127.0.0.1:8791
```

```bash
.venv/bin/python -m floodmind.server --host 0.0.0.0   # also lets phones on the same Wi-Fi report
```

With `--host 0.0.0.0`, the dashboard shows a QR code for the phone report page (`/report`, English and Tamil). People pick their ward, say flooded or dry, and optionally give the depth. Each report updates its ward and the wards within about 2 km on the dashboard within seconds, and FloodMind suggests which wards it most wants to hear from next. Reports are kept in `data/live/reports.sqlite` with the ward, the answer, the depth, the time and a one-way hash of a random browser id (used only to allow one report per ward per hour). No name, phone number or location is stored. "Clear demo reports" works only on the laptop running the server. macOS may ask once whether Python may accept incoming connections; allow it so phones can connect.

The server refreshes the forecast every 3 hours, and the dashboard's Refresh button triggers a run on demand. If a refresh fails (no network, IMD down), the server keeps the last good forecast and the dashboard says how old it is. Opened as a plain file, the dashboard shows the forecast snapshot from build time.

`scripts/13_live_replay.py` runs the same code on 2024–25 with a model trained only on 2015–2023. It scores PR-AUC 0.527 with IMD final history (identical to the evaluation), 0.526 with the IMD real-time history it uses day to day, and 0.526 with ECMWF-only history. So the live engine is the model that was tested, and it still works when IMD is late.

## Repository

```
floodmind/
  model.py        feature lists, the 50/50 ensemble, calibration, saved model bundles
  rain.py         IMD final + real-time grids and ECMWF forecasts on the 08:30 IST day
  live.py         the live forecast engine
  server.py       dashboard, live forecasts, phone report page, scheduled refresh
  reports.py      citizen-report store (SQLite) and the live correction
  assimilate.py   Gaussian-field correction and "ask here next"
  alerts.py       Tamil/English advisories and CAP 1.2 XML
  preflight.py    demo-day checks
scripts/          numbered pipeline steps 00–14
dashboard/        template.html → index.html (dashboard), report.html (phone page)
reports/          metrics, live correction, live replay, plain accuracy, drain ranking (JSON)
data/processed/   labels, training table, predictions, model bundles
data/live/        latest forecast, forecast log, citizen reports
```

## Limits

- Labels come from news. A flood nobody reported counts as dry, so quieter wards look safer than they are.
- IMD rainfall is a 0.25° grid (~27 km). Neighbouring wards share rain values, and local cloudbursts are smoothed.
- Forecasts are per ward per day, not street-level depth.
- The live-correction gains are measured by replaying reported floods. Real reports will be noisier and arrive unevenly.
- The drain ranking is a list for field inspection, not a verdict on any drain.
- Advisories are demonstrations. Official warnings in India come from IMD and the state disaster authority (TN-Alert / SACHET).

## How ready is it?

A validated prototype (about step 5 of the 9-step technology readiness scale): tested on 11 years of held-out data and running live, but not yet proven through a live monsoon. It is ready for a supervised shadow run, not for public warnings.

| Area | Status | Needed for a real deployment |
|---|---|---|
| Forecast accuracy | Held-out tests; live code reproduces them | A full live monsoon in shadow mode |
| Live data | Works, with automatic fallback | A commercial weather-data licence (Open-Meteo's free tier is non-commercial) or an IMD/ECMWF agreement |
| Citizen reports | Works on local Wi-Fi, rate-limited | Photo checks, trust scores, hosted HTTPS service |
| Software | Runs on one laptop | Automated tests, monitoring, backups, hosting |
| Alerts | Tamil/English + CAP, marked Exercise | Native-speaker review; issued only through IMD / the state authority |
| Partners | None yet | An agency partner (GCC or the state disaster authority) |

## Next

1. **Shadow mode this monsoon** (northeast monsoon starts mid-October): run every few hours, log every forecast, publish no alerts, and score against what floods.
2. Photo-to-depth on the report page, and checks against fake reports.
3. Better rain: NASA IMERG (0.1°) and Chennai's own 117 rain gauges.
4. Street-level nowcasting 1–3 hours ahead: a graph neural network over the road network, trained on 2D flood simulations, with flood-aware routing.
5. Transfer test: train on Chennai, evaluate in a city with no forecasting system.

## Data and credits

Google Groundsource (CC BY 4.0) · IMD gridded rainfall (Pai et al.) via imdlib · ECMWF IFS forecasts via Open-Meteo · Copernicus GLO-30 DEM · ESA WorldCover 2021 (CC BY 4.0) · WorldPop 2020 (CC BY 4.0) · © OpenStreetMap contributors (ODbL) · GCC ward map via OpenCity.
