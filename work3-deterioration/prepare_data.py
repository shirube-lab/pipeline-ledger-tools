"""Prepare the Handa sewer-pipe layer for deterioration analysis.

Steps:
1. Load the raw 管渠 shapefile (SonicWeb export, opaque SAFIELD columns).
2. Assign the presumed CRS (JGD2011 plane rectangular zone VII, EPSG:6675)
   and verify it numerically by reprojecting to WGS84 — the result must
   land on Handa City (lon ~136.9, lat ~34.9).
3. Rename columns using the S2AConfig XML definitions.
4. Profile SASTYLEID groups, then classify 汚水/雨水 (241xx/243xx).
5. Parse 施工年度 ("2009年" -> 2009) and compute pipe age.
6. Save a cleaned GeoPackage + a WGS84 GeoJSON for web mapping.

Output: cleaned/kankyo_cleaned.gpkg, cleaned/kankyo_wgs84.geojson
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
RAW = BASE / "data" / "handa" / "gesui_osui" / "24021" / "24021.shp"
OUT_DIR = Path(__file__).parent / "cleaned"

CRS_ASSUMED = "EPSG:6675"  # JGD2011 plane rectangular zone VII (presumed, verified below)
BASE_YEAR = 2026           # age reference year

# From 24021.xml (S2AConfig) — verified attribute definitions
RENAME = {
    "SAFIELD000": "sekou_year_raw",   # 施工年度
    "SAFIELD001": "kanshu",           # 管種名称
    "SAFIELD002": "kankei_mm",        # 管径1(mm) 径/幅
    "SAFIELD003": "dokaburi_up_m",    # 上流土被り(m)
    "SAFIELD004": "dokaburi_dn_m",    # 下流土被り(m)
}

# Handa City rough bounding box for the CRS sanity check
HANDA_LON = (136.85, 137.05)
HANDA_LAT = (34.83, 34.98)


def verify_crs(gdf: gpd.GeoDataFrame) -> None:
    wgs = gdf.to_crs("EPSG:4326")
    lon_min, lat_min, lon_max, lat_max = wgs.total_bounds
    print(f"WGS84 bounds: lon {lon_min:.4f}..{lon_max:.4f}, lat {lat_min:.4f}..{lat_max:.4f}")
    ok = (
        HANDA_LON[0] < lon_min and lon_max < HANDA_LON[1]
        and HANDA_LAT[0] < lat_min and lat_max < HANDA_LAT[1]
    )
    if not ok:
        raise SystemExit("CRS check FAILED: reprojected data does not land on Handa City")
    print("CRS check OK: data lands on Handa City -> EPSG:6675 assumption holds")


def profile_styles(gdf: gpd.GeoDataFrame) -> None:
    print("\n--- SASTYLEID profile (count / median diameter / median year) ---")
    tmp = gdf.copy()
    tmp["year"] = pd.to_numeric(
        tmp["sekou_year_raw"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
    )
    prof = tmp.groupby("SASTYLEID").agg(
        n=("SASTYLEID", "size"),
        med_diameter=("kankei_mm", "median"),
        med_year=("year", "median"),
        null_year=("year", lambda s: round(s.isna().mean(), 3)),
    )
    print(prof.to_string())


def main() -> None:
    gdf = gpd.read_file(RAW, encoding="cp932")
    print(f"raw features: {len(gdf)}")

    gdf = gdf.set_crs(CRS_ASSUMED, allow_override=True)
    verify_crs(gdf)

    gdf = gdf.rename(columns=RENAME)
    profile_styles(gdf)

    # Sewer type: style IDs 241xx are the 汚水 (sanitary) rendering styles,
    # 243xx the 雨水 (storm) ones — validated by the diameter profile above.
    gdf["sewer_type"] = pd.cut(
        gdf["SASTYLEID"], bins=[24100, 24199, 24399], labels=["汚水", "雨水"]
    )
    assert gdf["sewer_type"].notna().all(), "unclassified SASTYLEID found"

    n_dup = gdf["SAUID"].duplicated().sum()
    if n_dup:
        print(f"note: SAUID duplicated on {n_dup} rows (kept as-is; "
              "documented in data-quality findings)")

    gdf["sekou_year"] = pd.to_numeric(
        gdf["sekou_year_raw"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
    ).astype("Int64")
    gdf["age"] = BASE_YEAR - gdf["sekou_year"]
    gdf["length_m"] = gdf.geometry.length.round(2)

    n_year = gdf["sekou_year"].notna().sum()
    print(f"\ncleaned: {len(gdf)} pipes / with year: {n_year} "
          f"({n_year / len(gdf):.1%}) / total length: {gdf['length_m'].sum() / 1000:.1f} km")
    print(gdf["sewer_type"].value_counts().to_string())
    print("\nyear range:", int(gdf["sekou_year"].min()), "-", int(gdf["sekou_year"].max()))

    OUT_DIR.mkdir(exist_ok=True)
    keep = ["SAUID", "SASTYLEID", "sewer_type", "sekou_year", "age", "kanshu",
            "kankei_mm", "dokaburi_up_m", "dokaburi_dn_m", "length_m", "geometry"]
    cleaned = gdf[keep]
    cleaned.to_file(OUT_DIR / "kankyo_cleaned.gpkg", layer="kankyo", driver="GPKG")
    cleaned.to_crs("EPSG:4326").to_file(OUT_DIR / "kankyo_wgs84.geojson", driver="GeoJSON")
    print(f"\nsaved -> {OUT_DIR}")


if __name__ == "__main__":
    main()
