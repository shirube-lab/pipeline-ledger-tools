"""Generate a synthetic TV-camera survey dataset for the urgency demo.

Story link to work3: the screening in work3 ranked spans by risk; here
we pretend the top-priority spans (rank A) were actually surveyed. The
span list and geometry come from the real Handa open data via work3's
output, but EVERY defect record is synthetic — no real inspection data
exists in the Handa open data, and none is implied.

Scenario mix is seeded and covers every rule the engine implements:
immediate-A specials, rate boundaries, same-location duplicates,
c-only spans and clean spans.

Outputs (into this folder):
    span_master.csv     surveyed spans (from work3 rank-A, RC/陶管 only)
    defect_records.csv  synthetic defect records
    span_geoms.gpkg     span geometries (EPSG:6675) for the map
"""

from __future__ import annotations

import random
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).parent
WORK3_RESULT = HERE.parent / "work3-deterioration" / "output" / "priority_result.gpkg"

SEED = 42
N_SPANS = 60
STD_PIPE_LEN = {"rc": 2.43, "ceramic": 1.0}  # nominal segment length (m), assumption for the demo
MATERIAL_MAP = {"ヒューム管": "rc", "陶管": "ceramic"}

# Pipe-level items available for random fill (rank restrictions per H21 表2.3)
FILL_ITEMS = {
    "rc": {"クラック": ["a", "b", "c"], "浸入水": ["a", "b", "c"], "破損": ["b", "c"],
           "継手ズレ": ["b", "c"], "モルタル付着": ["a", "b", "c"], "樹木根侵入": ["a", "b"]},
    "ceramic": {"クラック": ["a", "b"], "浸入水": ["a", "b", "c"], "破損": ["b"],
                "継手ズレ": ["b", "c"], "モルタル付着": ["a", "b", "c"], "樹木根侵入": ["a", "b"]},
}


def load_spans() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(WORK3_RESULT)
    a = gdf[(gdf["priority_rank"] == "A")
            & (gdf["mat_family"].isin(MATERIAL_MAP))
            & (gdf["kankei_mm"] <= 3000)].copy()  # たるみ基準の対象は内径3,000mm以下
    a["material"] = a["mat_family"].map(MATERIAL_MAP)
    a = a.sort_values("risk_score", ascending=False)
    # Keep every ceramic span (they are few) so the 陶管-specific criteria
    # actually appear in the demo, then fill up with the top RC spans.
    ceramic = a[a["material"] == "ceramic"]
    rc = a[a["material"] == "rc"].head(N_SPANS - len(ceramic))
    a = pd.concat([rc, ceramic]).sort_values("risk_score", ascending=False).reset_index(drop=True)
    a["n_pipes"] = [
        max(1, round(l / STD_PIPE_LEN[m])) for l, m in zip(a["length_m"], a["material"])
    ]
    return a


def add_pipe_defect(rows: list, span_id, pipe_no: int, item: str, rank: str,
                    rng: random.Random, note: str = "") -> None:
    rows.append({"span_id": span_id, "pipe_no": pipe_no,
                 "distance_m": round(pipe_no * 2.0 + rng.uniform(0, 1.5), 1),
                 "item": item, "rank": rank, "note": note})


def add_span_defect(rows: list, span_id, item: str, rank: str, note: str = "") -> None:
    rows.append({"span_id": span_id, "pipe_no": None, "distance_m": None,
                 "item": item, "rank": rank, "note": note})


def random_fill(rows: list, span, rng: random.Random, n_defects: int,
                ranks: list[str]) -> None:
    """Scatter n random defects of the given ranks over distinct pipes."""
    items = FILL_ITEMS[span.material]
    pipe_nos = rng.sample(range(1, span.n_pipes + 1), min(n_defects, span.n_pipes))
    for no in pipe_nos:
        rank = rng.choice(ranks)
        candidates = [i for i, rk in items.items() if rank in rk and i not in ("破損", "継手ズレ")]
        add_pipe_defect(rows, span.span_id, no, rng.choice(candidates), rank, rng)


