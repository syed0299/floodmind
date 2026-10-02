"""Fetch OpenStreetMap layers for the study area: roads, waterways, water bodies, critical facilities."""
import geopandas as gpd
import osmnx as ox

from floodmind.config import BBOX, RAW

OUT = RAW / "osm"
ox.settings.use_cache = True
ox.settings.cache_folder = str(OUT / "cache")
ox.settings.requests_timeout = 300

west, south, east, north = BBOX
bbox = (west, south, east, north)

print("roads...")
G = ox.graph_from_bbox(bbox, network_type="drive", simplify=True)
ox.save_graphml(G, OUT / "roads_drive.graphml")
edges = ox.graph_to_gdfs(G, nodes=False)[["highway", "length", "geometry"]]
edges["highway"] = edges["highway"].astype(str)
edges.reset_index(drop=True).to_file(OUT / "roads.gpkg", driver="GPKG")
print(f"  {len(edges)} road edges")


def features(tags, name):
    gdf = ox.features_from_bbox(bbox, tags)
    keep = [c for c in ("name", "amenity", "waterway", "natural", "water", "landuse") if c in gdf]
    gdf = gdf[keep + ["geometry"]].reset_index(drop=True)
    for c in keep:
        gdf[c] = gdf[c].astype(str)
    gdf.to_file(OUT / f"{name}.gpkg", driver="GPKG")
    print(f"  {name}: {len(gdf)}")


print("water...")
features({"waterway": ["river", "canal", "stream", "drain", "ditch"]}, "waterways")
features({"natural": ["water", "wetland"], "water": True, "landuse": ["reservoir", "basin"]}, "waterbodies")
print("facilities...")
features({"amenity": ["hospital", "clinic", "school", "fire_station", "police", "shelter",
                      "community_centre", "college"]}, "facilities")
