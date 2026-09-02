"""How much of the "重要管路" definition can a ledger actually decide by itself?

The 中間整理 (令和8年1月) of the 下水道管路マネジメントのための技術基準等検討会
splits every sewer into 重要管路 and 枝線, and gives 重要管路 four conditions
(printed p.11):

  (1) 下水処理場～処理場直前の最終合流地点までの管路
  (2) 流域下水道の管路
  (3) 管径２ｍ相当以上の大口径管路
  (4) 緊急輸送道路下、軌道下、河川下の管路

This script writes each condition as code against a real municipal ledger
(半田市 open data) and records, for each one, what the ledger can decide and
what it cannot. The output is deliberately two-sided: the extracted pipes AND
the information that had to come from outside the ledger.

Nothing here labels a pipe as 重要管路 in an official sense. The conditions are
from an interim report, the regime is not in force yet, and three of the four
conditions need information this ledger does not carry.

Outputs (output/):
  cond3_large_diameter.csv  条件(3)で拾える管きょ
  cond1_trunk_runs.csv      条件(1)を有向グラフで解いた結果(末端ごと)
  cond4_road_candidates.csv 条件(4)の候補(台帳の道路管理者名で絞ったもの)
  cond4_rail_pipes.csv      条件(4)のうち軌道下(N02 鉄道データとの空間照合)
  pipe_sizes.csv            全管きょの口径・延長(記事の図の入力)
  summary.json              記事で使う数値
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
BASE = HERE.parent / "data" / "handa"
OUT = HERE / "output"
CRS = "EPSG:6675"          # JGD2011 平面直角座標系第Ⅶ系(記事 1 で検証済み)
TOL = 0.01                 # 端点スナップの許容差(m)

DIA_MM = 2000              # 条件(3)「管径２ｍ相当以上」を呼び径 2000mm 以上と解釈
COVER_MAX = 15.0           # 土被りの実在範囲(これを外れる値は欠測扱い)

# 条件(4)のうち台帳だけで絞れる部分。緊急輸送道路の指定路線そのものは台帳に無いが、
# マンホールの「道路管理者名」は入っている。緊急輸送道路は国道・県道が中心なので、
# 市道以外の管理者を候補として残す(= 判定ではなく候補の絞り込み)。
NON_CITY_ROAD = {"愛知県", "建設省", "国土交通省"}


def node_key(x: float, y: float) -> tuple[int, int]:
    return (round(x / TOL), round(y / TOL))


def as_text(series: pd.Series) -> pd.Series:
    """Text column as plain str, with every flavour of "missing" becoming "".

    Needed because this distribution is not consistent about it: 道路管理者名
    arrives as empty strings while 下水道区分名 arrives as pd.NA, and pyogrio
    hands back a StringDtype where astype(str) leaves NA as NA (so a naive
    `!= ""` test counts missing values as filled).
    """
    return (series.astype("string").fillna("").astype(str).str.strip()
            .replace({"nan": "", "None": "", "<NA>": ""}))


def load() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    pipes = gpd.read_file(BASE / "gesui_osui" / "24021" / "24021.shp",
                          encoding="cp932").set_crs(CRS, allow_override=True)
    mh = gpd.read_file(BASE / "gesui_osui" / "24001" / "24001.shp",
                       encoding="cp932").set_crs(CRS, allow_override=True)
    pipes["system"] = np.where(pipes["SASTYLEID"].to_numpy() < 24200, "汚水", "雨水")
    pipes["length_m"] = pipes.geometry.length
    pipes["dia_mm"] = pd.to_numeric(pipes["SAFIELD002"], errors="coerce")
    pipes["material"] = pipes["SAFIELD001"].astype(str).str.strip()
    pipes["year"] = pd.to_numeric(
        pipes["SAFIELD000"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce")
    return pipes, mh


def flow_direction(pipes: gpd.GeoDataFrame, mh: gpd.GeoDataFrame):
    """Node keys per end, plus a mask of pipes drawn against the flow.

    Same invert approximation as work3 (article 9): ground level - cover -
    diameter should fall from the start node to the end node. Pipes that run
    uphill under it are treated as drawing-direction errors and flipped.
    """
    ks = [node_key(*g.coords[0]) for g in pipes.geometry]
    ke = [node_key(*g.coords[-1]) for g in pipes.geometry]
    mh_idx = {node_key(g.x, g.y): i for i, g in enumerate(mh.geometry)}
    gl = pd.to_numeric(mh["SAFIELD013"], errors="coerce").to_numpy()

    def cover(col: str) -> np.ndarray:
        v = pd.to_numeric(pipes[col], errors="coerce").to_numpy()
        return np.where((v >= 0) & (v <= COVER_MAX), v, np.nan)

    cov_up, cov_dn = cover("SAFIELD003"), cover("SAFIELD004")
    dia = pipes["dia_mm"].to_numpy() / 1000.0
    s_i = np.array([mh_idx.get(k, -1) for k in ks])
    e_i = np.array([mh_idx.get(k, -1) for k in ke])
    on = (s_i >= 0) & (e_i >= 0)
    gl_s = np.where(on, gl[np.clip(s_i, 0, None)], np.nan)
    gl_e = np.where(on, gl[np.clip(e_i, 0, None)], np.nan)
    testable = (on & np.isfinite(gl_s) & np.isfinite(gl_e) & np.isfinite(cov_up)
                & np.isfinite(cov_dn) & np.isfinite(dia) & (dia > 0))
    inv_s, inv_e = gl_s - cov_up - dia, gl_e - cov_dn - dia
    uphill = testable & (inv_e > inv_s)
    stats = {
        "testable": int(testable.sum()),
        "agrees_with_drawing_direction": int((testable & (inv_e < inv_s)).sum()),
        "flipped": int(uphill.sum()),
        "equal_invert": int((testable & (inv_e == inv_s)).sum()),
    }
    return ks, ke, uphill, stats


def components(idx: np.ndarray, ks: list, ke: list, length: np.ndarray) -> list[dict]:
    """Undirected connected components of a subset of pipes, largest first."""
    adj: dict = defaultdict(list)
    nodes: set = set()
    for i in idx:
        adj[ks[i]].append((ke[i], i))
        adj[ke[i]].append((ks[i], i))
        nodes.add(ks[i])
        nodes.add(ke[i])
    seen: set = set()
    out: list[dict] = []
    for n in nodes:
        if n in seen:
            continue
        q, edges, members = deque([n]), set(), [n]
        seen.add(n)
        while q:
            u = q.popleft()
            for v, i in adj[u]:
                edges.add(i)
                if v not in seen:
                    seen.add(v)
                    members.append(v)
                    q.append(v)
        out.append({"length_m": float(sum(length[i] for i in edges)),
                    "pipes": len(edges), "nodes": members})
    return sorted(out, key=lambda c: -c["length_m"])


def condition3(pipes: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict]:
    """(3) 管径２ｍ相当以上 — the one condition that is a plain attribute filter.

    Plain, but not unambiguous. The 中間整理 says 「管径２ｍ相当以上」 and never
    defines 相当; the word was not there at the 第3回 stage (「管径２ｍ以上」).
    大阪市 runs the national special inspection with a cross-section-AREA rule
    (non-circular pipes count when their area matches a φ2000 circle), other
    bodies publish 「内径2m以上」 with no rule for non-circular sections at all.
    Deciding between those readings needs 断面形状 and 内空高, and this ledger's
    管きょ has neither — its one size column is literally named 管径１(mm) 径/幅,
    i.e. diameter OR width. So the filter is reported with the threshold swept,
    not as a single number.
    """
    big = pipes[pipes["dia_mm"] >= DIA_MM].copy()
    sweep = {}
    for t in (1500, 1800, 2000, 2200, 2500):
        sub = pipes[pipes["dia_mm"] >= t]
        sweep[f">= {t} mm"] = {"n": int(len(sub)),
                               "length_km": round(float(sub["length_m"].sum()) / 1000, 2)}
    blank = pipes["dia_mm"].isna()
    info = {
        "n": int(len(big)),
        "length_km": round(float(big["length_m"].sum()) / 1000, 2),
        "by_system": {str(k): {"n": int(len(v)),
                               "length_km": round(float(v["length_m"].sum()) / 1000, 2)}
                      for k, v in big.groupby("system")},
        "threshold_sweep": sweep,
        # 口径が空欄なら、この条件はそもそも判定できない
        "undecidable_blank_diameter": {
            "n": int(blank.sum()),
            "length_km": round(float(pipes.loc[blank, "length_m"].sum()) / 1000, 2),
            "share_of_length": round(float(pipes.loc[blank, "length_m"].sum())
                                     / float(pipes["length_m"].sum()), 4),
        },
        "material_mix": {str(k): int(v) for k, v in big["material"].value_counts().items()},
        # 全国特別重点調査(令和7年3月要請)の対象は「内径2m以上かつ 1994 年度以前に
        # 設置・改築」。重要管路の定義とは別基準なので、参考として分けて数える。
        "year_missing": int(big["year"].isna().sum()),
        "year_known": int(big["year"].notna().sum()),
        "installed_1994_or_earlier_of_known": int((big["year"] <= 1994).sum()),
        "diameter_column_is_ambiguous":
            "管径１(mm) 径/幅 — 円形の径と矩形の幅を兼ねる 1 列。断面形状・内空高さの列は無い",
    }
    cols = ["SAUID", "system", "dia_mm", "material", "year", "length_m"]
    return big[cols].sort_values("dia_mm", ascending=False), info


def condition1(pipes, mh, ks, ke, uphill) -> tuple[pd.DataFrame, dict]:
    """(1) 処理場～処理場直前の最終合流地点 — a graph walk, not a filter.

    Read literally, the condition is not "everything upstream of the plant";
    it is the run between the plant and the LAST place where flows merge
    before it. On a directed graph that is: start at a terminal node, walk
    upstream while the node has exactly one incoming pipe, stop at the first
    node with two or more.

    The ledger has no treatment-plant layer, so we cannot say which terminal
    is the plant. We therefore solve the walk for EVERY terminal and report
    the distribution — the geometry of the condition is decidable, the anchor
    is not.
    """
    length = pipes["length_m"].to_numpy()
    idx = np.where((pipes["system"] == "汚水").to_numpy())[0]
    out_e: dict = defaultdict(list)
    in_e: dict = defaultdict(list)
    nodes: set = set()
    for i in idx:
        a, b = (ke[i], ks[i]) if uphill[i] else (ks[i], ke[i])
        out_e[a].append((b, i))
        in_e[b].append((a, i))
        nodes.add(a)
        nodes.add(b)

    # Sensitivity: how much of the terminal count is an artefact of the
    # direction correction? Count terminals under the raw drawing direction too.
    raw_out: dict = defaultdict(list)
    raw_nodes: set = set()
    for i in idx:
        raw_out[ks[i]].append(i)
        raw_nodes.add(ks[i])
        raw_nodes.add(ke[i])
    terminals_raw = sum(1 for n in raw_nodes if not raw_out[n])

    sinks = [n for n in nodes if not out_e[n]]
    rows = []
    for s in sinks:
        run, node, seen = [], s, {s}
        while len(in_e[node]) == 1:          # 合流していない間だけ遡る
            up, i = in_e[node][0]
            run.append(i)
            if up in seen:                   # 万一の閉路
                break
            seen.add(up)
            node = up
        rows.append({
            "sink_x": s[0] * TOL, "sink_y": s[1] * TOL,
            "sink_indegree": len(in_e[s]),
            "run_pipes": len(run),
            "run_length_m": round(float(sum(length[i] for i in run)), 1),
            "stopped_at_indegree": len(in_e[node]),
        })
    df = pd.DataFrame(rows).sort_values("run_length_m", ascending=False)
    comps = components(idx, ks, ke, length)
    total_m = sum(c["length_m"] for c in comps)
    nonzero = df.loc[df["run_length_m"] > 0, "run_length_m"]

    # Why the graph is not one piece: each 処理分区 connects to the prefecture's
    # 流域下水道 trunk on its own, and that trunk is not in the city's ledger.
    # Showing the dominant 処理分区 per component tests that reading directly.
    district = {node_key(g.x, g.y): d
                for g, d in zip(mh.geometry, as_text(mh["SAFIELD005"]))}
    top = []
    for c in comps[:6]:
        names = pd.Series([district.get(n, "") for n in c["nodes"]])
        names = names[names != ""]
        share = float(names.value_counts(normalize=True).iloc[0]) if len(names) else float("nan")
        top.append({
            "length_km": round(c["length_m"] / 1000, 2),
            "pipes": c["pipes"],
            "dominant_district": names.value_counts().index[0] if len(names) else "(不明)",
            "dominant_share": round(share, 3),
        })

    # 連結の欠落がスナップ精度の問題でないことを、公開スクリプトの側で示す
    snap_sweep = {}
    for tol in (0.01, 0.1, 0.5, 1.0, 2.0):
        def key(c, t=tol):
            return (round(c[0] / t), round(c[1] / t))
        ks_t = [key(g.coords[0]) for g in pipes.geometry.iloc[idx]]
        ke_t = [key(g.coords[-1]) for g in pipes.geometry.iloc[idx]]
        local = np.arange(len(idx))
        cs = components(local, ks_t, ke_t, length[idx])
        snap_sweep[f"{tol:g} m"] = {
            "components": len(cs),
            "largest_share": round(cs[0]["length_m"] / sum(c["length_m"] for c in cs), 3),
        }

    # 分区と成分は 1 対 1 ではない。どの分区がいくつの成分に割れているかも出す
    per_district: dict = defaultdict(list)
    for c in comps:
        names = pd.Series([district.get(n, "") for n in c["nodes"]])
        names = names[names != ""]
        if len(names):
            per_district[names.value_counts().index[0]].append(c["length_m"] / 1000)
    split = {d: {"components": len(v), "total_km": round(sum(v), 2),
                 "largest_km": [round(x, 2) for x in sorted(v, reverse=True)[:4]]}
             for d, v in sorted(per_district.items(), key=lambda x: -sum(x[1]))}

    info = {
        "pipes": int(len(idx)),
        "nodes": int(len(nodes)),
        "snap_tolerance_sweep": snap_sweep,
        "components_per_district": split,
        "terminals": int(len(sinks)),
        "terminals_raw_drawing_direction": int(terminals_raw),
        "terminals_already_at_a_confluence": int((df["sink_indegree"] >= 2).sum()),
        "run_length_m_max": float(df["run_length_m"].max()),
        "run_length_m_median": float(df["run_length_m"].median()),
        "run_length_m_median_nonzero": round(float(nonzero.median()), 1),
        "run_length_m_total": round(float(df["run_length_m"].sum()), 1),
        "run_share_of_network": round(float(df["run_length_m"].sum())
                                      / float(length[idx].sum()), 4),
        "components": len(comps),
        "largest_component_share": round(comps[0]["length_m"] / total_m, 3),
        # 成分「数」より、延長がどこに集まっているかのほうが実態を表す
        "top6_share_of_length": round(sum(c["length_m"] for c in comps[:6]) / total_m, 3),
        "rest_components": len(comps) - 6,
        "rest_components_km": round(sum(c["length_m"] for c in comps[6:]) / 1000, 2),
        "top_components": top,
    }
    return df, info


def condition2(mh: gpd.GeoDataFrame) -> dict:
    """(2) 流域下水道の管路 — what the ledger's own 下水道区分名 says.

    A 流域関連公共下水道 city owns the collector network; the 流域下水道 trunk
    itself belongs to the prefecture, so it is not expected to appear in the
    city's ledger at all. Reporting the field's own values (and how often it
    is filled) is the honest form of this condition: the ledger answers "not
    here", not "none exists".
    """
    v = as_text(mh["SAFIELD003"])
    counts = {(k if k else "(空欄)"): int(n)
              for k, n in v.replace("", "(空欄)").value_counts().items()}
    return {"下水道区分名": counts, "filled_rate": round(float((v != "").mean()), 3)}


def condition4(pipes, mh, ks, ke) -> tuple[pd.DataFrame, dict]:
    """(4) 緊急輸送道路下・軌道下・河川下 — needs outside data, but not from zero.

    The designation itself is not in the ledger. The road ADMINISTRATOR is:
    every manhole carries 道路管理者名. Emergency transport routes are drawn
    mostly from national and prefectural roads, so pipes whose manholes sit on
    a non-city road are the candidates worth checking against the designation.
    This narrows the field; it does not decide it. City roads are designated
    in some municipalities, and not every prefectural road is.
    """
    admin = as_text(mh["SAFIELD016"])
    road = {node_key(g.x, g.y): a for g, a in zip(mh.geometry, admin)}
    s_road = np.array([road.get(k, "") for k in ks])
    e_road = np.array([road.get(k, "") for k in ke])
    admins = list(NON_CITY_ROAD)
    both = np.isin(s_road, admins) & np.isin(e_road, admins)
    either = np.isin(s_road, admins) | np.isin(e_road, admins)
    # Blank at either end means "unknown", not "city road": those pipes stay
    # candidates too, so the narrowed set is a lower bound.
    unknown = ((s_road == "") | (e_road == "")) & ~either
    cand = pipes[both].copy()
    cand["road_up"], cand["road_dn"] = s_road[both], e_road[both]
    info = {
        "manholes": int(len(mh)),
        "road_admin_filled_rate": round(float((admin != "").mean()), 3),
        "manholes_by_admin": {(k if k else "(空欄)"): int(n) for k, n
                              in admin.replace("", "(空欄)").value_counts().items()},
        "pipes_both_ends_non_city": int(both.sum()),
        "pipes_either_end_non_city": int(either.sum()),
        "pipes_with_an_unknown_end": int(unknown.sum()),
        "length_km_both_ends": round(float(pipes.loc[both, "length_m"].sum()) / 1000, 2),
        "length_km_either_end": round(float(pipes.loc[either, "length_m"].sum()) / 1000, 2),
        "length_km_unknown": round(float(pipes.loc[unknown, "length_m"].sum()) / 1000, 2),
        "share_of_all_pipes": round(float(both.sum()) / len(pipes), 4),
    }
    cols = ["SAUID", "system", "dia_mm", "road_up", "road_dn", "length_m"]
    return cand[cols].sort_values("length_m", ascending=False), info


def condition4_rail(pipes: gpd.GeoDataFrame) -> tuple[pd.DataFrame | None, dict]:
    """(4) の「軌道下」だけは、商用利用できる公開データで実装できる。

    N02(鉄道データ)は 2020 年度版以降 CC BY 4.0 で、軌道の中心線を線データで
    持っている。中心線からの距離でバッファを取り、交差する管きょを拾う。

    バッファ幅は軌道敷の幅の代用で、正確な鉄道用地界ではない。だから幅を振った
    感度も一緒に出す。緊急輸送道路下・河川下が同じようにできない理由は README と
    記事に書いたとおり(N10 は非商用、W05 も非商用、河川区域界は基盤地図情報でも
    未整備)。
    """
    zip_path = BASE.parent / "env" / "N02-24_GML.zip"
    if not zip_path.exists():
        return None, {"skipped": "N02-24_GML.zip が無い(data/env/setup_env_data.py を実行)"}
    rail = gpd.read_file(f"zip://{zip_path}!UTF-8/N02-24_RailroadSection.shp",
                         encoding="utf-8")
    extent = pipes.to_crs(rail.crs).union_all().convex_hull.buffer(0.006)  # ≈600m
    near = rail[rail.intersects(extent)].to_crs(CRS)

    # 「軌道下」の芯は横断です。中心線そのものと交差する管きょ = 軌道の下を通る管。
    # バッファはあくまで軌道敷幅の代用で、広げるほど「軌道沿いを並走する管」を
    # 巻き込むので、幅を振った感度として別に出します。
    center = near.geometry.union_all()
    crosses = pipes.geometry.intersects(center)
    # extent は「管路を N02 と同じ地理座標系に移し、凸包を約 600m 広げた領域」。
    # 触れた区間の全長と、extent でクリップした延長は別物なので両方出す。
    clipped = near.clip(gpd.GeoSeries([extent], crs=rail.crs).to_crs(CRS).iloc[0])
    info = {
        "rail_sections_in_extent": int(len(near)),
        "lines_km_touching_extent": {str(n): round(float(p.geometry.length.sum()) / 1000, 2)
                                     for n, p in near.groupby("N02_003")},
        "lines_km_clipped_to_extent": {str(n): round(float(p.geometry.length.sum()) / 1000, 2)
                                       for n, p in clipped.groupby("N02_003")},
        "crossing_centreline": {
            "n": int(crosses.sum()),
            "length_km": round(float(pipes.loc[crosses, "length_m"].sum()) / 1000, 2),
            "by_line": {},
        },
        "buffer_sweep": {},
    }
    for name, part in near.groupby("N02_003"):
        m = pipes.geometry.intersects(part.geometry.union_all())
        info["crossing_centreline"]["by_line"][str(name)] = int(m.sum())
    for width in (5.0, 10.0, 20.0):
        m = pipes.geometry.intersects(near.geometry.buffer(width).union_all())
        info["buffer_sweep"][f"buffer {width:g} m"] = {
            "n": int(m.sum()),
            "length_km": round(float(pipes.loc[m, "length_m"].sum()) / 1000, 2),
        }
    hit = pipes[crosses].copy()
    cols = ["SAUID", "system", "dia_mm", "material", "length_m"]
    return hit[cols].sort_values("length_m", ascending=False), info


def main() -> None:
    # The console on a Japanese Windows is cp932; the report text is not.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(exist_ok=True)
    pipes, mh = load()
    ks, ke, uphill, dir_stats = flow_direction(pipes, mh)
    # 条件(1) は汚水管きょだけで解くので、その部分集合での内訳も別に残す
    # (全体の内訳をそのまま汚水の話に使うと、分母がずれる)
    _, _, _, dir_stats["汚水のみ"] = flow_direction(
        pipes[pipes["system"] == "汚水"], mh)

    c3, i3 = condition3(pipes)
    c1, i1 = condition1(pipes, mh, ks, ke, uphill)
    i2 = condition2(mh)
    c4, i4 = condition4(pipes, mh, ks, ke)
    c4r, i4r = condition4_rail(pipes)

    c3.to_csv(OUT / "cond3_large_diameter.csv", index=False, encoding="utf-8-sig")
    c1.to_csv(OUT / "cond1_trunk_runs.csv", index=False, encoding="utf-8-sig")
    c4.to_csv(OUT / "cond4_road_candidates.csv", index=False, encoding="utf-8-sig")
    if c4r is not None:
        c4r.to_csv(OUT / "cond4_rail_pipes.csv", index=False, encoding="utf-8-sig")
    # full size distribution, so the article figures read tool output only
    pipes[["SAUID", "system", "dia_mm", "year", "length_m"]].to_csv(
        OUT / "pipe_sizes.csv", index=False, encoding="utf-8-sig")

    # 条件どうしは重なります。「機械で決められた集合」と「候補どまりの集合」は
    # 分けて数えないと、候補を足し込んだ数字が独り歩きします。
    def km(ids: set) -> float:
        return round(float(pipes.loc[pipes["SAUID"].isin(ids), "length_m"].sum()) / 1000, 2)

    s3 = set(c3["SAUID"])
    s4rail = set(c4r["SAUID"]) if c4r is not None else set()
    s4road = set(c4["SAUID"])
    decided = s3 | s4rail
    overlap = {
        "decided(条件3 ∪ 条件4軌道下)": {"n": len(decided), "length_km": km(decided)},
        "candidates_only(条件4 道路管理者)": {"n": len(s4road - decided),
                                            "length_km": km(s4road - decided)},
        "条件3 ∩ 条件4軌道下": len(s3 & s4rail),
        "decided_share_of_network": round(km(decided) / (pipes["length_m"].sum() / 1000), 4),
    }

    summary = {
        "ledger": {
            "pipes": int(len(pipes)),
            "length_km": round(float(pipes["length_m"].sum()) / 1000, 1),
            "by_system": {str(k): {"n": int(len(v)),
                                   "km": round(float(v["length_m"].sum()) / 1000, 1)}
                          for k, v in pipes.groupby("system")},
            "pipe_attributes": ["施工年度", "管種名称", "管径１(mm) 径/幅",
                                "上流土被り(m)", "下流土被り(m)"],
        },
        "flow_direction": dir_stats,
        "condition1_処理場から最終合流地点まで": i1,
        "condition2_流域下水道": i2,
        "condition3_管径2m相当以上": i3,
        "condition4_緊急輸送道路等": i4,
        "condition4_軌道下": i4r,
        "overlap": overlap,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nreports -> {OUT}")


if __name__ == "__main__":
    main()
