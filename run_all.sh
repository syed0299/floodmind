#!/usr/bin/env bash
# Rebuild every FloodMind output from the raw data (about 10–15 minutes on a laptop).
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
$PY scripts/01_wards.py          # ward polygons
$PY scripts/02_osm.py            # OSM roads, water, facilities (network, cached)
$PY -m floodmind.gazetteer       # locality -> ward lookup
$PY scripts/03_terrain.py        # DEM -> sinks, HAND, flow, TWI
$PY scripts/04_ward_features.py  # static per-ward features
$PY scripts/05_rain.py           # IMD observed + ECMWF archived forecasts
$PY scripts/06_labels.py         # truth engine: Groundsource + news -> ward-day labels
$PY scripts/07_dataset.py        # ward x day training table
$PY scripts/08_train.py          # leave-one-year-out training, baselines, model bundles
$PY scripts/10_eval_live.py      # live correction + active sensing evaluation
$PY scripts/11_drain_deficit.py  # drainage shortfall ranking
$PY scripts/13_live_replay.py    # the live engine replayed on 2024–25
$PY scripts/14_accuracy_plain.py # accuracy in plain words
$PY -m floodmind.live || echo "live forecast skipped (no internet?); the dashboard keeps the last one"
$PY scripts/09_export_geo.py     # map layers
$PY scripts/12_export_dashboard.py  # dashboard/index.html
