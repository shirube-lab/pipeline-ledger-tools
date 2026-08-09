"""Render the urgency judgment results on an OpenStreetMap base map.

Reads span_geoms.gpkg (real Handa pipe geometry, EPSG:6675) and
output/span_urgency.csv (synthetic-survey judgment results) and writes
output/urgency_map.html with spans colored by urgency.
"""

from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd

HERE = Path(__file__).parent

COLORS = {"Ⅰ": "#c00000", "Ⅱ": "#ed7d31", "Ⅲ": "#f2c744", "異常なし": "#2ca02c"}
ATTRIBUTION = "出典: 半田市「水道管路等データ」(CC-BY 4.0)を加工して作成"

geoms = gpd.read_file(HERE / "span_geoms.gpkg", layer="spans").to_crs(4326)
results = pd.read_csv(HERE / "output" / "span_urgency.csv")
gdf = geoms.merge(results, on="span_id")
print(f"spans on map: {len(gdf)}")

center = [gdf.geometry.union_all().centroid.y, gdf.geometry.union_all().centroid.x]
m = folium.Map(location=center, zoom_start=14, tiles=None)
folium.TileLayer(
    tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr=f"&copy; OpenStreetMap contributors | {ATTRIBUTION}",
    name="OpenStreetMap",
).add_to(m)
m.get_root().html.add_child(folium.Element(
    '<div style="position:fixed; top:8px; left:50%; transform:translateX(-50%);'
    ' z-index:9999; background:#fff8dc; border:1px solid #b8860b;'
    ' border-radius:4px; padding:6px 12px; font-size:12px; max-width:90%;">'
    "【手法デモ】調査データは全て合成です。半田市オープンデータ(CC-BY 4.0)の"
    "管路位置に、架空の調査結果を重ねたもので、実際の管路状態の評価では"
    "ありません。</div>"
))
legend_rows = "".join(
    f'<div><span style="display:inline-block;width:18px;height:4px;'
    f'background:{c};margin-right:6px;vertical-align:middle;"></span>'
    f'緊急度{g}' + ("" if g != "異常なし" else "") + "</div>"
    for g, c in COLORS.items()
).replace("緊急度異常なし", "異常なし")
m.get_root().html.add_child(folium.Element(
    '<div style="position:fixed; bottom:24px; left:12px; z-index:9999;'
    ' background:#ffffff; border:1px solid #888; border-radius:4px;'
    f' padding:8px 12px; font-size:12px;">{legend_rows}</div>'
))
folium.GeoJson(
    gdf.to_json(),
    style_function=lambda f: {
        "color": COLORS.get(f["properties"]["緊急度"], "#888888"),
        "weight": 5,
        "opacity": 0.9,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["span_id", "緊急度", "腐食", "たるみ", "発生率ランク", "特例適用", "判定根拠"],
        aliases=["スパンID", "緊急度", "腐食", "たるみ", "発生率", "特例", "判定根拠"],
    ),
).add_to(m)

out = HERE / "output" / "urgency_map.html"
m.save(str(out))
print(f"saved -> {out}")
