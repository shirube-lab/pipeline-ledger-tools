"""Download the environmental datasets used by work3 enrichment.

Run once after cloning (requires internet):

    python setup_env_data.py

Datasets and terms:
- NIED J-SHIS terrain/ground classification 250m mesh (2020 edition).
  Terms: attribution required; distribution of processed works is
  permitted (contact NIED if the work itself is to be sold).
  https://www.j-shis.bosai.go.jp/labs/wm2020/
- MLIT KSJ N03 administrative boundaries, Aichi 2024 (CC BY 4.0).
  Used as a coastline proxy via the dissolved outer boundary, because
  the KSJ coastline dataset (C23) is designated non-commercial.
  https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2024.html
"""

from __future__ import annotations

import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = {
    "Z-WM2020-JAPAN-M250.zip": (
        "https://www.j-shis.bosai.go.jp/labs/wm2020/data/Z-WM2020-JAPAN-M250.zip",
        "jshis",
    ),
    "N03-20240101_23_GML.zip": (
        "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2024/N03-20240101_23_GML.zip",
        "n03",
    ),
}


def main() -> None:
    for name, (url, subdir) in SOURCES.items():
        dest = HERE / name
        if not dest.exists():
            print(f"downloading {name} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r, dest.open("wb") as f:
                f.write(r.read())
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(HERE / subdir)
        print(f"{name} -> {subdir}/")
    print("done")


if __name__ == "__main__":
    main()
