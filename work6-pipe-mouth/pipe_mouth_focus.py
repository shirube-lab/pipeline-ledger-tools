"""Does "inspect the pipe mouths first" actually narrow anything down?

NILIM's 2026-08 analysis of the national special inspection reported that
defects cluster within 5 m of a manhole: 34.6 / 34.8 defects per metre at
the upstream / downstream mouth against 7.9 per metre elsewhere, over 743
spans averaging 72 m.

Focusing inspection on the mouths only pays off when a span is long enough
to HAVE a middle. This script measures, for a real ledger, how much length
the mouth zones actually cover and how much defect coverage a mouth-only
inspection would buy — as a ratio, never as a defect count: NILIM's sample
is drawn from urgency-I remediation lengths, not from a general population.

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
MOUTH_M = 5.0              # NILIM's "within 5 m of the manhole"

# NILIM 資料3-2 (第7回検討会, 2026-08-20) p.6 の m あたり発生件数。
# 母集団は「優先実施箇所以外の緊急度Ⅰ要対策延長・令和7年10月末時点」の
# 全743スパン(平均延長72m)で、一般母集団の発生率ではない。
DENSITY = {"mouth": (34.6 + 34.8) / 2,   # 上流側 34.6 / 下流側 34.8
           "middle": 7.9}


def load_pipes() -> gpd.GeoDataFrame:
    g = gpd.read_file(BASE / "gesui_osui" / "24021" / "24021.shp", encoding="cp932")
    g = g.set_crs(CRS, allow_override=True)
    g["sewer_type"] = np.where(g["SASTYLEID"] < 24200, "汚水", "雨水")
    g["length_m"] = g.geometry.length
    return g


def mouth_share(length: pd.Series) -> pd.Series:
    """Fraction of a span covered by the two 5 m mouth zones (capped at 1)."""
    return np.minimum(2 * MOUTH_M / length.clip(lower=1e-9), 1.0)


def coverage_table(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Length share and expected defect share of the mouth zones, by band."""
    bands = [0, 10, 20, 30, 50, 72, np.inf]
    labels = ["〜10m", "10〜20m", "20〜30m", "30〜50m", "50〜72m", "72m 超"]
    rows = []
    for st, sub in g.groupby("sewer_type", observed=True):
        band = pd.cut(sub["length_m"], bands, labels=labels, right=False)
        for b, s in sub.groupby(band, observed=True):
            mouth_len = np.minimum(2 * MOUTH_M, s["length_m"]).sum()
            mid_len = (s["length_m"] - np.minimum(2 * MOUTH_M, s["length_m"])).sum()
            # expected defects if NILIM's densities held for this ledger
            d_mouth = mouth_len * DENSITY["mouth"]
            d_mid = mid_len * DENSITY["middle"]
            rows.append({
                "系統": st, "延長帯": b, "本数": len(s),
                "延長km": round(s["length_m"].sum() / 1000, 1),
                "管口部の延長割合%": round(mouth_len / s["length_m"].sum() * 100, 1),
                "異状の想定捕捉率%": round(d_mouth / (d_mouth + d_mid) * 100, 1),
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
    print(f"\n国総研サンプルの平均延長 72m 未満の割合(汚水): "
          f"{(o['length_m'] < 72).mean():.1%}")
    print(f"管口部(両端 {MOUTH_M:.0f}m)がスパン全長に占める割合(汚水): "
          f"中央値 {mouth_share(o['length_m']).median():.1%} / "
          f"平均 {mouth_share(o['length_m']).mean():.1%}")
    whole = (o["length_m"] <= 2 * MOUTH_M)
    print(f"スパン全体が管口部に収まる(延長 {2*MOUTH_M:.0f}m 以下): "
          f"{whole.sum():,} 本 ({whole.mean():.1%})")

    print("\n=== 延長帯別: 管口部の延長割合と、想定される異状の捕捉率 ===")
    tbl = coverage_table(g)
    print(tbl.to_string(index=False))

    # ledger-wide trade-off (sanitary only; the storm network is a different
    # animal and NILIM's sample is a sanitary-dominated one)
    mouth_len = np.minimum(2 * MOUTH_M, o["length_m"]).sum()
    total_len = o["length_m"].sum()
    mid_len = total_len - mouth_len
    d_mouth = mouth_len * DENSITY["mouth"]
    d_mid = mid_len * DENSITY["middle"]
    print(f"\n=== 汚水全体のトレードオフ(国総研の密度比を当てた場合) ===")
    print(f"管口部だけを見ると、点検延長は全体の {mouth_len/total_len:.1%} "
          f"({mouth_len/1000:.1f}km / {total_len/1000:.1f}km)")
    print(f"そのとき捕捉できる異状は想定の {d_mouth/(d_mouth+d_mid):.1%}")
    print(f"密度比(管口部 / 管口以外) = {DENSITY['mouth']/DENSITY['middle']:.1f} 倍")

    tbl.to_csv(OUT / "mouth_focus_by_band.csv", index=False, encoding="utf-8-sig")
    g[["SAUID", "sewer_type", "length_m"]].assign(
        mouth_share=mouth_share(g["length_m"]).round(3)
    ).to_csv(OUT / "span_length.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