def build_defects(spans: pd.DataFrame, rng: random.Random) -> pd.DataFrame:
    rows: list[dict] = []
    for i, span in spans.iterrows():
        sid, n = span.span_id, span.n_pipes
        scenario = i % 10

        if scenario == 0:
            # Immediate-A special + corrosion A -> two A items -> urgency I
            add_pipe_defect(rows, sid, rng.randint(1, n), "破損", "a", rng,
                            "軸方向クラック幅5mm超(合成)")
            add_span_defect(rows, sid, "腐食", "A")
        elif scenario == 1:
            # Immediate-A special alone -> urgency II
            add_pipe_defect(rows, sid, rng.randint(1, n), "継手ズレ", "a", rng, "脱却(合成)")
            random_fill(rows, span, rng, max(1, n // 10), ["c"])
        elif scenario == 2:
            # High a-rate (>=20%) + sag B -> A + B ... urgency II or I
            for no in rng.sample(range(1, n + 1), max(1, round(n * 0.25))):
                add_pipe_defect(rows, sid, no, "クラック", "a", rng)
            add_span_defect(rows, sid, "たるみ", "B")
        elif scenario == 3:
            # Exact 20% a-rate boundary (works when n divisible by 5, else ~20%)
            k = max(1, round(n * 0.2))
            for no in rng.sample(range(1, n + 1), k):
                add_pipe_defect(rows, sid, no, "浸入水", "a", rng)
        elif scenario == 4:
            # Same-location duplicate (crack-a + infiltration-b at one spot)
            no = rng.randint(1, n)
            d = round(no * 2.0, 1)
            rows.append({"span_id": sid, "pipe_no": no, "distance_m": d,
                         "item": "クラック", "rank": "a", "note": "同一箇所テスト(合成)"})
            rows.append({"span_id": sid, "pipe_no": no, "distance_m": d,
                         "item": "浸入水", "rank": "b", "note": "同一箇所テスト(合成)"})
            add_span_defect(rows, sid, "腐食", "B")
        elif scenario == 5:
            # b-rank defects only -> rate B; corrosion B -> B×2 -> urgency II
            random_fill(rows, span, rng, max(2, n // 5), ["b"])
            add_span_defect(rows, sid, "腐食", "B")
        elif scenario == 6:
            # c-only, >=60% -> rate B alone -> urgency III... (B×1)
            k = max(1, round(n * 0.65))
            for no in rng.sample(range(1, n + 1), min(k, n)):
                add_pipe_defect(rows, sid, no, "モルタル付着", "c", rng)
        elif scenario == 7:
            # c-only, sparse -> rate C -> urgency III
            random_fill(rows, span, rng, max(1, n // 8), ["c"])
        elif scenario == 8:
            # Span-level only: sag C -> urgency III
            add_span_defect(rows, sid, "たるみ", "C")
        else:
            pass  # clean span -> 異常なし

    return pd.DataFrame(rows, columns=["span_id", "pipe_no", "distance_m", "item", "rank", "note"])


def main() -> None:
    rng = random.Random(SEED)
    spans = load_spans()

    master = pd.DataFrame({
        "span_id": spans["SAUID"],
        "mh_up": [f"MH{sid}U" for sid in spans["SAUID"]],
        "mh_down": [f"MH{sid}D" for sid in spans["SAUID"]],
        "material": spans["material"],
        "material_name": spans["material"].map({v: k for k, v in MATERIAL_MAP.items()}),
        "diameter_mm": spans["kankei_mm"].astype(int),
        "length_m": spans["length_m"].round(2),
        "n_pipes": spans["n_pipes"],
        "sekou_year": spans["sekou_year"].astype("Int64"),
    })
    master = master.rename(columns={"span_id": "span_id"})
    spans = spans.assign(span_id=spans["SAUID"])

    defects = build_defects(master.assign(span_id=master["span_id"]), rng)

    master.to_csv(HERE / "span_master.csv", index=False, encoding="utf-8-sig")
    defects.to_csv(HERE / "defect_records.csv", index=False, encoding="utf-8-sig")
    geoms = gpd.GeoDataFrame(
        {"span_id": spans["span_id"], "risk_score": spans["risk_score"],
         "sekou_year": spans["sekou_year"], "kankei_mm": spans["kankei_mm"]},
        geometry=spans.geometry, crs=spans.crs,
    )
    geoms.to_file(HERE / "span_geoms.gpkg", layer="spans", driver="GPKG")

    print(f"span_master.csv: {len(master)} spans "
          f"(rc={sum(master.material == 'rc')}, ceramic={sum(master.material == 'ceramic')})")
    print(f"defect_records.csv: {len(defects)} records (all synthetic)")
    print(f"span_geoms.gpkg: {len(geoms)} geometries")


if __name__ == "__main__":
    main()
