"""
Tendency Evaluator Module

Analyzes historical draft data to produce per-team tendency and chaos score
profiles.  These profiles are designed to feed into ``DraftSimulator`` in a
future phase, where their weighting will be manually tunable by the user.

**Tendency** measures a team's hitting-vs-pitching preference:
  * -1.0 → all batters drafted
  *  0.0 → perfectly balanced
  * +1.0 → all pitchers drafted

**Chaos score** measures how far a team deviates from "optimal" (value-based)
drafting:
  *  1   → most predictable / always picks best available value
  * 10   → most chaotic / large deviations from optimal

Both metrics are computed per-year, then averaged across all available years.
Raw intermediate values are preserved so the user can manually tune weights
later.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .history_manager import (
    HISTORY_DIR,
    list_available_years,
    load_draft_results,
)


# --- Private Helpers ---

def _compute_tendency_score(results_df: pd.DataFrame, team_name: str) -> float:
    """Compute tendency for a single team in a single year.

    Tendency is defined as ``(n_pitchers - n_batters) / total_picks``.

    Args:
        results_df: Draft results DataFrame with at least ``team_name`` and
            ``is_pitcher`` columns.
        team_name: The team whose tendency to compute.

    Returns:
        Float from -1.0 (all batters) to +1.0 (all pitchers).  Returns 0.0
        when the team has no picks.
    """
    team_picks = results_df[results_df["team_name"] == team_name]
    total = len(team_picks)
    if total == 0:
        return 0.0

    n_pitchers = int(team_picks["is_pitcher"].sum())
    n_batters = total - n_pitchers
    return (n_pitchers - n_batters) / total


def _compute_chaos_score(
    results_df: pd.DataFrame,
    team_name: str,
    all_player_dollars: Optional[pd.DataFrame] = None,
) -> float:
    """Compute chaos score for a single team in a single year.

    Walks through the draft in pick order, tracking which players have been
    drafted.  For each pick belonging to *team_name*, the deviation between
    the optimal available value and the actual pick value is recorded.  The
    mean deviation is returned.

    Args:
        results_df: Draft results DataFrame sorted by ``pick_number``.
            Must contain ``pick_number``, ``team_name``, ``player_id``,
            and ``dollars`` columns.
        team_name: The team whose chaos to compute.
        all_player_dollars: Optional DataFrame with ``player_id`` and
            ``dollars`` columns used as the dollar-value lookup.  When
            *None*, dollar values are taken from *results_df*.

    Returns:
        Float from 0.0 (perfectly optimal) approaching 1.0 (maximally
        chaotic).  Returns 0.0 when the team has no picks.
    """
    sorted_df = results_df.sort_values("pick_number").reset_index(drop=True)

    # Build dollar lookup
    if all_player_dollars is not None:
        dollar_map: Dict[str, float] = dict(
            zip(
                all_player_dollars["player_id"].astype(str),
                all_player_dollars["dollars"].astype(float),
            )
        )
    else:
        dollar_map = dict(
            zip(
                sorted_df["player_id"].astype(str),
                sorted_df["dollars"].astype(float),
            )
        )

    all_player_ids = set(dollar_map.keys())
    drafted_ids: set = set()
    deviations: List[float] = []

    for _, row in sorted_df.iterrows():
        pid = str(row["player_id"])

        if row["team_name"] == team_name:
            # Available players: those with known values not yet drafted
            available_dollars = [
                dollar_map[p] for p in all_player_ids if p not in drafted_ids
            ]

            optimal_value = max(available_dollars) if available_dollars else 0.0
            actual_value = dollar_map.get(pid, 0.0)

            if optimal_value > 0:
                deviation = (optimal_value - actual_value) / optimal_value
            else:
                deviation = 0.0

            deviations.append(deviation)

        # Mark player as drafted regardless of team
        drafted_ids.add(pid)

    if not deviations:
        return 0.0

    return float(np.mean(deviations))


def _normalize_chaos_scores(profiles: List[Dict]) -> None:
    """Re-normalize chaos scores across all profiles using min-max scaling.

    After individual ``evaluate_team`` calls produce per-team chaos values,
    this function rescales them relative to the group so the full 1–10 range
    is utilised.  The team with the lowest ``chaos_raw`` receives a score of
    1 and the team with the highest receives 10.

    The list is modified **in place**.
    """
    raw_values = [p["chaos_raw"] for p in profiles]
    if not raw_values:
        return

    min_raw = min(raw_values)
    max_raw = max(raw_values)

    for p in profiles:
        if max_raw == min_raw:
            # All teams have the same chaos – assign a neutral score
            p["chaos_score"] = 1
        else:
            normalized = (p["chaos_raw"] - min_raw) / (max_raw - min_raw)
            p["chaos_score"] = int(np.clip(np.round(normalized * 9 + 1), 1, 10))


# --- Public Functions ---

def evaluate_team(
    team_name: str,
    years: Optional[List[int]] = None,
    history_dir: str = HISTORY_DIR,
) -> Dict:
    """Build a full tendency profile for a single team across multiple years.

    For each year the team's tendency and chaos scores are computed from
    the saved draft results.  The per-year values are then averaged to
    produce aggregate scores.

    Args:
        team_name: Fantasy team name to evaluate.
        years: List of draft years to include.  When *None*, all years
            returned by ``list_available_years()`` are used.
        history_dir: Root directory for historical data.

    Returns:
        Dict containing ``team_name``, ``tendency``, ``tendency_label``,
        ``chaos_score`` (1–10), ``chaos_raw`` (0.0–1.0), and
        ``yearly_details`` list.
    """
    if years is None:
        years = list_available_years(history_dir=history_dir)

    yearly_details: List[Dict] = []

    for year in years:
        df = load_draft_results(year, history_dir=history_dir)
        if df is None:
            continue

        tendency = _compute_tendency_score(df, team_name)
        chaos = _compute_chaos_score(df, team_name)
        picks = int((df["team_name"] == team_name).sum())

        yearly_details.append({
            "year": year,
            "tendency": tendency,
            "chaos_raw": chaos,
            "picks": picks,
        })

    if yearly_details:
        avg_tendency = float(np.mean([d["tendency"] for d in yearly_details]))
        avg_chaos_raw = float(np.mean([d["chaos_raw"] for d in yearly_details]))
    else:
        avg_tendency = 0.0
        avg_chaos_raw = 0.0

    # Normalize chaos to 1-10 scale
    chaos_score = int(np.clip(np.round(avg_chaos_raw * 9 + 1), 1, 10))

    # Label tendency
    if avg_tendency < -0.15:
        tendency_label = "hitting"
    elif avg_tendency > 0.15:
        tendency_label = "pitching"
    else:
        tendency_label = "balanced"

    return {
        "team_name": team_name,
        "tendency": avg_tendency,
        "tendency_label": tendency_label,
        "chaos_score": chaos_score,
        "chaos_raw": avg_chaos_raw,
        "yearly_details": yearly_details,
    }


def evaluate_all_teams(
    years: Optional[List[int]] = None,
    history_dir: str = HISTORY_DIR,
) -> List[Dict]:
    """Discover all team names across specified years and evaluate each.

    Args:
        years: List of draft years to include.  When *None*, all years
            returned by ``list_available_years()`` are used.
        history_dir: Root directory for historical data.

    Returns:
        List of profile dicts (one per team), sorted by team name.
    """
    if years is None:
        years = list_available_years(history_dir=history_dir)

    team_names: set = set()
    for year in years:
        df = load_draft_results(year, history_dir=history_dir)
        if df is not None:
            team_names.update(df["team_name"].dropna().unique().tolist())

    profiles = [
        evaluate_team(name, years=years, history_dir=history_dir)
        for name in sorted(team_names)
    ]

    # Re-normalize chaos scores relative to the group so the full 1-10
    # range is used instead of everyone clustering high.
    _normalize_chaos_scores(profiles)

    return profiles


def save_profiles(
    profiles: List[Dict],
    profiles_dir: str = "profiles",
) -> str:
    """Save a list of team profile dicts to ``<profiles_dir>/tendencies.json``.

    The output file contains a ``generated_at`` timestamp, a
    ``years_analyzed`` list (union of all years across profiles), and the
    full ``profiles`` list.

    Args:
        profiles: List of profile dicts as returned by ``evaluate_team``.
        profiles_dir: Directory in which to save the file.

    Returns:
        Filepath of the saved JSON file.
    """
    os.makedirs(profiles_dir, exist_ok=True)

    # Collect all years mentioned in yearly_details
    all_years: set = set()
    for p in profiles:
        for detail in p.get("yearly_details", []):
            all_years.add(detail["year"])

    output = {
        "generated_at": datetime.now().isoformat(),
        "years_analyzed": sorted(all_years),
        "profiles": profiles,
    }

    filepath = os.path.join(profiles_dir, "tendencies.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


def load_profiles(profiles_dir: str = "profiles") -> Optional[Dict]:
    """Load ``tendencies.json`` from the profiles directory.

    Args:
        profiles_dir: Directory containing the profiles file.

    Returns:
        Dict with ``generated_at``, ``years_analyzed``, and ``profiles``
        keys, or *None* if the file does not exist.
    """
    filepath = os.path.join(profiles_dir, "tendencies.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
