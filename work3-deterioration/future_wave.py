"""Project the future aging wave: length of pipes at or beyond the 50-year
standard (depreciation) life at each future year. The classic
stock-management chart that motivates planned renewal even when today's
aged stock is small.

Counting rule: age >= 50 (matches the MLIT convention "耐用年数50年を
経過した管路"). Pipes with unknown construction year are excluded here
(imputed ages would fabricate the timing of the wave), while the risk
scoring in score_priority.py uses imputed ages — see README for why the
two analyses treat missing years differently.
"""

from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.rcParams["font.family"] = "Meiryo"

HERE = Path(__file__).parent
OUT = HERE / "output"
ATTRIBUTION = "出典: 半田市「水道管路等データ」(CC-BY 4.0)を加工して作成"

OUT.mkdir(exist_ok=True)
gdf = gpd.read_file(HERE / "cleaned" / "kankyo_cleaned.gpkg")
df = pd.DataFrame(gdf.drop(columns="geometry"))

known = df[df["sekou_year"].notna()].copy()
known_km = known["length_m"].sum() / 1000.0
print(f"known-year pipes: {len(known):,} / {len(df):,} ({known_km:.1f} km)")

years = range(2026, 2066, 5)
rows = []
for y in years:
    over = known[(y - known["sekou_year"]) >= 50]
    rows.append({"year": y, "km_over50": over["length_m"].sum() / 1000.0,
                 "count_over50": len(over)})
proj = pd.DataFrame(rows)
print(f"\n=== 50年経過延長の将来推移(施工年度既知の {len(known):,} 本ベース)===")
print(proj.to_string(index=False))

fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(proj["year"], proj["km_over50"], width=3.4, color="#d7191c", alpha=0.85)
ax.set_xlabel("年")
ax.set_ylabel("標準耐用年数50年を経過した延長 (km)")
ax.set_title(f"経年管渠の将来推移(施工年度既知の {len(known):,} 本。"
             "無対策と仮定した試算)")
for _, r in proj.iterrows():
    ax.text(r["year"], r["km_over50"] + 3, f"{r['km_over50']:.0f}", ha="center", fontsize=9)
plt.figtext(0.99, 0.01, ATTRIBUTION, ha="right", fontsize=8, color="#555555")
plt.tight_layout()
plt.savefig(OUT / "future_wave.png", dpi=150)
print(f"\nsaved -> {OUT / 'future_wave.png'}")
