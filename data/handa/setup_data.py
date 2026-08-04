"""Extract the Handa open-data archives into the layout the scripts expect.

The distributed zips contain one nested zip per GIS layer:

    suidou.zip -> suidou/22001.zip -> suidou/22001/22001.shp ...

Run this once after cloning the repository (stdlib only, no dependencies):

    python setup_data.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).parent
GROUPS = ["suidou", "gesui_usui", "gesui_osui"]


def main() -> None:
    for group in GROUPS:
        archive = HERE / f"{group}.zip"
        if not archive.exists():
            raise SystemExit(f"missing archive: {archive.name} — "
                             "download it from the Handa City open-data page "
                             "(see README.md)")
        group_dir = HERE / group
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(group_dir)
        n_layers = 0
        for nested in sorted(group_dir.glob("*.zip")):
            with zipfile.ZipFile(nested) as zf:
                zf.extractall(group_dir / nested.stem)
            n_layers += 1
        print(f"{group}: {n_layers} layers extracted")
    print("done")


if __name__ == "__main__":
    main()
