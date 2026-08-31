"""Does "inspect the pipe mouths first" actually narrow anything down?

NILIM's 2026-08 analysis of the national special inspection reported that
defects cluster near manholes: 34.6 / 34.8 defects per metre within 5 m of
the upstream / downstream mouth, 14.8 / 22.0 in the 5-10 m band, and 7.9
in the middle, over 743 spans averaging 72 m.

Focusing inspection on the mouths only pays off when a span is long enough
to HAVE a middle. This script measures, for a real ledger, how much length
the mouth zones cover and how much defect coverage a mouth-only inspection
would buy — as a ratio, never as a defect count: NILIM's sample is drawn
from urgency-I remediation lengths of large-diameter pipes, not from a
general population.

Outputs: span length distribution, mouth-share by length band, and the
coverage/effort trade-off under NILIM's density ratios.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1] / "data" / "handa"
OUT = Path(__file__).parent / "output"
CRS = "EPSG:6675"          # JGD2011 plane rectangular zone VII (see article 1)

MOUTH_M = 5.0              # 管口 5m 以内
NEAR_M = 10.0              # 5〜10m 帯の外側境界

# NILIM 資料3-2 (第7回検討会, 2026-08-20) p.6 の m あたり発生件数を、資料の
# 区間区分どおり 3 層で持つ。7.9 は「管口以外(平均52m)」= 72m から両端 10m を
# 除いた中央部の値で、5〜10m 帯を含まない。2 層に潰すと短いスパンの「管口以外」
# を過小評価し、捕捉率が上振れする。
# 母集団は「優先実施箇所以外の緊急度Ⅰ要対策延長・令和7年10月末時点」の全743
# スパン(平均延長72m。全国特別重点調査は管径2m以上・布設後30年以上が対象)で、
# 一般母集団の発生率ではない。
DENSITY = {
    "mouth": (34.6 + 34.8) / 2,   # 管口 5m 以内: 上流 34.6 / 下流 34.8
    "near": (14.8 + 22.0) / 2,    # 5〜10m 帯:    上流 14.8 / 下流 22.0
    "middle": 7.9,                # 管口以外(平均52m)
}


def load_pipes() -> gpd.GeoDataFrame:
    g = gpd.read_file(BASE / "gesui_osui" / "24021" / "24021.shp", encoding="cp932")
    g = g.set_crs(CRS, allow_override=True)
    g["sewer_type"] = np.where(g["SASTYLEID"] < 24200, "汚水", "雨水")
    g["length_m"] = g.geometry.length
    return g


def mouth_share(length: pd.Series) -> pd.Series:
    """Fraction of a span covered by the two 5 m mouth zones (capped at 1)."""
    return np.minimum(2 * MOUTH_M / length.clip(lower=1e-9), 1.0)


def split_zones(length: pd.Series):
    """Length in the mouth zones, the 5-10 m band, and the middle —
    matching the three intervals NILIM reports."""
    mouth = np.minimum(2 * MOUTH_M, length)
    near = np.clip(length - 2 * MOUTH_M, 0, 2 * (NEAR_M - MOUTH_M))
    middle = np.clip(length - 2 * NEAR_M, 0, None)
    return mouth, near, middle


def expected_defects(mouth_len: float, near_len: float, mid_len: float):
    """(defects in the mouth zones, defects elsewhere) under NILIM's densities."""
    d_mouth = mouth_len * DENSITY["mouth"]
    d_rest = near_len * DENSITY["near"] + mid_len * DENSITY["middle"]
    return d_mouth, d_rest


