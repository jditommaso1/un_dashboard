"""Download raw inputs into data/raw/ (not committed).

Usage: uv run python pipeline/fetch.py
"""
from __future__ import annotations

import lzma
import tarfile
import urllib.request
from pathlib import Path

from unvotes import ROOT, load_config

CSHAPES_PKG = "https://icr.ethz.ch/data/cshapes/cshapes_2.0.tar.gz"
CSHAPES_COW = "cshapes/inst/extdata/cshapes_2_cow.topojson.xz"
NATURAL_EARTH = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
                 "ne_50m_admin_0_map_units.geojson")


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"exists: {dest.relative_to(ROOT)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def main() -> None:
    cfg = load_config()
    src = cfg["source"]
    download(src["votes_url"], ROOT / src["votes_csv"])
    download(src["decisions_url"], ROOT / src["decisions_csv"])
    download(src["codebook_url"], ROOT / src["codebook_pdf"])

    # CShapes 2.0, Correlates of War edition (ships inside the R package tarball).
    cs_dir = ROOT / "data" / "raw" / "cshapes"
    pkg = cs_dir / "cshapes_2.0.tar.gz"
    download(CSHAPES_PKG, pkg)
    out = cs_dir / "cshapes_2_cow.topojson"
    if not out.exists():
        with tarfile.open(pkg) as tar:
            data = tar.extractfile(CSHAPES_COW).read()
        out.write_bytes(lzma.decompress(data))
        print(f"extracted {out.relative_to(ROOT)}")

    # Natural Earth 1:50m map units (public domain), fills places CShapes leaves blank.
    download(NATURAL_EARTH, ROOT / "data" / "raw" / "naturalearth" / "ne_50m_admin_0_map_units.geojson")


if __name__ == "__main__":
    main()
