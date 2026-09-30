import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unvotes import ABSENT, ROOT, assign_year, contested_decisions, load_config, pair_scores, weight_matrix  # noqa: E402

CFG = load_config()
Y, N, A = 0, 1, 2


def test_weights_follow_spec():
    W = weight_matrix(CFG)
    assert W[Y, Y] == W[N, N] == W[A, A] == 1.0
    assert W[Y, N] == W[N, Y] == 0.0
    assert W[Y, A] == W[A, N] == 0.5


def test_pair_scores_excludes_absences():
    # 4 decisions x 3 states
    codes = np.array([
        [Y, Y, ABSENT],
        [Y, N, N],
        [A, Y, ABSENT],
        [N, N, ABSENT],
    ])
    total, n = pair_scores(codes, weight_matrix(CFG))
    assert n[0, 1] == 4 and total[0, 1] == 1 + 0 + 0.5 + 1
    assert n[0, 2] == 1 and total[0, 2] == 0
    assert n[1, 2] == 1 and total[1, 2] == 1
    assert np.allclose(total, total.T)


def test_contested_threshold():
    rows = []
    # d1: 91 yes / 9 no -> uncontested; d2: 90 yes / 10 abstain -> contested (not > 90%)
    for i in range(100):
        rows.append(("d1", "in favor" if i < 91 else "against"))
        rows.append(("d2", "in favor" if i < 90 else "abstaining"))
    rows.append(("d1", "not voting"))
    v = pd.DataFrame(rows, columns=["decision_id", "vote"])
    assert list(contested_decisions(v, CFG)) == ["d2"]


def test_session_year_rule():
    v = pd.DataFrame({
        "session_id": ["RS-077", "RS-011", "ESS-001", "SS-001", "ESS-011", "ESS-011"],
        "meeting_date": pd.to_datetime(["2023-09-01", "1957-09-13", "1956-11-01", "1947-05-05",
                                        "2022-03-02", "2022-10-12"]),
    })
    assert assign_year(v, CFG).tolist() == [2022, 1956, 1956, 1946, 2021, 2022]


# --- Snapshot checks on built output (run build.py first) ---
DATA = ROOT / CFG["output_dir"]


def score(ref, other, year):
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    d = json.loads((DATA / "ref" / f"{ref}.json").read_text())["d"]
    cell = d[str(other)][meta["years"].index(year)]
    return None if cell is None else cell[0] / 1000


@pytest.mark.skipif(not (DATA / "meta.json").exists(), reason="build output missing")
@pytest.mark.parametrize("ref,other,year,lo,hi", [
    (2, 200, 2022, 0.85, 1.0),    # US-UK close
    (2, 365, 1985, 0.0, 0.3),     # US-USSR Cold War
    (2, 365, 1995, 0.45, 0.8),    # post-Cold War thaw
    (2, 666, 2015, 0.85, 1.0),    # US-Israel
    (365, 710, 2020, 0.75, 1.0),  # Russia-China
])
def test_known_pairs(ref, other, year, lo, hi):
    s = score(ref, other, year)
    assert s is not None and lo <= s <= hi, s


@pytest.mark.skipif(not (DATA / "meta.json").exists(), reason="build output missing")
def test_symmetry_and_statuses():
    assert score(2, 710, 2000) == score(710, 2, 2000)
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    yi = meta["years"].index
    assert meta["countries"]["560"]["status"][yi(1980)] == meta["status_codes"]["suspended"]
    assert meta["countries"]["255"]["status"][yi(1980)] == meta["status_codes"]["non_member"]
    assert meta["year_info"][yi(1964)]["decisions"] == 0


@pytest.mark.skipif(not (DATA / "geo.json").exists(), reason="geo output missing")
def test_geo_covers_every_voting_state():
    """Every state with a scored seat in a session has a visible polygon (directly or via score_from)."""
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    geo = json.loads((DATA / "geo.json").read_text(encoding="utf-8"))
    props = [g["properties"] for g in geo["objects"]["f"]["geometries"]]
    seated = {o["value"] for o in meta["map_overrides"] if o["kind"] == "score_from"}
    for yi, y in enumerate(meta["years"]):
        shown = {p.get("c") for p in props if p["k"] != "occ" and any(a <= y <= b for a, b in p["y"])}
        shown |= {o["value"] for o in meta["map_overrides"]
                  if o["kind"] == "score_from" and o["from_year"] <= y <= o["to_year"] and o["cow"] in shown}
        voting = {int(c) for c, v in meta["countries"].items() if v["status"][yi] == meta["status_codes"]["member"]}
        missing = voting - shown
        # Late joiners of 1991/1992 cast no contested votes before the snapshot date (see README).
        allowed = {1991: {331, 344, 346, 349, 359, 371, 373, 703}, 1992: {316, 317}}.get(y, set())
        assert missing <= allowed | seated, (y, sorted(missing - allowed))


@pytest.mark.skipif(not (DATA / "geo.json").exists(), reason="geo output missing")
def test_geo_keeps_large_landmasses():
    """Simplification once dropped mainland Australia; check big countries keep their area."""
    import geopandas as gpd

    geo = gpd.read_file(DATA / "geo.json").set_crs(4326, allow_override=True)
    km2 = geo.to_crs("ESRI:54009").area / 1e6
    expected = {"Australia": 7.69e6, "Brazil": 8.5e6, "Canada": 9.0e6, "India": 3.2e6}
    for name, area in expected.items():
        got = km2[geo["n"] == name]
        assert len(got) and (got > 0.9 * area).all(), (name, list(got.round()))
