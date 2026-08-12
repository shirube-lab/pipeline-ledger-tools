"""Convert Handa city's published sewer ledger data into the NILIM draft
exchange format (地震対応における下水道管路データ交換標準仕様書(素案), 2026-03).

The point of this exercise is NOT a perfect conversion — it is to surface,
with real ledger data, exactly where the mapping succeeds, where it needs a
human judgment call, and where information has no home on either side.
Everything the converter cannot decide mechanically is written to reports
instead of being silently guessed.

Outputs (under output/):
  handa_exchange_draft.gpkg  exchange-format GeoPackage (layer/field names
                             follow the draft's application schema)
  gap_analysis.md            per-feature fill rates / missing / no-home lists
  conversion_log.md          every judgment call with counts
  quality_violations.csv     mandatory-field violations and outlier values

Sources of truth:
  schema/nilim_draft_schema.json   transcribed from the draft (printed pp.20-29)
  mapping/handa_mapping.json       mapping decisions, one place only
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyproj

HERE = Path(__file__).parent
BASE = HERE.parent
DATA = BASE / "data" / "handa" / "gesui_osui"   # usui folders hold the same rows
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)

SCHEMA = json.loads((HERE / "schema" / "nilim_draft_schema.json").read_text(encoding="utf-8"))
MAPPING = json.loads((HERE / "mapping" / "handa_mapping.json").read_text(encoding="utf-8"))

# The draft mandates 日本測地系2024 geographic coordinates (printed p.68).
# pyproj's EPSG database (checked below at runtime) has no JGD2024 entry, so
# we stop at JGD2011 geographic (EPSG:6668) and record the gap in the report.
SRC_CRS = "EPSG:6675"   # JGD2011 / Japan Plane Rectangular CS VII
DST_CRS = "EPSG:6668"   # JGD2011 geographic — closest reachable to the spec

judgments: list[str] = []      # human-judgment calls actually exercised
violations: list[dict] = []    # rows for quality_violations.csv


def log_judgment(msg: str) -> None:
    judgments.append(msg)


def nfkc(s: object) -> object:
    return unicodedata.normalize("NFKC", s) if isinstance(s, str) else s


def read_layer(layer_no: str) -> gpd.GeoDataFrame:
    g = gpd.read_file(DATA / layer_no / f"{layer_no}.shp", encoding="cp932")
    g = g.set_crs(SRC_CRS, allow_override=True)   # .prj files are 0 bytes
    return g


def sewer_kind(style_id: pd.Series) -> pd.Series:
    """241xx -> 02 汚水, 243xx -> 02? no: 02=汚水, 03=雨水 (排除区分, p.25)."""
    s = style_id.astype(str).str[:3]
    return s.map({"241": "02", "243": "03"}).fillna("99")


# ----------------------------------------------------------------- 管きょ
def convert_pipes() -> gpd.GeoDataFrame:
    src = read_layer("24021")
    n = len(src)

    mat_map = MAPPING["material_code_map"]
    kanshu = src["SAFIELD001"].map(nfkc)
    # mapping keys are written in the ledger's original spelling; normalize both
    norm_map = {nfkc(k): v["code"] for k, v in mat_map.items() if k != "_source"}
    material = kanshu.map(norm_map)
    material = material.where(kanshu.notna(), norm_map.get("__NULL__", "99"))
    unmapped = kanshu[material.isna()].value_counts()
    if len(unmapped):
        raise SystemExit(f"unmapped 管種名称 values: {dict(unmapped)}")
    for value, cnt in kanshu.fillna("(空欄)").value_counts().items():
        code = norm_map.get(value, norm_map["__NULL__"])
        basis = next((v["basis"] for k, v in mat_map.items() if nfkc(k) == value), "")
        if "判断" in basis:
            log_judgment(f"管材質: 「{value}」{cnt}本 → {code}。{basis}")

    # 呼び径: the ledger column is literally named 管径1(mm) 径/幅 — one column
    # for what the draft splits into 呼び径 (circular) and 内法幅 (box). With no
    # 断面形状 in the ledger we cannot split mechanically.
    dia = pd.to_numeric(src["SAFIELD002"], errors="coerce")
    zero = int((dia == 0).sum())
    if zero:
        violations.append({"layer": "管きょ", "item": "呼び径", "kind": "値0(未入力扱い)", "count": zero})
        dia = dia.where(dia != 0)
    log_judgment(f"呼び径: 台帳の「管径1(mm) 径/幅」は円形の径と矩形の幅を兼ねる多義列。"
                 f"断面形状が台帳に無いため機械的に振り分けられず、全件を呼び径に割り当てた({n}本)。")

    def to_mm(col: str, label: str, lo: float, hi: float) -> pd.Series:
        v = pd.to_numeric(src[col], errors="coerce")
        bad = v[(v < lo) | (v > hi)]
        if len(bad):
            violations.append({"layer": "管きょ", "item": label, "kind": f"範囲外({lo}〜{hi}m)",
                               "count": int(len(bad)),
                               "examples": ", ".join(f"{x:g}" for x in bad.head(3))})
        return (v * 1000).round()

    # Ledger values read "2015年" — a unit suffix inside the value. The draft
    # wants Integer, so strip it (and log the call: this is exactly the kind
    # of cell-level cleanup every municipality will hit on conversion).
    year_raw = src["SAFIELD000"].astype("string")
    year = pd.to_numeric(year_raw.str.extract(r"^(\d{4})", expand=False), errors="coerce")
    n_suffixed = int((year_raw.str.contains("年", na=False)).sum())
    log_judgment(f"竣工年度: 台帳の値は「2015年」のように単位語付きの文字列({n_suffixed}本)。"
                 f"素案の Integer に合わせ先頭 4 桁を抽出。")
    dup = int(src["SAUID"].duplicated().sum())
    if dup:
        violations.append({"layer": "管きょ", "item": "施設番号(SAUID)", "kind": "重複(必須[1]の一意性違反)",
                           "count": dup})
    log_judgment("竣工年度: 台帳の語は「施工年度」、素案は「竣工年度」(工事完了年度)。同義とみなして転記。")

    out = gpd.GeoDataFrame({
        "施設番号": src["SAUID"].astype(str),
        "排除区分": sewer_kind(src["SASTYLEID"]),
        "竣工年度": year.astype("Int64"),
        "管材質": material,
        "呼び径": dia.astype("Int64"),
        "上流土被り": to_mm("SAFIELD003", "上流土被り", -0.001, 30).astype("Int64"),
        "下流土被り": to_mm("SAFIELD004", "下流土被り", -0.001, 30).astype("Int64"),
    }, geometry=src.geometry, crs=SRC_CRS)
    return out


# --------------------------------------------------------------- マンホール
def convert_manholes() -> gpd.GeoDataFrame:
    src = read_layer("24001")

    mh_map = {nfkc(k): v["code"] for k, v in MAPPING["manhole_code_map"].items() if k != "_source"}
    shubetsu = src["SAFIELD009"].map(nfkc)
    kind = shubetsu.map(mh_map).where(shubetsu.notna(), mh_map["__NULL__"])
    unmapped = shubetsu[kind.isna()].value_counts()
    if len(unmapped):
        raise SystemExit(f"unmapped 人孔種別名称 values: {dict(unmapped)}")
    for value, cnt in shubetsu.fillna("(空欄)").value_counts().items():
        entry = next((v for k, v in MAPPING["manhole_code_map"].items() if nfkc(k) == value), None)
        if entry and "判断" in entry.get("basis", ""):
            log_judgment(f"マンホール種別: 「{value}」{cnt}基 → {entry['code']}。{entry['basis']}")

    road = src["SAFIELD016"].map(nfkc).map({"半田市": "06", "愛知県": "05", "建設省": "01"})
    road = road.where(src["SAFIELD016"].notna(), "99")
    n_kensetsusho = int((src["SAFIELD016"].map(nfkc) == "建設省").sum())
    log_judgment(f"道路管理者: 「建設省」{n_kensetsusho}基 → 01(国)。2001 年に廃止された省名が台帳に残っている。")

    key = src["SAFIELD002"].astype("string")
    n_missing = int(key.isna().sum())
    n_dup = int(key.dropna().duplicated().sum())
    violations.append({"layer": "マンホール", "item": "施設番号(人孔キー)", "kind": "欠損(必須[1]違反)", "count": n_missing})
    violations.append({"layer": "マンホール", "item": "施設番号(人孔キー)", "kind": "重複(必須[1]の一意性違反)", "count": n_dup})
    facility = key.fillna("SAUID:" + src["SAUID"].astype(str))
    log_judgment(f"施設番号: 人孔キー欠損 {n_missing} 基は SAUID で代用(接頭辞付き)。重複 {n_dup} 基はそのまま出力し品質レポートに記録。")

    depth = pd.to_numeric(src["SAFIELD012"], errors="coerce")
    bad = depth[(depth < 0) | (depth > 30)]
    if len(bad):
        violations.append({"layer": "マンホール", "item": "深さ", "kind": "範囲外(0〜30m)", "count": int(len(bad)),
                           "examples": ", ".join(f"{x:g}" for x in bad.head(3))})

    haijo = src["SAFIELD004"].map(nfkc).map({"汚水": "02", "雨水": "03"}).fillna("99")

    out = gpd.GeoDataFrame({
        "施設番号": facility,
        "排除区分": haijo,
        "種別": kind,
        "道路管理者": road,
        "深さ": (depth * 1000).round().astype("Int64"),
        "排水区域名称": src["SAFIELD006"],
        "処理分区域名称": src["SAFIELD005"],
        "図面番号": src["SAFIELD007"],
    }, geometry=src.geometry, crs=SRC_CRS)
    return out


# --------------------------------------------------------------- 公共ます / 取付け管
def convert_masu() -> gpd.GeoDataFrame:
    src = read_layer("24041")
    log_judgment(f"公共ます: 施設番号に相当する属性が桝レイヤに無いため SAUID を充当({len(src)}基)。")
    out = gpd.GeoDataFrame({
        "施設番号": src["SAUID"].astype(str),
        "ます種別": sewer_kind(src["SASTYLEID"]).map({"02": "20", "03": "30"}).fillna("99"),
    }, geometry=src.geometry, crs=SRC_CRS)
    return out


def convert_toritsuke() -> gpd.GeoDataFrame:
    src = read_layer("24051")
    return gpd.GeoDataFrame({"dummy": [None] * len(src)}, geometry=src.geometry, crs=SRC_CRS).drop(columns="dummy")


# ------------------------------------------------------------------ reports
def fill_rates(g: gpd.GeoDataFrame) -> dict[str, float]:
    return {c: round(g[c].notna().mean() * 100, 1) for c in g.columns if c != "geometry"}


def check_either_or(layers: dict[str, gpd.GeoDataFrame]) -> None:
    """The draft requires 排水区域名称 or 処理区域名称 on マンホール and 管きょ
    (pp.21-22 注記). Count rows where neither is filled."""
    for feat in ("マンホール", "管きょ"):
        g = layers[feat]
        drain = g["排水区域名称"].notna() if "排水区域名称" in g.columns else pd.Series(False, index=g.index)
        treat = g["処理区域名称"].notna() if "処理区域名称" in g.columns else pd.Series(False, index=g.index)
        n_bad = int((~(drain | treat)).sum())
        if n_bad:
            violations.append({"layer": feat, "item": "排水区域名称/処理区域名称",
                               "kind": "どちらか必須(注記)を両方欠く", "count": n_bad,
                               "examples": f"全{len(g):,}件中"})


def write_reports(layers: dict[str, gpd.GeoDataFrame]) -> None:
    proj_db = pyproj.database.get_database_metadata("EPSG.VERSION")
    lines = ["# 変換ギャップ分析 — 半田市データ → 交換標準(素案)", ""]
    lines.append(f"変換先の空間参照系について: 素案は「日本測地系2024における緯度経度座標系」を指定する(印刷 p.68)が、"
                 f"本変換に使った pyproj {pyproj.__version__}(EPSG データベース {proj_db})には JGD2024 の地理座標系が"
                 f"登録されていない。到達できたのは JGD2011 地理座標系(EPSG:6668)まで。JGD2011→2024 の補正には"
                 f"国土地理院の座標変換(POS2JGD 等)が別途必要になる。")
    lines.append("")
    for feat, g in layers.items():
        spec_attrs = [a["name"] for a in SCHEMA["features"][feat]["attributes"]]
        have = [c for c in g.columns if c != "geometry"]
        missing = [a for a in spec_attrs if a not in have]
        m = MAPPING.get(feat, {})
        lines.append(f"## {feat} ({len(g):,} 件)")
        lines.append("")
        lines.append(f"- 素案の属性数(ジオメトリ除く): **{len(spec_attrs)}** / 埋められた属性: **{len(have)}** "
                     f"({len(have)}/{len(spec_attrs)} = {len(have)/max(len(spec_attrs),1)*100:.0f}%)")
        rates = fill_rates(g)
        lines.append(f"- 各属性の充足率(非 NULL 率): " + ", ".join(f"{k} {v}%" for k, v in rates.items()))
        if missing:
            lines.append(f"- **台帳に無く埋められない素案属性({len(missing)})**: " + "、".join(missing))
        for nh in m.get("no_home", []):
            lines.append(f"- 行き場のない台帳側の情報: {nh}")
        lines.append("")
    (OUT / "gap_analysis.md").write_text("\n".join(lines), encoding="utf-8")

    log = ["# 変換の判断ログ", "",
           "機械的に決められず、人の判断で割り当てた項目の全記録。", ""]
    log += [f"- {j}" for j in judgments]
    (OUT / "conversion_log.md").write_text("\n".join(log), encoding="utf-8")

    pd.DataFrame(violations).to_csv(OUT / "quality_violations.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    layers = {
        "マンホール": convert_manholes(),
        "管きょ": convert_pipes(),
        "公共ます": convert_masu(),
        "取付け管": convert_toritsuke(),
    }
    check_either_or(layers)
    gpkg = OUT / "handa_exchange_draft.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    for name, g in layers.items():
        g.to_crs(DST_CRS).to_file(gpkg, layer=name, driver="GPKG")
        print(f"wrote layer {name}: {len(g):,} features, {len(g.columns)-1} attrs")
    write_reports(layers)
    print(f"\nreports -> {OUT}")
    print(f"judgment calls: {len(judgments)}, violation rows: {len(violations)}")


if __name__ == "__main__":
    main()
