"""Deterioration risk scoring and renewal priority ranking for sewer pipes.

Two complementary approaches, mirroring 下水道ストックマネジメント practice:

1. Rule-based risk = P(deterioration) x Consequence
   - P: logistic curve over service-time ratio (age / effective life).
     Effective life = 50 years (standard for sewer pipes) x material factor
     (ceramic/concrete pipes deteriorate faster than PVC).
   - C: pipe diameter (bigger failure impact) + shallow cover bonus
     (road-collapse risk).

2. ML demo on SYNTHETIC inspection labels
   - Simulates a partial TV-camera inspection program (20% of pipes),
     with outcome labels drawn from a hidden degradation process + noise.
   - Trains a classifier on inspected pipes, predicts risk for the rest.
   - The labels are synthetic; the pipeline is what a real project would
     run when actual inspection records exist.

Outputs: priority GeoPackage/CSV, folium priority map, age-profile chart.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

matplotlib.rcParams["font.family"] = "Meiryo"

HERE = Path(__file__).parent
OUT = HERE / "output"
RNG = np.random.default_rng(42)

ATTRIBUTION = "出典: 半田市「水道管路等データ」(CC-BY 4.0)を加工して作成"
DISCLAIMER = (
    "【手法デモ】本マップは半田市オープンデータ(CC-BY 4.0)を加工した手法デモであり、"
    "半田市の実際の管路状態の評価・更新計画を示すものではありません。"
    "優先度ランクは相対評価(リスクスコア上位5%をAと定義)による点検順序の試算で、"
    "危険度の絶対評価ではありません(現時点で標準耐用年数50年を超えた管渠はほぼありません)。"
    "「ML予測」列は合成の緊急度ラベルによる参考値です。"
)

# 減価償却上の標準耐用年数(地方公営企業法施行規則)。物理的寿命ではない
STANDARD_LIFE = 50
MATERIAL_FACTOR = {  # effective-life multiplier by material family
    "陶管": 0.80,
    "ヒューム管": 0.90,
    "その他": 0.90,
    "硬質塩ビ管": 1.10,
    "塩ビ管": 1.10,
    "強化プラスチック管": 1.15,
}
# Longest key first so 硬質塩ビ管 is tested before 塩ビ管
_MATERIAL_KEYS = sorted(
    (k for k in MATERIAL_FACTOR if k != "その他"), key=len, reverse=True
)


def material_family(kanshu: str | float) -> str:
    if not isinstance(kanshu, str):
        return "その他"
    # NFKC normalization folds half-width katakana (強化ﾌﾟﾗｽﾁｯｸ管 etc.)
    normalized = unicodedata.normalize("NFKC", kanshu)
    for key in _MATERIAL_KEYS:
        if key in normalized:
            return key
    return "その他"


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def rule_based_risk(df: pd.DataFrame) -> pd.DataFrame:
    factor = df["mat_family"].map(MATERIAL_FACTOR)
    df["service_ratio"] = df["age_filled"] / (STANDARD_LIFE * factor)
    # P: 0.5 at end of effective life, steep rise beyond it
    df["p_deterioration"] = sigmoid(6.0 * (df["service_ratio"] - 1.0))

    diam = df["kankei_mm"].fillna(df["kankei_mm"].median())
    c_diam = np.clip(diam / 1000.0, 0.15, 1.0)          # normalize by 1000mm
    shallow = (df["dokaburi_up_m"].fillna(1.5) < 1.0)    # shallow cover
    df["consequence"] = np.clip(c_diam + shallow * 0.2, 0.0, 1.0)

    df["risk_score"] = (df["p_deterioration"] * df["consequence"]).round(4)
    return df


def assign_rank(df: pd.DataFrame) -> pd.DataFrame:
    # A: top 5% risk, B: next 15%, C: next 30%, D: rest
    q = df["risk_score"].rank(pct=True)
    df["priority_rank"] = np.select(
        [q >= 0.95, q >= 0.80, q >= 0.50], ["A", "B", "C"], default="D"
    )
    return df


def ml_demo(df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Synthetic-inspection ML pipeline (labels are SIMULATED).

    Labels emulate the guideline's urgency assessment: 1 = urgency grade
    II or higher (requires action), 0 = grade III / no deterioration.
    Real urgency grades come from TV-camera inspection findings; none are
    public, so a hidden degradation process generates fictional ones.
    """
    # Hidden "true" degradation process differs slightly from the rule model
    hidden = sigmoid(
        5.0 * (df["service_ratio"] - 0.95)
        + 0.3 * (df["kankei_mm"].fillna(200) < 250)
        - 0.2 * df["dokaburi_up_m"].fillna(1.5)
    )
    inspected = RNG.random(len(df)) < 0.20
    labels = (RNG.random(len(df)) < hidden).astype(int)

    feats = pd.get_dummies(
        df[["age_filled", "kankei_mm", "dokaburi_up_m", "length_m", "mat_family"]],
        columns=["mat_family"],
    ).fillna(-1)

    x_ins, y_ins = feats[inspected], labels[inspected]
    x_tr, x_te, y_tr, y_te = train_test_split(
        x_ins, y_ins, test_size=0.3, random_state=42, stratify=y_ins
    )
    model = GradientBoostingClassifier(random_state=42)
    model.fit(x_tr, y_tr)
    auc = roc_auc_score(y_te, model.predict_proba(x_te)[:, 1])

    df["ml_inspected"] = inspected
    df["ml_pred_urgent"] = model.predict_proba(feats)[:, 1].round(4)
    return df, auc


