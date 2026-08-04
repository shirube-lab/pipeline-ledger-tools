"""Generate synthetic water-pipe ledger data for the checker demo.

Creates two datasets that mimic a real-world reconciliation task:
- ledger (GeoJSON): the pipe ledger as registered in a GIS system
- survey (CSV): field survey results that should match the ledger

Discrepancies are injected on purpose so that ledger_checker.py has
something to find. All data is synthetic; no real municipality data.
"""

from __future__ import annotations

import random
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

SEED = 42
N_PIPES = 200

MATERIALS = ["DIP", "VP", "CIP", "SP", "PE"]
# Nominal diameters (mm) commonly used for distribution pipes
DIAMETERS = [50, 75, 100, 150, 200, 250, 300, 400]
YEAR_RANGE = (1965, 2024)

# Base coordinate around a fictional city area (JGD2011 / lon-lat)
BASE_LON, BASE_LAT = 137.10, 35.10


def make_ledger(rng: random.Random) -> gpd.GeoDataFrame:
    rows = []
    for i in range(1, N_PIPES + 1):
        lon = BASE_LON + rng.uniform(-0.02, 0.02)
        lat = BASE_LAT + rng.uniform(-0.02, 0.02)
        d_lon = rng.uniform(-0.002, 0.002)
        d_lat = rng.uniform(-0.002, 0.002)
        geom = LineString([(lon, lat), (lon + d_lon, lat + d_lat)])
        rows.append(
            {
                "pipe_id": f"P{i:05d}",
                "install_year": rng.randint(*YEAR_RANGE),
                "material": rng.choice(MATERIALS),
                "diameter_mm": rng.choice(DIAMETERS),
                "length_m": round(rng.uniform(5.0, 120.0), 1),
                "district": rng.choice(["A", "B", "C"]),
                "geometry": geom,
            }
        )
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:6668")

    # Inject ledger-side defects
    gdf.loc[10, "install_year"] = 2035        # future year
    gdf.loc[25, "diameter_mm"] = 0            # invalid diameter
    gdf.loc[40, "length_m"] = -3.0            # negative length
    gdf.loc[55, "material"] = "dip"           # inconsistent notation (lowercase)
    dup = gdf.iloc[[70]].copy()               # duplicated pipe_id
    gdf = pd.concat([gdf, dup], ignore_index=True)
    return gdf


def make_survey(rng: random.Random, ledger: gpd.GeoDataFrame) -> pd.DataFrame:
    survey = ledger.drop(columns="geometry").copy()
    survey = survey.drop_duplicates(subset="pipe_id")

    # Pipes that the survey could not find (missing from survey)
    survey = survey[~survey["pipe_id"].isin(["P00003", "P00017", "P00099"])]

    # Pipes found in the field but absent from the ledger
    extra = pd.DataFrame(
        [
            {"pipe_id": "X90001", "install_year": 1998, "material": "VP",
             "diameter_mm": 75, "length_m": 22.5, "district": "B"},
            {"pipe_id": "X90002", "install_year": 2003, "material": "PE",
             "diameter_mm": 50, "length_m": 14.0, "district": "C"},
        ]
    )
    survey = pd.concat([survey, extra], ignore_index=True)

    # Attribute mismatches against the ledger. Pick a value guaranteed to
    # differ from the current one so every injected mismatch is detectable.
    injections = [
        ("P00008", "material", ["PE", "DIP"]),
        ("P00031", "diameter_mm", [150, 200]),
        ("P00046", "install_year", [1988, 1990]),
    ]
    for pid, col, candidates in injections:
        mask = survey["pipe_id"] == pid
        current = survey.loc[mask, col].iloc[0]
        new_value = candidates[0] if str(candidates[0]) != str(current) else candidates[1]
        survey.loc[mask, col] = new_value

    return survey


def main() -> None:
    rng = random.Random(SEED)
    ledger = make_ledger(rng)
    survey = make_survey(rng, ledger)

    here = Path(__file__).parent
    ledger.to_file(here / "ledger.geojson", driver="GeoJSON")
    survey.to_csv(here / "survey.csv", index=False, encoding="utf-8-sig")
    print(f"ledger.geojson: {len(ledger)} features")
    print(f"survey.csv: {len(survey)} rows")


if __name__ == "__main__":
    main()
