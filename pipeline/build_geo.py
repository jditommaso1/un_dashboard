"""Build site/data/geo.json: historical borders for every session year.

One TopoJSON holds every polygon used in any session; each feature lists the session
years it is visible (`y`: [[from, to], ...]), so the site filters by year with no
extra downloads. Borders come from CShapes 2.0 (COW edition) at each session's
snapshot date (see unvotes.border_snapshots), with these additions:

- Ukrainian and Byelorussian SSR polygons (UN seats since 1945) cut out of the USSR,
  using their 1991 borders.
- Territory CShapes assigns to a controlling state whose annexation or occupation the UN
  did not recognise is split out as an `occ` overlay (Crimea, Israeli-occupied
  territories, Western Sahara, East Timor).
- Natural Earth map units fill places CShapes leaves blank (Greenland, small colonies
  before independence, microstates before UN admission).
- Borders after 2019 (CShapes' last year) are the 2019 borders extended.

Usage: uv run python pipeline/build_geo.py
"""
from __future__ import annotations

import json
import warnings

import geopandas as gpd
import pandas as pd
import topojson as tp
from shapely.geometry import Point

from unvotes import ROOT, border_snapshots, contested_decisions, load_config, prepare

EQUAL_AREA = "ESRI:54009"
OPEN_END = pd.Timestamp("2099-12-31")
SIMPLIFY_TOLERANCE = 0.01   # Visvalingam area, degrees^2; checked visually at world scale
FALLBACK_TOLERANCE = 0.05   # Douglas-Peucker, degrees; for features toposimplify mangles
QUANTIZATION = 1e5
warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")
SMALL_KM2 = 3000            # features below this get a capital dot on the map
MIN_PIECE_KM2 = 30          # drop slivers left by polygon differences


def load_cshapes() -> gpd.GeoDataFrame:
    g = gpd.read_file(ROOT / "data/raw/cshapes/cshapes_2_cow.topojson").set_crs(4326, allow_override=True)
    g = g[g["end"] >= "1945-01-01"].copy()
    g["end"] = g["end"].where(g["end"] < pd.Timestamp("2019-12-31"), OPEN_END)
    g["geometry"] = g.geometry.make_valid()
    g["kind"] = "cs"
    return g.reset_index(drop=True)


def row(g, cow, start):
    r = g[(g["cowcode"] == cow) & (g["start"] == pd.Timestamp(start))]
    assert len(r) == 1, (cow, start, len(r))
    return r.iloc[0]


def clean(geom):
    """Drop slivers from a (multi)polygon produced by differencing CShapes versions."""
    parts = getattr(geom, "geoms", [geom])
    s = gpd.GeoSeries(list(parts), crs=4326)
    keep = s[s.to_crs(EQUAL_AREA).area / 1e6 >= MIN_PIECE_KM2]
    return keep.union_all() if len(keep) else None


