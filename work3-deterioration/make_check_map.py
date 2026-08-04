"""Render a small folium map to visually verify georeferencing.

Takes a ~1km window around central Handa and overlays the sewer pipes
on OpenStreetMap. If pipes follow the street network, the CRS
assumption (EPSG:6675) is visually confirmed.
"""

from pathlib import Path

import folium
import geopandas as gpd

HERE = Path(__file__).parent
CENTER = (34.8920, 136.9380)  # central Handa
WINDOW = 0.006                # ~600m half-width

gdf = gpd.read_file(HERE / "cleaned" / "kankyo_wgs84.geojson")
sub = gdf.cx[
    CENTER[1] - WINDOW : CENTER[1] + WINDOW,
    CENTER[0] - WINDOW : CENTER[0] + WINDOW,
]
print(f"window features: {len(sub)}")

ATTRIBUTION = "出典: 半田市「水道管路等データ」(CC-BY 4.0)を加工して作成"

m = folium.Map(location=CENTER, zoom_start=16, tiles=None)
folium.TileLayer(
    tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr=f"&copy; OpenStreetMap contributors | {ATTRIBUTION}",
    name="OpenStreetMap",
).add_to(m)
m.get_root().html.add_child(folium.Element(
    '<div style="position:fixed; top:8px; left:50%; transform:translateX(-50%);'
    ' z-index:9999; background:#fff8dc; border:1px solid #b8860b;'
    ' border-radius:4px; padding:6px 12px; font-size:12px; max-width:90%;">'
    "【手法デモ】座標系検証用マップ。半田市オープンデータ(CC-BY 4.0)を加工した"
    "もので、実際の管路状態の評価を示すものではありません。</div>"
))
folium.GeoJson(
    sub.to_json(),
    style_function=lambda f: {
        "color": "#d62728" if f["properties"]["sewer_type"] == "雨水" else "#1f77b4",
        "weight": 3,
        "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["sewer_type", "sekou_year", "kanshu", "kankei_mm"],
        aliases=["区分", "施工年度", "管種", "管径(mm)"],
    ),
).add_to(m)
out = HERE / "output" / "crs_check_map.html"
out.parent.mkdir(exist_ok=True)
m.save(str(out))
print(f"saved -> {out}")
