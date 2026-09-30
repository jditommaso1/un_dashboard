"""Build site/data/*.json from UNGA-DM votes.

Usage: uv run python pipeline/build.py [--config pipeline/config.yaml]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from unvotes import ABSENT, ROOT, contested_decisions, load_config, pair_scores, prepare, weight_matrix

# Country-year status codes written to meta.json
NON_MEMBER, MEMBER, ABSENT_ALL, SUSPENDED = 0, 1, 2, 3


def historical_names(cfg_dir: Path) -> pd.DataFrame:
    return pd.read_csv(cfg_dir / "historical_names.csv", comment="#")


def country_year_status(v: pd.DataFrame, years: list[int], codes: list[int], cfg: dict) -> dict[int, list[int]]:
    rows = v.groupby(["member_state_id", "year"]).size()
    voted = v[v["code"] != ABSENT].groupby(["member_state_id", "year"]).size()
    suspended_code = v[v["vote"] == "not voting (suspended)"].groupby(["member_state_id", "year"]).size()
    windows = {(s["cow"], y) for s in cfg.get("suspensions", []) for y in range(s["from"], s["to"] + 1)}
    out = {}
    for c in codes:
        st = []
        for y in years:
            if rows.get((c, y), 0) == 0:
                st.append(NON_MEMBER)
            elif voted.get((c, y), 0) > 0:
                st.append(MEMBER)
            elif (c, y) in windows or suspended_code.get((c, y), 0) > 0:
                st.append(SUSPENDED)
            else:
                st.append(ABSENT_ALL)
        out[c] = st
    return out


def build(cfg: dict, out_dir: Path) -> dict:
    v = prepare(cfg)
    contested = contested_decisions(v, cfg)
    vc = v[v["decision_id"].isin(contested)]

    codes = sorted(v["member_state_id"].unique().tolist())
    idx = {c: i for i, c in enumerate(codes)}
    years = list(range(int(v["year"].min()), int(v["year"].max()) + 1))
    W = weight_matrix(cfg)

    S = np.zeros((len(years), len(codes), len(codes)))
    N = np.zeros_like(S)
    for yi, y in enumerate(years):
        vy = vc[vc["year"] == y]
        if vy.empty:
            continue
        m = vy.pivot(index="decision_id", columns="member_state_id", values="code")
        m = m.reindex(columns=codes).fillna(ABSENT).astype(int).to_numpy()
        S[yi], N[yi] = pair_scores(m, W)

    status = country_year_status(v, years, codes, cfg)

    # Per-reference files: for each other country, scores (0-1000) and vote counts by year.
    ref_dir = out_dir / "ref"
    if ref_dir.exists():
        shutil.rmtree(ref_dir)
    ref_dir.mkdir(parents=True)
    for r in codes:
        ri = idx[r]
        entries = {}
        for c in codes:
            if c == r:
                continue
            n = N[:, ri, idx[c]]
            if not n.any():
                continue
            s = np.divide(S[:, ri, idx[c]], n, out=np.full(len(years), np.nan), where=n > 0)
            entries[str(c)] = [
                [int(round(sv * 1000)), int(nv)] if nv > 0 else None for sv, nv in zip(s, n)
            ]
        with open(ref_dir / f"{r}.json", "w", encoding="utf-8") as f:
            json.dump({"ref": r, "d": entries}, f, separators=(",", ":"))

    # Year-level info (all configured decisions vs contested subset).
    dec = v.drop_duplicates("decision_id")
    per_year = dec.groupby("year").size()
    per_year_c = dec[dec["decision_id"].isin(contested)].groupby("year").size()
    year_info = [
        {"year": y, "decisions": int(per_year.get(y, 0)), "contested": int(per_year_c.get(y, 0)),
         "session": y - 1945 if cfg["year_basis"] == "session" else None}
        for y in years
    ]

    names = historical_names(ROOT / "pipeline")
    common = v.drop_duplicates("member_state_id").set_index("member_state_id")["member_state"]
    countries = {}
    for c in codes:
        hn = names[names["cow"] == c]
        countries[str(c)] = {
            "name": common[c],
            "hist": [[int(r.from_year), int(r.to_year), r.name] for r in hn.itertuples()],
            "status": status[c],
        }

    meta = {
        "years": years,
        "year_info": year_info,
        "countries": countries,
        "featured_refs": cfg["featured_refs"],
        "predecessors": pd.read_csv(ROOT / "pipeline" / "predecessors.csv", comment="#").to_dict("records"),
        "map_overrides": pd.read_csv(ROOT / "pipeline" / "map_overrides.csv", comment="#")
            .astype({"value": "Int64"}).astype(object).where(lambda d: d.notna(), None).to_dict("records"),
        "status_codes": {"non_member": NON_MEMBER, "member": MEMBER, "absent": ABSENT_ALL, "suspended": SUSPENDED},
        "config": {k: cfg[k] for k in ["vote_column", "decision_topics", "year_basis", "session_cutoff",
                                        "contested", "scoring", "min_votes", "suspensions"]},
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, separators=(",", ":"), ensure_ascii=False)
    return {"S": S, "N": N, "codes": codes, "years": years, "contested": contested}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "pipeline" / "config.yaml"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = ROOT / cfg["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    res = build(cfg, out)
    size = sum(p.stat().st_size for p in (out / "ref").glob("*.json"))
    print(f"{len(res['codes'])} countries, {len(res['years'])} years, {len(res['contested'])} contested votes; "
          f"ref files {size / 1e6:.1f} MB, meta {(out / 'meta.json').stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
