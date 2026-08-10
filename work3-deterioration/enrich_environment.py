"""Enrich the cleaned sewer-pipe layer with environmental features.

Adds two feature groups shown to matter for buried-pipe deterioration in
the literature (Takachi et al. 2026, J. of AI & Data Science, JSCE):

1. Geomorphological classification (微地形区分) from the NIED J-SHIS
   250m-mesh terrain/ground classification map (2020 edition).
   Joined via the mesh code of each pipe's centroid — a simplification
   of the paper's longest-intersection rule; noted in the README.
2. Distance to coastline, using the outer boundary of the dissolved
   N03 administrative polygons (Aichi) as a coastline proxy. For Handa
   the nearest outer boundary is always the bay shore (the inland
   prefecture border lies tens of km away), so the proxy is exact in
   effect while staying on a CC BY 4.0 dataset (the KSJ coastline
   dataset C23 itself is non-commercial and thus unusable here).

Inputs (downloaded by data/env/setup_env_data.py):
    data/env/jshis/Z-WM2020-JAPAN-M250/Z-WM2020-JAPAN-M250.csv
    data/env/n03/N03-20240101_23.geojson

Output: cleaned/kankyo_enriched.gpkg
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).parent
BASE = HERE.parent
JSHIS_CSV = BASE / "data" / "env" / "jshis" / "Z-WM2020-JAPAN-M250" / "Z-WM2020-JAPAN-M250.csv"
N03_GEOJSON = BASE / "data" / "env" / "n03" / "N03-20240101_23.geojson"
OUT = HERE / "cleaned" / "kankyo_enriched.gpkg"

# Aichi-area first-order mesh prefixes (Handa city sits in 5236)
MESH_PREFIXES = ("5236", "5237", "5136", "5137")

# J-SHIS geomorphological classification (Wakamatsu & Matsuoka, 2020
# edition). See Z-WM2020-MAP.pdf for the authoritative definition.
JCODE_NAMES = {
    0: "沿岸海域", 1: "山地", 2: "山麓地", 3: "丘陵", 4: "火山地",
    5: "火山山麓地", 6: "火山性丘陵", 7: "岩石台地", 8: "砂礫質台地",
    9: "火山灰台地", 10: "谷底低地", 11: "扇状地", 12: "自然堤防",
    13: "後背湿地", 14: "旧河道・旧池沼", 15: "三角州・海岸低地",
    16: "砂州・砂礫州", 17: "砂丘", 18: "砂丘・砂州間低地",
    19: "干拓地", 20: "埋立地",
    21: "磯・岩礁", 22: "河原", 23: "河道", 24: "湖沼",
}


def mesh250_code(lat: float, lon: float) -> str:
    """JIS X 0410 mesh code down to the 250m (quarter-of-quarter) level."""
    p = int(lat * 1.5)
    u = int(lon - 100)
    lat_r = lat * 1.5 - p
    lon_r = lon - 100 - u
    q = int(lat_r * 8)
    v = int(lon_r * 8)
    lat_r = lat_r * 8 - q
    lon_r = lon_r * 8 - v
    r = int(lat_r * 10)
    w = int(lon_r * 10)
    lat_r = lat_r * 10 - r
    lon_r = lon_r * 10 - w
    # 500m quadrant: 1=SW 2=SE 3=NW 4=NE
    d4 = (2 if lat_r >= 0.5 else 0) + (1 if lon_r >= 0.5 else 0) + 1
    lat_r = lat_r * 2 - (1 if lat_r >= 0.5 else 0)
    lon_r = lon_r * 2 - (1 if lon_r >= 0.5 else 0)
    d5 = (2 if lat_r >= 0.5 else 0) + (1 if lon_r >= 0.5 else 0) + 1
    return f"{p:02d}{u:02d}{q}{v}{r}{w}{d4}{d5}"


def load_terrain() -> pd.DataFrame:
    df = pd.read_csv(
        JSHIS_CSV, comment="#", header=None,
        names=["CODE", "JCODE", "AVS"], dtype={"CODE": str},
        skipinitialspace=True,
    )
    df["CODE"] = df["CODE"].str.strip()
    df = df[df["CODE"].str.startswith(MESH_PREFIXES)]
    df["JCODE"] = pd.to_numeric(df["JCODE"], errors="coerce").astype("Int64")
    df["AVS"] = pd.to_numeric(df["AVS"], errors="coerce")
    print(f"terrain mesh rows (Aichi area): {len(df):,}")
    return df.set_index("CODE")


def main() -> None:
    gdf = gpd.read_file(HERE / "cleaned" / "kankyo_cleaned.gpkg")
    print(f"pipes: {len(gdf):,}")

    centroids = gdf.geometry.centroid

    # --- coastline distance (via dissolved admin-boundary proxy) ---
    admin = gpd.read_file(N03_GEOJSON).to_crs(gdf.crs)
    boundary = admin.union_all().boundary
    gdf["coast_dist_m"] = centroids.distance(boundary).round(1)
    print("coast_dist_m: min {:.0f} / median {:.0f} / max {:.0f}".format(
        gdf["coast_dist_m"].min(), gdf["coast_dist_m"].median(),
        gdf["coast_dist_m"].max()))

    # --- terrain classification via 250m mesh code of centroid ---
    cent_wgs = centroids.to_crs("EPSG:4326")
    codes = [mesh250_code(pt.y, pt.x) for pt in cent_wgs]
    terrain = load_terrain()
    matched = terrain.reindex(codes)
    gdf["terrain_code"] = matched["JCODE"].to_numpy()
    gdf["avs30"] = matched["AVS"].to_numpy()
    gdf["terrain_name"] = pd.Series(gdf["terrain_code"]).map(JCODE_NAMES)

    join_rate = gdf["terrain_code"].notna().mean()
    print(f"terrain join rate: {join_rate:.1%}")
    print("\nterrain distribution (pipes):")
    print(gdf["terrain_name"].value_counts().to_string())

    gdf.to_file(OUT, layer="kankyo", driver="GPKG")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
