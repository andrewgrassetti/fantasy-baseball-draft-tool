"""
History Manager Module

Handles saving and loading historical draft data for future tendency analysis.
Follows the same patterns as src/persistence.py.
"""
import io
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


# --- Constants ---

HISTORY_DIR = "history"
PROFILES_DIR = "profiles"

DRAFT_RESULTS_COLUMNS = [
    "pick_number",   # int:   Overall pick number (1-indexed)
    "round",         # int:   Draft round
    "team_name",     # str:   Fantasy team name
    "player_name",   # str:   Player's display name
    "player_id",     # str:   FanGraphs PlayerId
    "position",      # str:   Player's position (e.g., "SS", "SP", "OF")
    "is_pitcher",    # bool:  True if pitcher, False if batter
    "dollars",       # float: Projected dollar value at time of draft
]


# --- Public Functions ---

def save_draft_results(
    year: int,
    draft_results: pd.DataFrame,
    draft_order_csv: Optional[str] = None,
    keeper_config: Optional[dict] = None,
    projection_files: Optional[Dict[str, str]] = None,
    history_dir: str = HISTORY_DIR,
) -> str:
    """Save a completed draft's results to ``history/<year>/``.

    Args:
        year: The draft year (e.g., 2026).
        draft_results: DataFrame matching DRAFT_RESULTS_COLUMNS schema.
        draft_order_csv: Optional raw CSV string of the draft order used that
            year.
        keeper_config: Optional keeper config dict in the same format as
            ``engine.export_keeper_config()``.
        projection_files: Optional dict mapping filename -> file content for
            that year's projection CSVs.
        history_dir: Root directory for historical data (default: ``history``).

    Returns:
        Path to the year directory where files were saved.
    """
    year_dir = os.path.join(history_dir, str(year))
    os.makedirs(year_dir, exist_ok=True)

    # Save draft results CSV
    results_path = os.path.join(year_dir, "draft_results.csv")
    draft_results.to_csv(results_path, index=False)

    # Save optional draft order CSV
    if draft_order_csv is not None:
        order_path = os.path.join(year_dir, "draft_order.csv")
        with open(order_path, "w", encoding="utf-8") as f:
            f.write(draft_order_csv)

    # Save optional keeper config
    if keeper_config is not None:
        keeper_path = os.path.join(year_dir, "keeper_config.json")
        with open(keeper_path, "w", encoding="utf-8") as f:
            json.dump(keeper_config, f, indent=2, ensure_ascii=False)

    # Save optional projection files
    if projection_files:
        projections_dir = os.path.join(year_dir, "projections")
        os.makedirs(projections_dir, exist_ok=True)
        for filename, content in projection_files.items():
            proj_path = os.path.join(projections_dir, filename)
            with open(proj_path, "w", encoding="utf-8") as f:
                f.write(content)

    # Build and save metadata
    team_list = sorted(draft_results["team_name"].dropna().unique().tolist())
    metadata = {
        "year": year,
        "timestamp": datetime.now().isoformat(),
        "total_picks": len(draft_results),
        "team_list": team_list,
        "has_projections": projection_files is not None and len(projection_files) > 0,
    }
    metadata_path = os.path.join(year_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return year_dir


def load_draft_results(
    year: int, history_dir: str = HISTORY_DIR
) -> Optional[pd.DataFrame]:
    """Load ``draft_results.csv`` for a given year.

    Args:
        year: The draft year to load (e.g., 2026).
        history_dir: Root directory for historical data (default: ``history``).

    Returns:
        DataFrame with DRAFT_RESULTS_COLUMNS schema, or None if not found.
    """
    results_path = os.path.join(history_dir, str(year), "draft_results.csv")
    if not os.path.exists(results_path):
        return None
    return pd.read_csv(results_path)


def load_draft_order(
    year: int, history_dir: str = HISTORY_DIR
) -> Optional[str]:
    """Load the draft order CSV string for a given year.

    Args:
        year: The draft year to load (e.g., 2026).
        history_dir: Root directory for historical data (default: ``history``).

    Returns:
        Raw CSV string of the draft order, or None if not found.
    """
    order_path = os.path.join(history_dir, str(year), "draft_order.csv")
    if not os.path.exists(order_path):
        return None
    with open(order_path, "r", encoding="utf-8") as f:
        return f.read()


def load_keeper_config(
    year: int, history_dir: str = HISTORY_DIR
) -> Optional[dict]:
    """Load keeper config JSON for a given year.

    Args:
        year: The draft year to load (e.g., 2026).
        history_dir: Root directory for historical data (default: ``history``).

    Returns:
        Keeper config dict, or None if not found.
    """
    keeper_path = os.path.join(history_dir, str(year), "keeper_config.json")
    if not os.path.exists(keeper_path):
        return None
    with open(keeper_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_available_years(history_dir: str = HISTORY_DIR) -> List[int]:
    """Scan the history directory and return sorted list of years with results.

    Args:
        history_dir: Root directory for historical data (default: ``history``).

    Returns:
        Sorted list of integer years that have a ``draft_results.csv`` file.
    """
    if not os.path.exists(history_dir):
        return []

    years = []
    for entry in os.listdir(history_dir):
        year_dir = os.path.join(history_dir, entry)
        if not os.path.isdir(year_dir):
            continue
        try:
            year = int(entry)
        except ValueError:
            continue
        results_path = os.path.join(year_dir, "draft_results.csv")
        if os.path.exists(results_path):
            years.append(year)

    return sorted(years)


def collect_projection_files(data_dir: str = "data") -> Dict[str, str]:
    """Read all CSV files from the data directory and return as filename→content mapping.

    This is used to archive the projection CSVs alongside draft results so that
    the exact inputs used for a draft are preserved in the history folder.

    Args:
        data_dir: Path to the data directory (default: ``data``).

    Returns:
        Dict mapping filename to file content for each CSV found.  Returns an
        empty dict if the directory does not exist or contains no CSVs.
    """
    if not os.path.isdir(data_dir):
        return {}

    files: Dict[str, str] = {}
    for entry in sorted(os.listdir(data_dir)):
        if not entry.lower().endswith(".csv"):
            continue
        filepath = os.path.join(data_dir, entry)
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                files[entry] = f.read()
        except (OSError, UnicodeDecodeError):
            # Skip files that can't be read
            continue

    return files


def build_draft_results_from_engine(
    engine,
    draft_order_csv: str,
) -> pd.DataFrame:
    """Convert a completed DraftEngine state into the historical draft_results DataFrame.

    Reconstructs the pick order from the draft order CSV and maps each pick to
    the player actually drafted by that team.  Both "Drafted" and "Keeper" status
    players are collected from ``engine.bat_df`` and ``engine.pitch_df``.

    Args:
        engine: A completed ``DraftEngine`` instance.
        draft_order_csv: Raw CSV string of the draft order used (same format as
            accepted by ``DraftSimulator``).  Expected columns: ``player_name``
            (team name), ``pick_number``, and optionally ``tendency``.

    Returns:
        DataFrame with DRAFT_RESULTS_COLUMNS schema, one row per picked player,
        ordered by pick_number.
    """
    # Parse the draft order CSV to get the ordered team sequence
    order_df = pd.read_csv(io.StringIO(draft_order_csv))

    # Normalize column names to lowercase for robustness
    order_df.columns = [c.strip().lower() for c in order_df.columns]

    # Determine team-name column (supports 'player_name' or 'team_name')
    if "player_name" in order_df.columns:
        team_col = "player_name"
    elif "team_name" in order_df.columns:
        team_col = "team_name"
    else:
        # Fallback: first column
        team_col = order_df.columns[0]

    # Sort by pick_number to ensure correct order
    if "pick_number" in order_df.columns:
        order_df = order_df.sort_values("pick_number").reset_index(drop=True)

    # Collect all drafted / keeper players from both DataFrames
    drafted_statuses = {"Drafted", "Keeper"}

    bat_taken = engine.bat_df[engine.bat_df["Status"].isin(drafted_statuses)].copy()
    bat_taken["_is_pitcher"] = False

    pitch_taken = engine.pitch_df[engine.pitch_df["Status"].isin(drafted_statuses)].copy()
    pitch_taken["_is_pitcher"] = True

    all_taken = pd.concat([bat_taken, pitch_taken], ignore_index=True)

    # Build a lookup: team_name -> list of players (in roster order)
    team_players: Dict[str, list] = {name: [] for name in engine.teams}
    for team_name, team in engine.teams.items():
        for player in team.roster:
            team_players[team_name].append(player)

    # Build the result rows by iterating through the draft order
    # For each pick slot, find which player was assigned to that team
    rows = []
    team_pick_index: Dict[str, int] = {name: 0 for name in engine.teams}

    total_teams = len(order_df)

    for _, order_row in order_df.iterrows():
        pick_number = int(order_row.get("pick_number", len(rows) + 1))
        team_name = str(order_row[team_col])

        # Round is 1-indexed: determined from position in the draft order
        # (pick_number - 1) // total_teams gives 0-indexed round
        round_num = ((pick_number - 1) // total_teams) + 1 if total_teams > 0 else 1

        players_for_team = team_players.get(team_name, [])
        idx = team_pick_index.get(team_name, 0)

        if idx >= len(players_for_team):
            # No player recorded for this pick slot — skip
            team_pick_index[team_name] = idx + 1
            continue

        player = players_for_team[idx]
        team_pick_index[team_name] = idx + 1

        # Look up dollar value from the source DataFrame
        dollars = player.dollars
        if dollars is None or (isinstance(dollars, float) and pd.isna(dollars)):
            dollars = 0.0

        rows.append({
            "pick_number": pick_number,
            "round": round_num,
            "team_name": team_name,
            "player_name": player.name,
            "player_id": str(player.player_id),
            "position": player.position,
            "is_pitcher": player.is_pitcher,
            "dollars": float(dollars),
        })

    result_df = pd.DataFrame(rows, columns=DRAFT_RESULTS_COLUMNS)
    return result_df.sort_values("pick_number").reset_index(drop=True)
