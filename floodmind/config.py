"""Shared paths and study-area settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
REPORTS = ROOT / "reports"

# Greater Chennai Corporation (200 wards) plus a small margin, lon/lat.
BBOX = (80.10, 12.82, 80.36, 13.26)  # west, south, east, north

# Metric CRS for distances/areas (UTM zone 44N).
CRS_METRIC = "EPSG:32644"
CRS_LL = "EPSG:4326"

WARDS_KML = RAW / "wards" / "gcc_wards_2022.kml"
DEM_TILES = [RAW / "dem" / "cop30_N12_E080.tif", RAW / "dem" / "cop30_N13_E080.tif"]
WORLDCOVER = RAW / "worldcover" / "ESA_WorldCover_10m_2021_v200_N12E078_Map.tif"
WORLDPOP = RAW / "worldpop" / "ind_ppp_2020_constrained.tif"
GROUNDSOURCE = RAW / "groundsource" / "groundsource_2026.parquet"

for d in (INTERIM, PROCESSED, REPORTS):
    d.mkdir(parents=True, exist_ok=True)
