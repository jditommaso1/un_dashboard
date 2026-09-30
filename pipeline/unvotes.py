"""Core transforms: load UNGA-DM votes, assign years, flag contested votes, score pairs."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
VOTE_CODES = {"in favor": 0, "against": 1, "abstaining": 2}  # index into the weight matrix
ABSENT = -1


def load_config(path: Path | str = ROOT / "pipeline" / "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_votes(cfg: dict) -> pd.DataFrame:
    cols = ["decision_id", "member_state_id", "member_state", "original_seat_name",
            "original_vote", "amended_vote", "session_id", "decision_topic", "meeting_date"]
    v = pd.read_csv(ROOT / cfg["source"]["votes_csv"], usecols=cols, low_memory=False)
    v["meeting_date"] = pd.to_datetime(v["meeting_date"])
    v["vote"] = v[cfg["vote_column"]]
    return v


def assign_year(v: pd.DataFrame, cfg: dict) -> pd.Series:
    """Session year (regular session n -> 1945 + n; others by date cutoff) or calendar year."""
    date = v["meeting_date"]
    if cfg["year_basis"] == "calendar":
        return date.dt.year
    if cfg["year_basis"] != "session":
        raise ValueError(f"unknown year_basis {cfg['year_basis']!r}")
    month, day = (int(x) for x in cfg["session_cutoff"].split("-"))
    before_cutoff = (date.dt.month < month) | ((date.dt.month == month) & (date.dt.day < day))
    by_date = date.dt.year - before_cutoff.astype(int)
    regular = v["session_id"].str.match(r"^RS-\d+$")
    by_number = 1945 + v["session_id"].str.extract(r"^RS-(\d+)$")[0].astype(float)
    return by_number.where(regular, by_date).astype(int)


def contested_decisions(v: pd.DataFrame, cfg: dict) -> pd.Index:
    """Decision ids where no single option exceeds `threshold` of the denominator votes."""
    c = cfg["contested"]
    counted = v[v["vote"].isin(c["denominator"])]
    tally = counted.groupby(["decision_id", "vote"]).size().unstack(fill_value=0)
    share = tally.max(axis=1) / tally.sum(axis=1)
    if not c["enabled"]:
        return share.index
    return share.index[share <= c["threshold"]]


def weight_matrix(cfg: dict) -> np.ndarray:
    s = cfg["scoring"]
    # rows/cols: yes, no, abstain
    return np.array([
        [s["same"], s["yes_vs_no"], s["vote_vs_abstain"]],
        [s["yes_vs_no"], s["same"], s["vote_vs_abstain"]],
        [s["vote_vs_abstain"], s["vote_vs_abstain"], s["same"]],
    ])


def pair_scores(codes: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """All-pairs agreement for one year.

    codes: (decisions x countries) int array of VOTE_CODES, ABSENT where the state
    did not cast a yes/no/abstain vote. Returns (score_sum, n) as countries x countries,
    where n counts decisions both states voted on.
    """
    onehot = [(codes == k).astype(np.float64) for k in range(3)]
    n = sum(onehot)  # participation indicator
    n = n.T @ n
    total = np.zeros_like(n)
    for a in range(3):
        for b in range(3):
            if W[a, b]:
                total += W[a, b] * (onehot[a].T @ onehot[b])
    return total, n


def border_snapshots(v: pd.DataFrame, contested: pd.Index, years: list[int]) -> dict[int, pd.Timestamp]:
    """Date whose borders represent each session: the median date of its contested votes
    (by then half of them had been cast). Years with no votes use 1 December."""
    cast = v[(v["code"] != ABSENT) & v["decision_id"].isin(contested)]
    med = cast.groupby("year")["meeting_date"].median().dt.normalize()
    return {y: med.get(y, pd.Timestamp(f"{y}-12-01")) for y in years}


def prepare(cfg: dict) -> pd.DataFrame:
    """Votes restricted to the configured decision set, with year and vote code."""
    v = load_votes(cfg)
    v["year"] = assign_year(v, cfg)
    v = v[v["decision_topic"].isin(cfg["decision_topics"])].copy()
    v["code"] = v["vote"].map(VOTE_CODES).fillna(ABSENT).astype(int)
    return v
