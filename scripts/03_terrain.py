"""Terrain rasters from Copernicus GLO-30.

Copernicus DEM is a surface model (it includes buildings), so we apply a small grey
opening to approximate bare ground, burn OSM rivers/canals into it so drainage follows
the real channels, then derive hydrological layers with pysheds:

  dtm        bare-earth approximation (m)
  sink_depth depth of closed depressions = filled - original (m)  -> waterlogging pockets
  hand       height above nearest drainage (m)
  facc       flow accumulation (cells)
  slope      slope (degrees)
  twi        topographic wetness index ln(a / tan b)
"""
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy import ndimage
from pysheds.grid import Grid
from pysheds.sview import Raster

from floodmind.config import CRS_METRIC, DEM_TILES, INTERIM, RAW

if not hasattr(np, "in1d"):  # pysheds still calls the NumPy 1.x name
    np.in1d = lambda a, b, **kw: np.isin(np.ravel(a), b, **kw)

# Hydrology domain is larger than the city so upstream flow is not cut off at the edge.
DOMAIN = (80.00, 12.75, 80.40, 13.35)
RES = 30.0
OUT = INTERIM / "terrain"
OUT.mkdir(exist_ok=True)


def write(name, arr, profile):
    p = profile.copy()
    p.update(dtype="float32", count=1, nodata=np.nan, compress="deflate")
    with rasterio.open(OUT / f"{name}.tif", "w", **p) as dst:
        dst.write(arr.astype("float32"), 1)


# 1. Mosaic + clip to domain + reproject to UTM 30 m.
srcs = [rasterio.open(p) for p in DEM_TILES]
mosaic, tr = merge(srcs, bounds=DOMAIN)
src_crs = srcs[0].crs
h, w = mosaic.shape[1:]
dst_tr, dw, dh = calculate_default_transform(src_crs, CRS_METRIC, w, h, *DOMAIN, resolution=RES)
dem = np.full((dh, dw), np.nan, dtype="float32")
reproject(mosaic[0], dem, src_transform=tr, src_crs=src_crs, dst_transform=dst_tr,
          dst_crs=CRS_METRIC, resampling=Resampling.bilinear, dst_nodata=np.nan)
profile = dict(driver="GTiff", height=dh, width=dw, crs=CRS_METRIC, transform=dst_tr)
print(f"DEM grid {dh}x{dw} at {RES} m")

# Sea / nodata: Copernicus marks ocean at ~0 m; keep as 0 so it acts as the outlet.
dem = np.where(np.isnan(dem), 0.0, dem)
# A few water-filled quarry pits near Pammal read as -65 m; floor them so they don't dominate.
dem = np.maximum(dem, -3.0)
write("dem_raw", dem, profile)

# 2. DSM -> DTM approximation: grey opening removes building-sized bumps (<= 90 m).
dtm = ndimage.grey_opening(dem, size=(3, 3)).astype("float32")

# 3. Burn mapped rivers/canals 3 m into the DTM so flow routing follows them.
ww_path = RAW / "osm" / "waterways.gpkg"
burn = np.zeros_like(dtm, dtype=bool)
if ww_path.exists():
    ww = gpd.read_file(ww_path).to_crs(CRS_METRIC)
    ww = ww[ww["waterway"].isin(["river", "canal"])]
    if len(ww):
        burn = rasterize(((g, 1) for g in ww.geometry.buffer(15)), out_shape=dtm.shape,
                         transform=dst_tr, fill=0, dtype="uint8").astype(bool)
    print(f"burned {burn.sum()} channel cells from {len(ww)} OSM rivers/canals")
conditioned = np.where(burn, dtm - 3.0, dtm).astype("float32")
write("dtm", dtm, profile)
write("dtm_burned", conditioned, profile)

# 4. Hydrology with pysheds.
grid = Grid.from_raster(str(OUT / "dtm_burned.tif"))
r = grid.read_raster(str(OUT / "dtm_burned.tif"))
pit = grid.fill_pits(r)
pit_arr = np.array(pit, copy=True)  # fill_depressions modifies its input in place
filled = grid.fill_depressions(pit)
flat = grid.resolve_flats(filled)
dirmap = (64, 128, 1, 2, 4, 8, 16, 32)
fdir = grid.flowdir(flat, dirmap=dirmap)
acc = grid.accumulation(fdir, dirmap=dirmap)

# Channels: >= 0.5 km² contributing area, plus the burned OSM channels.
channels = (np.asarray(acc) >= 0.5e6 / RES**2) | burn
channels_r = Raster(channels, viewfinder=acc.viewfinder)
hand = grid.compute_hand(fdir, flat, channels_r, dirmap=dirmap)

sink = np.clip(np.asarray(filled) - pit_arr, 0, 5.0)
write("sink_depth", sink, profile)
write("hand", np.asarray(hand), profile)
write("facc", np.asarray(acc), profile)
write("channels", channels.astype("float32"), profile)

# 5. Slope and TWI.
gy, gx = np.gradient(dtm, RES)
slope = np.degrees(np.arctan(np.hypot(gx, gy)))
a = (np.asarray(acc) + 1) * RES  # specific catchment area per unit contour width
twi = np.log(a / np.tan(np.radians(np.maximum(slope, 0.1))))
write("slope", slope, profile)
write("twi", twi, profile)

print("done:", sorted(p.name for p in OUT.glob("*.tif")))
for name, arr in [("sink_depth", sink), ("hand", np.asarray(hand)), ("slope", slope)]:
    v = arr[np.isfinite(arr)]
    print(f"  {name}: p50={np.percentile(v, 50):.2f} p90={np.percentile(v, 90):.2f} max={v.max():.2f}")
