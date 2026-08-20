"""Model upgrade (v2) for the deterioration screening — article #10.

Two reader-review-driven changes, applied stepwise so the before/after of
the rank-A membership can be shown honestly:

  v1    : combined population, C = diameter + shallow cover  (score_priority)
  step1 : same scores, ranks assigned per drainage system (汚水/雨水)
  v2    : consequence gains a trunk-degree term (upstream accumulated
          length), ranks still per system

Trunk degree comes from the pipe network itself:
- endpoints are pre-snapped (99%+ coincide with manholes at 1mm),
- drawing direction matches flow direction on ~98% of testable pipes
  (invert approximation: ground level - cover - diameter falls downstream),
- pipes that run uphill under that approximation are treated as
  drawing-direction errors and flipped before accumulation,
- edges still stuck in cycles get no trunk value (flagged, term = 0).

v1 stays untouched in score_priority.py so article #1's results remain
reproducible. Weights in the v2 consequence are the author's assumptions
(a methods demo), not standard values.
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from score_priority import assign_rank, material_family, rule_based_risk

HERE = Path(__file__).parent
BASE = HERE.parent / "data" / "handa"
OUT = HERE / "output"
CRS = "EPSG:6675"
TOL = 0.01  # endpoint snapping tolerance (m); 99%+ already snap at 1mm

TRUNK_WEIGHT = 0.3   # assumption: trunk term worth up to +0.3 in consequence


def node_key(x: float, y: float) -> tuple[int, int]:
    return (round(x / TOL), round(y / TOL))


def compute_trunk() -> tuple[pd.DataFrame, dict]:
    """Upstream accumulated length per pipe (SAUID), plus validation stats."""
    pipes = gpd.read_file(BASE / "gesui_osui" / "24021" / "24021.shp",
                          encoding="cp932").set_crs(CRS, allow_override=True)
    mh = gpd.read_file(BASE / "gesui_osui" / "24001" / "24001.shp",
                       encoding="cp932").set_crs(CRS, allow_override=True)

    start = pipes.geometry.apply(lambda g: g.coords[0])
    end = pipes.geometry.apply(lambda g: g.coords[-1])
    ks = [node_key(x, y) for x, y in start]
    ke = [node_key(x, y) for x, y in end]
    length = pipes.geometry.length.to_numpy()
    system = np.where(pipes["SASTYLEID"].to_numpy() < 24200, "汚水", "雨水")

    # --- flow-direction check via invert approximation ------------------
    mh_idx = {node_key(g.x, g.y): i for i, g in enumerate(mh.geometry)}
    gl = pd.to_numeric(mh["SAFIELD013"], errors="coerce").to_numpy()
    cov_up = pd.to_numeric(pipes["SAFIELD003"], errors="coerce").to_numpy()
    cov_dn = pd.to_numeric(pipes["SAFIELD004"], errors="coerce").to_numpy()
    cov_up = np.where((cov_up >= 0) & (cov_up <= 15), cov_up, np.nan)
    cov_dn = np.where((cov_dn >= 0) & (cov_dn <= 15), cov_dn, np.nan)
    dia = pd.to_numeric(pipes["SAFIELD002"], errors="coerce").to_numpy() / 1000.0

    s_mh = np.array([mh_idx.get(k, -1) for k in ks])
    e_mh = np.array([mh_idx.get(k, -1) for k in ke])
    on_mh = (s_mh >= 0) & (e_mh >= 0)
    gl_s = np.where(on_mh, gl[np.clip(s_mh, 0, None)], np.nan)
    gl_e = np.where(on_mh, gl[np.clip(e_mh, 0, None)], np.nan)
    testable = (on_mh & np.isfinite(gl_s) & np.isfinite(gl_e)
                & np.isfinite(cov_up) & np.isfinite(cov_dn)
                & np.isfinite(dia) & (dia > 0))
    inv_s = gl_s - cov_up - dia
    inv_e = gl_e - cov_dn - dia
    downhill = testable & (inv_e < inv_s)
    uphill = testable & (inv_e > inv_s)   # treated as drawing-direction error
    # counter-hypothesis (start = downstream, covers swapped) for comparison
    inv_s_swap = gl_s - cov_dn - dia
    inv_e_swap = gl_e - cov_up - dia
    downhill_swap = testable & (inv_e_swap < inv_s_swap)
    # independent check: manhole bottom (ground - manhole depth) also falls
    dep = pd.to_numeric(mh["SAFIELD012"], errors="coerce").to_numpy()
    dep_s = np.where(on_mh, dep[np.clip(s_mh, 0, None)], np.nan)
    dep_e = np.where(on_mh, dep[np.clip(e_mh, 0, None)], np.nan)
    t2 = on_mh & np.isfinite(gl_s) & np.isfinite(gl_e) & np.isfinite(dep_s) & np.isfinite(dep_e)
    bottom_falls = t2 & ((gl_e - dep_e) < (gl_s - dep_s))
    stats = {
        "testable": int(testable.sum()),
        "downhill_rate": float(downhill.sum() / testable.sum()),
        "downhill_rate_swapped": float(downhill_swap.sum() / testable.sum()),
        "mh_bottom_testable": int(t2.sum()),
        "mh_bottom_falls_rate": float(bottom_falls.sum() / t2.sum()),
        "flipped": int(uphill.sum()),
    }

    # --- accumulate per system (Kahn order, UNIQUE upstream edges) --------
    # The network is not a tree: branches re-converge (diamond shapes), so
    # naively adding numbers downstream would double-count shared upstream
    # once per path. Carry the SET of upstream edges (a bitset per node)
    # and sum lengths over the de-duplicated set instead.
    trunk = np.full(len(pipes), np.nan)
    stats["cycle_edges"] = 0
    stats["branch_nodes"] = 0
    for st in ("汚水", "雨水"):
        idx = np.where(system == st)[0]
        pos = {i: p for p, i in enumerate(idx)}       # local bit position
        len_vec = length[idx].astype(np.float64)
        nbits = len(idx)
        nbytes = (nbits + 7) // 8
        out_edges: dict = defaultdict(list)
        indeg: dict = defaultdict(int)
        nodes = set()
        for i in idx:
            a, b = (ke[i], ks[i]) if uphill[i] else (ks[i], ke[i])
            out_edges[a].append((b, i))
            indeg[b] += 1
            nodes.add(a)
            nodes.add(b)
        stats["branch_nodes"] += sum(1 for n in nodes if len(out_edges[n]) >= 2)
        up_set: dict = defaultdict(int)               # node -> bitset of upstream edges
        q = deque(n for n in nodes if indeg[n] == 0)
        while q:
            n = q.popleft()
            mask = up_set.pop(n, 0)
            if mask:
                bits = np.unpackbits(
                    np.frombuffer(mask.to_bytes(nbytes, "little"), dtype=np.uint8),
                    bitorder="little")[:nbits]
                w_n = float(bits @ len_vec)           # unique upstream length at node n
            else:
                w_n = 0.0
            for b, i in out_edges[n]:
                trunk[i] = w_n + length[i]
                up_set[b] |= mask | (1 << pos[i])
                indeg[b] -= 1
                if indeg[b] == 0:
                    q.append(b)
        stats["cycle_edges"] += int(np.isnan(trunk[idx]).sum())

    tbl = pd.DataFrame({"SAUID": pipes["SAUID"], "trunk_m": trunk})
    # 16 rows share a SAUID (known QA finding); keep the larger trunk value
    tbl = (tbl.sort_values("trunk_m", ascending=False)
           .drop_duplicates("SAUID").reset_index(drop=True))
    return tbl, stats


def main() -> None:
    src = HERE / "cleaned" / "kankyo_enriched.gpkg"
    gdf = gpd.read_file(src)
    df = gdf.copy()

    # --- v1 baseline, exactly as score_priority.py does ------------------
    for col in ["dokaburi_up_m", "dokaburi_dn_m"]:
        df[col] = df[col].where(df[col].between(0.0, 15.0))
    df["mat_family"] = df["kanshu"].map(material_family)
    df["age_filled"] = df["age"].astype("Float64")
    med_by_mat = df.groupby("mat_family")["age_filled"].transform("median")
    df["age_imputed"] = df["age_filled"].isna()
    df["age_filled"] = df["age_filled"].fillna(med_by_mat).astype(float)
    df = rule_based_risk(df)
    df = assign_rank(df)
    df = df.rename(columns={"priority_rank": "rank_v1",
                            "consequence": "consequence_v1",
                            "risk_score": "risk_v1"})

    # --- step1: same score, rank within each drainage system -------------
    q = df.groupby("sewer_type", observed=True)["risk_v1"].rank(pct=True)
    df["rank_step1"] = np.select(
        [q >= 0.98, q >= 0.80, q >= 0.50], ["A", "B", "C"], default="D")

    # --- v2: add trunk-degree term to consequence, rank per system -------
    trunk_tbl, net_stats = compute_trunk()
    df = df.merge(trunk_tbl, on="SAUID", how="left")
    df["trunk_unknown"] = df["trunk_m"].isna()
    log_trunk = np.log1p(df["trunk_m"])
    log_max = log_trunk.groupby(df["sewer_type"], observed=True).transform("max")
    df["c_trunk"] = (log_trunk / log_max).fillna(0.0)

    diam = df["kankei_mm"].fillna(df["kankei_mm"].median())
    c_diam = np.clip(diam / 1000.0, 0.15, 1.0)
    shallow = (df["dokaburi_up_m"].fillna(1.5) < 1.0)
    df["consequence_v2"] = np.clip(
        c_diam + shallow * 0.2 + TRUNK_WEIGHT * df["c_trunk"], 0.0, 1.0)
    df["risk_v2"] = (df["p_deterioration"] * df["consequence_v2"]).round(4)
    q2 = df.groupby("sewer_type", observed=True)["risk_v2"].rank(pct=True)
    df["rank_v2"] = np.select(
        [q2 >= 0.98, q2 >= 0.80, q2 >= 0.50], ["A", "B", "C"], default="D")

    # --- double risk under each model -------------------------------------
    SOFT_TERRAIN = {"干拓地", "埋立地", "三角州・海岸低地", "谷底低地",
                    "旧河道・旧池沼", "後背湿地", "砂丘・砂州間低地"}
    df["soft_ground"] = df["terrain_name"].isin(SOFT_TERRAIN)
    df["double_risk_v1"] = (df["rank_v1"] == "A") & df["soft_ground"]
    df["double_risk_v2"] = (df["rank_v2"] == "A") & df["soft_ground"]

    # --- report -----------------------------------------------------------
    print("=== network / flow-direction stats ===")
    print(f"testable pipes: {net_stats['testable']:,} "
          f"(downhill under drawing direction: {net_stats['downhill_rate']:.1%}, "
          f"counter-hypothesis(swapped covers): {net_stats['downhill_rate_swapped']:.1%})")
    print(f"independent check — manhole bottom falls along drawing dir: "
          f"{net_stats['mh_bottom_falls_rate']:.1%} of {net_stats['mh_bottom_testable']:,}")
    print(f"flipped as drawing-direction errors: {net_stats['flipped']:,}")
    print(f"edges left in cycles (trunk unknown): {net_stats['cycle_edges']:,} "
          f"({net_stats['cycle_edges'] / len(gdf):.1%})")
    known = df[~df["trunk_unknown"]]
    for st, sub in known.groupby("sewer_type", observed=True):
        print(f"trunk[{st}]: max {sub['trunk_m'].max() / 1000:.1f} km, "
              f"p99 {sub['trunk_m'].quantile(0.99) / 1000:.1f} km, "
              f"median {sub['trunk_m'].median():.0f} m "
              f"(系統総延長 {df.loc[df['sewer_type'] == st, 'length_m'].sum() / 1000:.1f} km)")
    big = known[known["trunk_m"] > 10_000]
    print(f"trunk>10km: {len(big)} 本, 管径中央値 {big['kankei_mm'].median():.0f}mm "
          f"(全体の管径中央値 {df['kankei_mm'].median():.0f}mm)")

    print("\n=== rank-A composition: v1 -> step1 -> v2 ===")
    for name, col in [("v1", "rank_v1"), ("step1", "rank_step1"), ("v2", "rank_v2")]:
        a = df[df[col] == "A"]
        by_sys = a["sewer_type"].value_counts().to_dict()
        by_mat = a["mat_family"].value_counts().head(3).to_dict()
        print(f"{name}: A={len(a)} 本 / {a['length_m'].sum() / 1000:.1f} km | "
              f"系統 {by_sys} | 管種上位 {by_mat} | "
              f"管径中央値 {a['kankei_mm'].median():.0f}mm | "
              f"幹線度中央値 {a['trunk_m'].median() / 1000 if a['trunk_m'].notna().any() else float('nan'):.2f}km")

    print("\n=== migration v1 -> v2 (本数) ===")
    mig = pd.crosstab(df["rank_v1"], df["rank_v2"])
    print(mig.to_string())
    entered = ((df["rank_v2"] == "A") & (df["rank_v1"] != "A")).sum()
    left = ((df["rank_v1"] == "A") & (df["rank_v2"] != "A")).sum()
    stayed = ((df["rank_v1"] == "A") & (df["rank_v2"] == "A")).sum()
    print(f"A stayed {stayed}, left {left}, entered {entered}")

    d1, d2 = df["double_risk_v1"], df["double_risk_v2"]
    print(f"\ndouble risk: v1 {d1.sum()} 本 -> v2 {d2.sum()} 本 "
          f"(共通 {(d1 & d2).sum()}, 出 {(d1 & ~d2).sum()}, 入 {(~d1 & d2).sum()})")

    OUT.mkdir(exist_ok=True)
    mig.to_csv(OUT / "rank_migration_v1_v2.csv", encoding="utf-8-sig")
    keep = ["SAUID", "sewer_type", "sekou_year", "age_filled", "age_imputed",
            "kanshu", "mat_family", "kankei_mm", "dokaburi_up_m", "length_m",
            "p_deterioration", "consequence_v1", "risk_v1", "rank_v1",
            "trunk_m", "trunk_unknown", "c_trunk", "consequence_v2",
            "risk_v2", "rank_step1", "rank_v2", "terrain_name",
            "soft_ground", "double_risk_v1", "double_risk_v2", "geometry"]
    keep = [c for c in keep if c in df.columns or c == "geometry"]
    gpd.GeoDataFrame(df[keep], crs=gdf.crs).to_file(
        OUT / "priority_result_v2.gpkg", layer="priority_v2", driver="GPKG")
    print(f"\nsaved -> {OUT / 'priority_result_v2.gpkg'}")


if __name__ == "__main__":
    main()
