"""Extract field definitions from SonicWeb S2AConfig layer XML files.

Walks the Handa open-data folders, parses each <layer>.xml, and emits a
field dictionary (layer -> SAFIELDxxx -> ColID / Japanese title) as both
a console table and a CSV. This mapping lets us rename the opaque
SAFIELD columns of the shapefiles to their real ledger attribute names.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "data" / "handa"
OUT_CSV = Path(__file__).parent / "s2a_field_mapping.csv"


def parse_layer_xml(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    layer_no = root.findtext(".//LayerNo") or path.stem
    table = root.findtext(".//AttributeTable") or ""
    coord_no = root.findtext(".//CoordinateSystemNo") or ""
    rows = []
    for field in root.findall(".//ShapeAttributeConfig/Fields/Field"):
        field_id = field.get("id", "")
        title = field.findtext("Title") or ""
        col_id = field.findtext("ColID") or ""
        if not title and not col_id:
            continue  # system columns without business meaning
        rows.append(
            {
                "group": path.parent.parent.name,
                "layer_no": layer_no,
                "layer_table": table,
                "coord_no": coord_no,
                "field_id": field_id,
                "col_id": col_id,
                "title": title,
            }
        )
    return rows


def main() -> None:
    all_rows = []
    for xml_path in sorted(BASE.glob("*/*/*.xml")):
        if xml_path.stem != xml_path.parent.name:
            continue  # skip Thematicmap.xml etc.
        all_rows.extend(parse_layer_xml(xml_path))

    if not all_rows:
        raise SystemExit(f"no layer XML found under {BASE}")

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    current = None
    for r in all_rows:
        key = (r["group"], r["layer_no"])
        if key != current:
            current = key
            print(f"\n[{r['group']}] {r['layer_no']} ({r['layer_table']}, coord={r['coord_no']})")
        if r["title"]:
            print(f"  {r['field_id']:<12} {r['col_id']:<18} {r['title']}")
    print(f"\nCSV -> {OUT_CSV}")


if __name__ == "__main__":
    main()
