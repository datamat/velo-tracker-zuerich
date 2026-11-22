"""Velo Tracker Zürich – weekly snapshot, run by GitHub (see .github/workflows/snapshot.yml).

Saves the bike network plus current roadworks into snapshots/<date>/ of the
repository, so the git history becomes the time series of the network.
Not meant for double-click: on your PC, 1_Collect_data.bat does the same and more.
"""
import os
import sys
from pathlib import Path

import common as C
import collect_data as K

KEYS = ("velonetz", "tiefbau")


def main():
    out = Path(os.environ.get("SNAPSHOT_DIR", "."))
    ok = True
    for src in C.sources():
        if src["key"] in KEYS:
            print(src["title_de"])
            try:
                K.collect_geo(src, out)
            except Exception as e:
                print("   failed:", e)
                ok = False
    try:
        K.collect_city_page(out)
    except Exception as e:
        print("   city page failed:", e)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
