"""Clean GCC 2022 ward polygons into a GeoPackage with ward_id, area and centroid."""
import geopandas as gpd

from floodmind.config import CRS_METRIC, INTERIM, WARDS_KML

wards = gpd.read_file(WARDS_KML)
wards["ward_id"] = wards["Name"].str.strip().astype(int)
wards = wards[["ward_id", "geometry"]].copy()
wards["geometry"] = wards.geometry.force_2d().make_valid()
wards = wards.dissolve("ward_id").reset_index()

metric = wards.to_crs(CRS_METRIC)
wards["area_km2"] = metric.area / 1e6
cent = metric.centroid.to_crs(wards.crs)
wards["lon"], wards["lat"] = cent.x, cent.y

wards.to_file(INTERIM / "wards.gpkg", driver="GPKG")
print(f"{len(wards)} wards, total {wards.area_km2.sum():.0f} km², "
      f"median {wards.area_km2.median():.2f} km²")