def age_profile_chart(df: pd.DataFrame) -> None:
    known = df[df["sekou_year"].notna()].copy()
    known["era"] = (known["sekou_year"] // 5 * 5).astype(int)
    pivot = (
        known.pivot_table(index="era", columns="mat_family",
                          values="length_m", aggfunc="sum")
        .fillna(0.0) / 1000.0
    )
    ax = pivot.plot(kind="bar", stacked=True, figsize=(11, 5), width=0.85)
    ax.set_xlabel("施工年度(5年区切り)")
    ax.set_ylabel("延長 (km)")
    ax.set_title("管渠の管齢構成(管種別・延長ベース)")
    ax.legend(title="管種", fontsize=9)
    plt.figtext(0.99, 0.01, ATTRIBUTION, ha="right", fontsize=8, color="#555555")
    plt.tight_layout()
    plt.savefig(OUT / "age_profile.png", dpi=150)
    plt.close()


def priority_map(gdf: gpd.GeoDataFrame) -> None:
    colors = {"A": "#d7191c", "B": "#fdae61", "C": "#ffdf80", "D": "#bdbdbd"}
    slim = gdf.copy()
    slim["geometry"] = slim.geometry.simplify(1.0)
    slim = slim.to_crs("EPSG:4326")

    m = folium.Map(location=(34.8990, 136.9330), zoom_start=13, tiles=None)
    folium.TileLayer(
        tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr=f"&copy; OpenStreetMap contributors | {ATTRIBUTION}",
        name="OpenStreetMap",
    ).add_to(m)
    banner = folium.Element(
        '<div style="position:fixed; top:8px; left:50%; transform:translateX(-50%);'
        ' z-index:9999; background:#fff8dc; border:1px solid #b8860b;'
        ' border-radius:4px; padding:6px 12px; font-size:12px; max-width:90%;">'
        f"{DISCLAIMER}</div>"
    )
    m.get_root().html.add_child(banner)
    for rank in ["D", "C", "B", "A"]:  # draw A last (on top)
        layer = slim[slim["priority_rank"] == rank]
        folium.GeoJson(
            layer.to_json(),
            name=f"優先度{rank} ({len(layer)}本)",
            style_function=lambda f, r=rank: {
                "color": colors[r],
                "weight": 3.5 if r == "A" else (2.5 if r == "B" else 1.5),
                "opacity": 0.9 if r in "AB" else 0.5,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["priority_rank", "sewer_type", "sekou_year", "kanshu",
                        "kankei_mm", "risk_score", "ml_pred_urgent"],
                aliases=["優先度", "区分", "施工年度", "管種", "管径(mm)",
                         "リスクスコア", "ML予測: 緊急度Ⅱ以上の確率(合成・参考)"],
            ),
        ).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(OUT / "priority_map.html"))


def main() -> None:
    gdf = gpd.read_file(HERE / "cleaned" / "kankyo_cleaned.gpkg")
    df = gdf.copy()

    # Sanitize implausible cover-depth values found in the ledger
    # (e.g. -24.28m / 60,557m). Out-of-range -> treated as missing.
    for col in ["dokaburi_up_m", "dokaburi_dn_m"]:
        bad = ~df[col].between(0.0, 15.0) & df[col].notna()
        if bad.any():
            print(f"cleaning: {col} out-of-range {bad.sum()} 件を欠損扱いに")
        df[col] = df[col].where(df[col].between(0.0, 15.0))

    df["mat_family"] = df["kanshu"].map(material_family)
    # Missing year (11.5%): assume era-median per material family, flag it
    df["age_filled"] = df["age"].astype("Float64")
    med_by_mat = df.groupby("mat_family")["age_filled"].transform("median")
    df["age_imputed"] = df["age_filled"].isna()
    df["age_filled"] = df["age_filled"].fillna(med_by_mat).astype(float)

    df = rule_based_risk(df)
    df = assign_rank(df)
    df, auc = ml_demo(df)

    OUT.mkdir(exist_ok=True)
    print("=== 優先度ランク別サマリ ===")
    summary = df.groupby("priority_rank").agg(
        本数=("priority_rank", "size"),
        延長km=("length_m", lambda s: round(s.sum() / 1000, 1)),
        平均経過年数=("age_filled", lambda s: round(s.mean(), 1)),
    )
    print(summary.to_string())
    print(f"\nML デモ(合成緊急度ラベル)AUC: {auc:.3f}")
    print(f"耐用年数50年超の管渠: "
          f"{(df['age_filled'] > 50).sum()} 本 / "
          f"{df.loc[df['age_filled'] > 50, 'length_m'].sum() / 1000:.1f} km")

    keep = ["SAUID", "sewer_type", "sekou_year", "age_filled", "age_imputed",
            "kanshu", "mat_family", "kankei_mm", "dokaburi_up_m", "length_m",
            "service_ratio", "p_deterioration", "consequence", "risk_score",
            "priority_rank", "ml_inspected", "ml_pred_urgent", "geometry"]
    result = gpd.GeoDataFrame(df[keep], crs=gdf.crs)
    result.to_file(OUT / "priority_result.gpkg", layer="priority", driver="GPKG")
    top = result.sort_values("risk_score", ascending=False).head(300)
    with (OUT / "priority_top300.csv").open("w", encoding="utf-8-sig", newline="") as f:
        f.write(f"# {ATTRIBUTION}\n")
        f.write("# 本ファイルは手法デモの試算値。ml_pred_urgent は合成の緊急度ラベル"
                "(緊急度Ⅱ以上相当か否か)による参考値であり実測に基づく評価ではない\n")
        top.drop(columns="geometry").to_csv(f, index=False)

    age_profile_chart(df)
    priority_map(result)
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
