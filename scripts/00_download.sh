#!/usr/bin/env bash
# Download the open datasets FloodMind uses (~1.7 GB). No accounts or API keys needed.
set -euo pipefail
cd "$(dirname "$0")/../data/raw"
mkdir -p dem worldcover worldpop groundsource wards rain/imd

# Copernicus GLO-30 elevation (AWS open data)
for t in N12_00_E080_00 N13_00_E080_00; do
  curl -fL -o "dem/cop30_${t:0:3}_E080.tif" \
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_${t}_DEM/Copernicus_DSM_COG_10_${t}_DEM.tif"
done
# ESA WorldCover 2021, 10 m land cover
curl -fL -o worldcover/ESA_WorldCover_10m_2021_v200_N12E078_Map.tif \
  "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N12E078_Map.tif"
# WorldPop 2020 constrained population, ~100 m (slow server; 531 MB)
curl -fL --retry 5 -o worldpop/ind_ppp_2020_constrained.tif \
  "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/IND/ind_ppp_2020_constrained.tif"
# Google Groundsource flood events from news (Zenodo, CC BY 4.0; 667 MB)
curl -fL -o groundsource/groundsource_2026.parquet \
  "https://zenodo.org/records/18647054/files/groundsource_2026.parquet?download=1"
# Greater Chennai Corporation 2022 ward map (OpenCity)
curl -fL -o wards/gcc_wards_2022.kml \
  "https://data.opencity.in/dataset/c77de7f8-e377-4990-90fc-4f0f8ca0e2d2/resource/e90176d4-319a-45bd-918e-ecce4f048c4d/download/6a8a05ed-a41c-492a-aade-ff7517e1a4b1.kml"
# IMD 0.25° gridded daily rainfall, 2015–2025
(cd rain/imd && ../../../../.venv/bin/python -c "import imdlib as imd; imd.get_data('rain', 2015, 2025, fn_format='yearwise', file_dir='.')")