def carve(g: gpd.GeoDataFrame, cow: int, geom, start, end) -> gpd.GeoDataFrame:
    """Remove geom from `cow`'s rows over [start, end], splitting rows at the range edges."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    day = pd.Timedelta(days=1)
    out = []
    for _, r in g.iterrows():
        if r["cowcode"] != cow or r["end"] < start or r["start"] > end:
            out.append(r)
            continue
        if r["start"] < start:
            before = r.copy()
            before["end"] = start - day
            out.append(before)
        mid = r.copy()
        mid["start"], mid["end"] = max(r["start"], start), min(r["end"], end)
        mid["geometry"] = r["geometry"].difference(geom)
        out.append(mid)
        if r["end"] > end:
            after = r.copy()
            after["start"] = end + day
            out.append(after)
    return gpd.GeoDataFrame(out, crs=4326).reset_index(drop=True)


def add_soviet_republics(g):
    ussr_end = pd.Timestamp("1991-12-25")
    extra = []
    for cow, name in [(369, "Ukrainian SSR"), (370, "Byelorussian SSR")]:
        geom = row(g, cow, "1991-12-26")["geometry"]
        g = carve(g, 365, geom, "1945-08-15", ussr_end)
        extra.append({"cowcode": cow, "country_name": name, "start": pd.Timestamp("1945-08-15"),
                      "end": ussr_end, "status": "soviet republic", "owner": "365", "kind": "cs",
                      "geometry": geom})
    return pd.concat([g, gpd.GeoDataFrame(extra, crs=4326)], ignore_index=True)


def add_occupations(g):
    """Split out territory held without UN recognition; each piece becomes an `occ` feature."""
    israel_1948 = row(g, 666, "1948-05-14")["geometry"]
    pieces = {
        "sinai": row(g, 651, "1961-09-29")["geometry"],
        "golan": row(g, 652, "1961-09-29")["geometry"],
        "west_bank": g[g["cowcode"] == 6631].iloc[-1]["geometry"],
        "gaza": g[g["cowcode"] == 6511].iloc[-1]["geometry"],
    }
    labels = {
        "sinai": ("Sinai Peninsula", "Egyptian territory occupied by Israel (1967)"),
        "golan": ("Golan Heights", "Syrian territory occupied by Israel since 1967"),
        "west_bank": ("West Bank", "Palestinian territory occupied by Israel since 1967"),
        "gaza": ("Gaza Strip", "Palestinian territory occupied by Israel since 1967"),
    }
    occ = []

    def add(geom, controller, start, end, name, note):
        geom = clean(geom)
        if geom is None:
            return
        occ.append({"cowcode": controller, "country_name": name, "start": pd.Timestamp(start),
                    "end": pd.Timestamp(end), "status": "occupied", "owner": str(controller),
                    "kind": "occ", "note": note, "geometry": geom})

    for start, end in [("1967-06-10", "1979-05-25"), ("1979-05-26", OPEN_END)]:
        held = row(g, 666, start)["geometry"].difference(israel_1948)
        for key, ref in pieces.items():
            part = held.intersection(ref)
            if not part.is_empty:
                add(part, 666, start, end, *labels[key])
        g = carve(g, 666, held, start, end)

    ukr = row(g, 369, "1991-12-26")["geometry"].difference(row(g, 369, "2014-03-18")["geometry"])
    add(ukr, 365, "2014-03-18", OPEN_END, "Crimea",
        "Ukrainian territory annexed by Russia in 2014; the General Assembly affirmed Ukraine's "
        "territorial integrity (resolution 68/262)")
    g = carve(g, 365, ukr, "2014-03-18", OPEN_END)

    ws_note = "Non-self-governing territory on the UN list; controlled by {}"
    morocco_1958 = row(g, 600, "1958-04-10")["geometry"]
    maur_pre = row(g, 435, "1960-11-28")["geometry"] if len(g[(g.cowcode == 435) & (g.start == "1960-11-28")]) else \
        g[(g.cowcode == 435) & (g.end == pd.Timestamp("1975-11-13"))].iloc[0]["geometry"]
    for start, end in [("1975-11-14", "1979-08-04"), ("1979-08-05", OPEN_END)]:
        held = row(g, 600, start)["geometry"].difference(morocco_1958)
        add(held, 600, start, end, "Western Sahara", ws_note.format("Morocco"))
        g = carve(g, 600, held, start, end)
    held = row(g, 435, "1975-11-14")["geometry"].difference(maur_pre)
    add(held, 435, "1975-11-14", "1979-08-04", "Western Sahara (southern part)", ws_note.format("Mauritania"))
    g = carve(g, 435, held, "1975-11-14", "1979-08-04")

    et = row(g, 860, "2002-09-27")["geometry"]
    add(et, 850, "1976-07-17", "2002-05-19", "East Timor",
        "Annexed by Indonesia in 1976, not recognised by the UN; UN transitional administration 1999-2002")
    g = carve(g, 850, et, "1976-07-17", "2002-05-19")
    return pd.concat([g, gpd.GeoDataFrame(occ, crs=4326)], ignore_index=True)


def year_ranges(years: list[int]) -> list[list[int]]:
    out = []
    for y in years:
        if out and (y == out[-1][1] + 1 or (out[-1][1] == 1963 and y == 1965)):
            out[-1][1] = y
        else:
            out.append([y, y])
    return out


def ne_fillers(g, snapshots) -> gpd.GeoDataFrame:
    """Natural Earth units for session years in which CShapes has nothing there."""
    ne = gpd.read_file(ROOT / "data/raw/naturalearth/ne_50m_admin_0_map_units.geojson")
    ne = ne[ne["TYPE"] != "Indeterminate"].reset_index(drop=True)  # Antarctica
    ne["geometry"] = ne.geometry.make_valid()
    table = pd.read_csv(ROOT / "pipeline" / "ne_fillers.csv", comment="#").set_index("ne_name")
    ne_ea = ne.to_crs(EQUAL_AREA)
    area = ne_ea.area

    # Which CShapes code each unit stands for: the 2019 state whose capital lies in (or,
    # for atolls the 1:50m outline misses, within ~1 degree of) the unit.
    latest = g[(g["end"] == OPEN_END) & (g["kind"] == "cs") & (g["status"] == "independent")]
    unit_cow = {}
    for r in latest.itertuples():
        dist = ne.distance(Point(r.caplong, r.caplat))
        if dist.min() < 1.0:
            unit_cow.setdefault(dist.idxmin(), r.cowcode)

    # Overlap of every NE unit with every CShapes feature, computed once. Features visible
    # in the same session do not overlap, so a unit's coverage is the sum of its overlaps.
    g_ea = g.to_crs(EQUAL_AREA).geometry.buffer(0)
    overlap = {}  # (ne index, g index) -> km2
    for gi, ni in zip(*ne_ea.sindex.query(g_ea, predicate="intersects")):
        overlap[(ni, gi)] = ne_ea.geometry.iloc[ni].intersection(g_ea.iloc[gi]).area

    visible = {i: [] for i in ne.index}
    for y, d in snapshots.items():
        now = g[(g["start"] <= d) & (g["end"] >= d)]
        now_idx, now_cows = set(now.index), set(now["cowcode"])
        covered = pd.Series(0.0, index=ne.index)
        for (ni, gi), a in overlap.items():
            if gi in now_idx:
                covered[ni] += a
        for i in ne.index:
            if unit_cow.get(i) in now_cows:
                continue
            if covered[i] / area[i] < 0.5:
                visible[i].append(y)

    rows = []
    for i, ys in visible.items():
        if not ys:
            continue
        u = ne.loc[i]
        name = u["NAME_LONG"] if isinstance(u.get("NAME_LONG"), str) else u["NAME"]
        if u["NAME"] in table.index:
            ind, pre = int(table.loc[u["NAME"], "independence"]), table.loc[u["NAME"], "pre_owner"]
            dep = [y for y in ys if y < ind]
            sov = [y for y in ys if y >= ind]
            if dep:
                rows.append({"name": name, "status": "dependent", "owner_name": pre, "y": year_ranges(dep),
                             "geometry": u.geometry})
            if sov:
                rows.append({"name": name, "status": "independent", "owner_name": None, "y": year_ranges(sov),
                             "geometry": u.geometry})
        else:
            rows.append({"name": name, "status": "dependent", "owner_name": u["SOVEREIGNT"], "y": year_ranges(ys),
                         "geometry": u.geometry})
    f = gpd.GeoDataFrame(rows, crs=4326)
    f["kind"] = "ne"
    return f


def main() -> None:
    cfg = load_config()
    v = prepare(cfg)
    years = list(range(int(v["year"].min()), int(v["year"].max()) + 1))
    snapshots = border_snapshots(v, contested_decisions(v, cfg), years)

    g = load_cshapes()
    g = add_soviet_republics(g)
    g = add_occupations(g)

    # Visible session years per CShapes feature; drop features never shown.
    g["y"] = [year_ranges([y for y, d in snapshots.items() if r.start <= d <= r.end]) for r in g.itertuples()]
    g = g[g["y"].map(len) > 0].reset_index(drop=True)
    g["owner_name"] = None
    fill = ne_fillers(g, snapshots)

    cols = ["kind", "cowcode", "country_name", "status", "owner", "owner_name", "note", "caplong", "caplat", "y",
            "geometry"]
    fill = fill.rename(columns={"name": "country_name"})
    allf = pd.concat([g, fill], ignore_index=True).reindex(columns=cols)
    allf = gpd.GeoDataFrame(allf, crs=4326)
    allf["km2"] = (allf.to_crs(EQUAL_AREA).area / 1e6).round()

    topo = tp.Topology(allf[["geometry"]].assign(i=range(len(allf))), prequantize=False)
    simp = topo.toposimplify(SIMPLIFY_TOLERANCE, simplify_algorithm="vw", simplify_with="simplification",
                             prevent_oversimplify=True).to_gdf().sort_values("i")
    simp = simp.set_crs(4326, allow_override=True)
    # toposimplify occasionally collapses a whole ring (it dropped mainland Australia, keeping
    # only Tasmania). Re-simplify any feature that lost most of its area on its own.
    raw_km2 = allf.to_crs(EQUAL_AREA).area.values / 1e6
    simp_km2 = simp.to_crs(EQUAL_AREA).area.values / 1e6
    geoms = list(simp.geometry.values)
    for j in [j for j in range(len(allf)) if raw_km2[j] > MIN_PIECE_KM2 and simp_km2[j] < 0.5 * raw_km2[j]]:
        geoms[j] = allf.geometry.iloc[j].simplify(FALLBACK_TOLERANCE, preserve_topology=True)
        print(f"re-simplified {allf.country_name.iloc[j]}: {simp_km2[j]:,.0f} of {raw_km2[j]:,.0f} km2 survived toposimplify")
    simp = gpd.GeoDataFrame(geometry=geoms, crs=4326)

    props = []
    for r in allf.itertuples():
        p = {"k": r.kind, "n": r.country_name, "y": r.y, "s": r.status}
        if pd.notna(r.cowcode):
            p["c"] = int(r.cowcode)
        if isinstance(r.owner, str) and r.owner.isdigit() and int(r.owner) != p.get("c"):
            p["o"] = int(r.owner)
        if isinstance(r.owner_name, str):
            p["on"] = r.owner_name
        if isinstance(r.note, str):
            p["note"] = r.note
        if r.km2 < SMALL_KM2 and r.kind != "occ":
            pt = (Point(r.caplong, r.caplat) if pd.notna(r.caplong) else r.geometry.representative_point())
            p["pt"] = [round(pt.x, 3), round(pt.y, 3)]
        props.append(p)
    out = gpd.GeoDataFrame({"p": [json.dumps(p) for p in props]}, geometry=simp.geometry.values, crs=4326)
    topo_json = json.loads(tp.Topology(out, prequantize=QUANTIZATION, topology=True, object_name="f").to_json())
    for geom in topo_json["objects"]["f"]["geometries"]:
        geom["properties"] = json.loads(geom["properties"]["p"])

    # Era index (documentation / debugging): consecutive years sharing one polygon set.
    sets = {y: frozenset(i for i, p in enumerate(props) if any(a <= y <= b for a, b in p["y"])) for y in years}
    eras = []
    for y in years:
        if eras and sets[y] == sets[eras[-1][0]]:
            eras[-1][1] = y
        else:
            eras.append([y, y])
    topo_json["snapshots"] = {str(y): str(d.date()) for y, d in snapshots.items()}
    topo_json["eras"] = eras

    dest = ROOT / cfg["output_dir"] / "geo.json"
    dest.write_text(json.dumps(topo_json, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"{len(props)} features, {len(eras)} border eras, geo.json {dest.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