def coverage_table(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Length share and expected defect share of the mouth zones, by band."""
    bands = [0, 10, 20, 30, 50, 72, np.inf]
    labels = ["〜10m", "10〜20m", "20〜30m", "30〜50m", "50〜72m", "72m 以上"]
    rows = []
    total_by_sys = g.groupby("sewer_type", observed=True)["length_m"].sum()
    for st, sub in g.groupby("sewer_type", observed=True):
        band = pd.cut(sub["length_m"], bands, labels=labels, right=False)
        for b, s in sub.groupby(band, observed=True):
            mouth, near, middle = split_zones(s["length_m"])
            d_mouth, d_rest = expected_defects(mouth.sum(), near.sum(), middle.sum())
            band_len = s["length_m"].sum()
            rows.append({
                "系統": st, "延長帯": b, "本数": len(s),
                "延長km": round(band_len / 1000, 1),
                "系統内の延長割合%": round(band_len / total_by_sys[st] * 100, 1),
                "管口部の延長割合%": round(mouth.sum() / band_len * 100, 1),
                "異状の想定捕捉率%": round(d_mouth / (d_mouth + d_rest) * 100, 1),
            })
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    g = load_pipes()

    print("=== スパン延長の分布 ===")
    stats = g.groupby("sewer_type", observed=True)["length_m"].agg(
        本数="size", 総延長km=lambda s: round(s.sum() / 1000, 1),
        平均m=lambda s: round(s.mean(), 1), 中央値m=lambda s: round(s.median(), 1),
        p95m=lambda s: round(s.quantile(0.95), 1))
    print(stats.to_string())

    o = g[g["sewer_type"] == "汚水"]
    total_len = o["length_m"].sum()
    print(f"\n国総研サンプルの平均延長 72m 未満の割合(汚水): "
          f"{(o['length_m'] < 72).mean():.1%}")
    print(f"管口部(両端 {MOUTH_M:.0f}m)がスパン全長に占める割合(汚水): "
          f"中央値 {mouth_share(o['length_m']).median():.1%} / "
          f"平均 {mouth_share(o['length_m']).mean():.1%}")

    print("\n=== 延長帯別: 管口部の延長割合と、想定される異状の捕捉率 ===")
    tbl = coverage_table(g)
    print(tbl.to_string(index=False))

    mouth, near, middle = split_zones(o["length_m"])
    d_mouth, d_rest = expected_defects(mouth.sum(), near.sum(), middle.sum())
    print("\n=== 汚水全体のトレードオフ(国総研の密度比を当てた場合) ===")
    print(f"管口部だけを見ると、点検対象の延長は全体の {mouth.sum()/total_len:.1%} "
          f"({mouth.sum()/1000:.1f}km / {total_len/1000:.1f}km)")
    print(f"そのとき捕捉できる異状は想定の {d_mouth/(d_mouth+d_rest):.1%}")
    print(f"密度比: 管口部 / 中央部 = {DENSITY['mouth']/DENSITY['middle']:.1f} 倍、"
          f"管口部 / 5〜10m 帯 = {DENSITY['mouth']/DENSITY['near']:.1f} 倍")
    print(f"帯別の延長: 管口部 {mouth.sum()/1000:.1f}km / "
          f"5〜10m {near.sum()/1000:.1f}km / 中央部 {middle.sum()/1000:.1f}km")

    print("\n=== 「絞り込み不能」の規模: 本数 vs 延長 ===")
    for th, label in [(2 * MOUTH_M, "10m 未満(全体が管口部)"),
                      (2 * NEAR_M, "20m 未満(中央部を持たない)")]:
        sel = o["length_m"] < th
        print(f"  {label}: 本数 {sel.sum():,}本 ({sel.mean():.1%}) / "
              f"延長 {o.loc[sel, 'length_m'].sum()/1000:.1f}km "
              f"({o.loc[sel, 'length_m'].sum()/total_len:.1%})")
    long_sel = o["length_m"] >= 30
    print(f"  30m 以上:  本数 {long_sel.sum():,}本 ({long_sel.mean():.1%}) / "
          f"延長 {o.loc[long_sel, 'length_m'].sum()/1000:.1f}km "
          f"({o.loc[long_sel, 'length_m'].sum()/total_len:.1%})")

    tbl.to_csv(OUT / "mouth_focus_by_band.csv", index=False, encoding="utf-8-sig")
    mouth_a, near_a, mid_a = split_zones(g["length_m"])
    g[["SAUID", "sewer_type", "length_m"]].assign(
        mouth_share=mouth_share(g["length_m"]).round(3),
        mouth_m=mouth_a.round(2), near_m=near_a.round(2), middle_m=mid_a.round(2),
    ).to_csv(OUT / "span_length.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
