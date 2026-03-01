"""
Unit tests for src/history_manager.py
"""
import io
import json
import os
import tempfile

import pandas as pd
import pytest

from src.history_manager import (
    DRAFT_RESULTS_COLUMNS,
    build_draft_results_from_engine,
    collect_projection_files,
    list_available_years,
    load_draft_order,
    load_draft_results,
    load_keeper_config,
    save_draft_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draft_results(n=4):
    """Return a minimal DataFrame with DRAFT_RESULTS_COLUMNS schema."""
    rows = []
    for i in range(n):
        rows.append({
            "pick_number": i + 1,
            "round": 1,
            "team_name": f"Team {(i % 2) + 1}",
            "player_name": f"Player {i + 1}",
            "player_id": str(1000 + i),
            "position": "OF" if i % 2 == 0 else "SP",
            "is_pitcher": i % 2 != 0,
            "dollars": float(10 + i),
        })
    return pd.DataFrame(rows, columns=DRAFT_RESULTS_COLUMNS)


def _make_engine(team_names=None, batters=None, pitchers=None):
    """Create a minimal DraftEngine with optional pre-drafted players."""
    from src.draft_engine import DraftEngine

    if team_names is None:
        team_names = ["Alpha", "Beta"]

    # Minimal batter DataFrame
    bat_data = {
        "PlayerId": ["b1", "b2", "b3"],
        "Name": ["Batter One", "Batter Two", "Batter Three"],
        "POS": ["OF", "1B", "SS"],
        "Team": ["NYY", "BOS", "LAD"],
        "Dollars": [20.0, 15.0, 10.0],
    }
    bat_df = pd.DataFrame(bat_data)

    # Minimal pitcher DataFrame
    pitch_data = {
        "PlayerId": ["p1", "p2"],
        "Name": ["Pitcher One", "Pitcher Two"],
        "POS": ["SP", "RP"],
        "Team": ["HOU", "ATL"],
        "Dollars": [18.0, 12.0],
    }
    pitch_df = pd.DataFrame(pitch_data)

    engine = DraftEngine(bat_df, pitch_df, team_names=team_names)
    return engine


# ---------------------------------------------------------------------------
# save_draft_results
# ---------------------------------------------------------------------------

class TestSaveDraftResults:
    def test_creates_year_directory(self, tmp_path):
        df = _make_draft_results()
        year_dir = save_draft_results(2026, df, history_dir=str(tmp_path))
        assert os.path.isdir(year_dir)
        assert year_dir == str(tmp_path / "2026")

    def test_creates_draft_results_csv(self, tmp_path):
        df = _make_draft_results()
        save_draft_results(2026, df, history_dir=str(tmp_path))
        assert os.path.exists(tmp_path / "2026" / "draft_results.csv")

    def test_saves_draft_order_csv(self, tmp_path):
        df = _make_draft_results()
        order_csv = "player_name,pick_number\nTeam 1,1\nTeam 2,2\n"
        save_draft_results(2026, df, draft_order_csv=order_csv, history_dir=str(tmp_path))
        order_file = tmp_path / "2026" / "draft_order.csv"
        assert order_file.exists()
        assert order_file.read_text() == order_csv

    def test_saves_keeper_config_json(self, tmp_path):
        df = _make_draft_results()
        keeper_cfg = {"team_names": ["Team 1", "Team 2"], "keepers": {}}
        save_draft_results(2026, df, keeper_config=keeper_cfg, history_dir=str(tmp_path))
        keeper_file = tmp_path / "2026" / "keeper_config.json"
        assert keeper_file.exists()
        loaded = json.loads(keeper_file.read_text())
        assert loaded == keeper_cfg

    def test_saves_projection_files(self, tmp_path):
        df = _make_draft_results()
        proj = {"batters.csv": "Name,Dollars\nPlayer,10\n", "pitchers.csv": "Name,Dollars\nPitcher,8\n"}
        save_draft_results(2026, df, projection_files=proj, history_dir=str(tmp_path))
        proj_dir = tmp_path / "2026" / "projections"
        assert proj_dir.is_dir()
        assert (proj_dir / "batters.csv").exists()
        assert (proj_dir / "pitchers.csv").exists()

    def test_saves_metadata_json(self, tmp_path):
        df = _make_draft_results(4)
        save_draft_results(2026, df, history_dir=str(tmp_path))
        meta_file = tmp_path / "2026" / "metadata.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert meta["year"] == 2026
        assert meta["total_picks"] == 4
        assert set(meta["team_list"]) == {"Team 1", "Team 2"}
        assert meta["has_projections"] is False

    def test_metadata_has_projections_true(self, tmp_path):
        df = _make_draft_results()
        save_draft_results(
            2026, df,
            projection_files={"b.csv": "x"},
            history_dir=str(tmp_path),
        )
        meta = json.loads((tmp_path / "2026" / "metadata.json").read_text())
        assert meta["has_projections"] is True

    def test_no_optional_files_when_not_provided(self, tmp_path):
        df = _make_draft_results()
        save_draft_results(2026, df, history_dir=str(tmp_path))
        year_dir = tmp_path / "2026"
        assert not (year_dir / "draft_order.csv").exists()
        assert not (year_dir / "keeper_config.json").exists()
        assert not (year_dir / "projections").exists()


# ---------------------------------------------------------------------------
# load_draft_results
# ---------------------------------------------------------------------------

class TestLoadDraftResults:
    def test_round_trips_dataframe(self, tmp_path):
        df = _make_draft_results(6)
        save_draft_results(2025, df, history_dir=str(tmp_path))
        loaded = load_draft_results(2025, history_dir=str(tmp_path))
        assert loaded is not None
        assert list(loaded.columns) == DRAFT_RESULTS_COLUMNS
        assert len(loaded) == 6

    def test_returns_none_for_missing_year(self, tmp_path):
        result = load_draft_results(1999, history_dir=str(tmp_path))
        assert result is None

    def test_returns_none_when_history_dir_absent(self, tmp_path):
        missing_dir = str(tmp_path / "no_such_history")
        result = load_draft_results(2026, history_dir=missing_dir)
        assert result is None

    def test_values_preserved(self, tmp_path):
        df = _make_draft_results(2)
        save_draft_results(2024, df, history_dir=str(tmp_path))
        loaded = load_draft_results(2024, history_dir=str(tmp_path))
        assert loaded.iloc[0]["player_name"] == df.iloc[0]["player_name"]
        assert loaded.iloc[0]["pick_number"] == df.iloc[0]["pick_number"]


# ---------------------------------------------------------------------------
# load_draft_order
# ---------------------------------------------------------------------------

class TestLoadDraftOrder:
    def test_round_trips_csv_string(self, tmp_path):
        df = _make_draft_results()
        order_csv = "player_name,pick_number\nTeam 1,1\nTeam 2,2\n"
        save_draft_results(2026, df, draft_order_csv=order_csv, history_dir=str(tmp_path))
        loaded = load_draft_order(2026, history_dir=str(tmp_path))
        assert loaded == order_csv

    def test_returns_none_when_not_saved(self, tmp_path):
        df = _make_draft_results()
        save_draft_results(2026, df, history_dir=str(tmp_path))
        assert load_draft_order(2026, history_dir=str(tmp_path)) is None

    def test_returns_none_for_missing_year(self, tmp_path):
        assert load_draft_order(1999, history_dir=str(tmp_path)) is None


# ---------------------------------------------------------------------------
# load_keeper_config
# ---------------------------------------------------------------------------

class TestLoadKeeperConfig:
    def test_round_trips_keeper_config(self, tmp_path):
        df = _make_draft_results()
        cfg = {
            "team_names": ["Alpha", "Beta"],
            "keepers": {"Alpha": [{"player_id": "b1", "cost": 5.0, "is_pitcher": False}]},
        }
        save_draft_results(2026, df, keeper_config=cfg, history_dir=str(tmp_path))
        loaded = load_keeper_config(2026, history_dir=str(tmp_path))
        assert loaded == cfg

    def test_returns_none_when_not_saved(self, tmp_path):
        df = _make_draft_results()
        save_draft_results(2026, df, history_dir=str(tmp_path))
        assert load_keeper_config(2026, history_dir=str(tmp_path)) is None

    def test_returns_none_for_missing_year(self, tmp_path):
        assert load_keeper_config(1999, history_dir=str(tmp_path)) is None


# ---------------------------------------------------------------------------
# list_available_years
# ---------------------------------------------------------------------------

class TestListAvailableYears:
    def test_returns_sorted_years(self, tmp_path):
        for year in (2024, 2022, 2026):
            save_draft_results(year, _make_draft_results(), history_dir=str(tmp_path))
        assert list_available_years(history_dir=str(tmp_path)) == [2022, 2024, 2026]

    def test_returns_empty_list_when_no_history(self, tmp_path):
        assert list_available_years(history_dir=str(tmp_path)) == []

    def test_returns_empty_list_when_dir_absent(self, tmp_path):
        missing = str(tmp_path / "no_history")
        assert list_available_years(history_dir=missing) == []

    def test_ignores_dirs_without_draft_results(self, tmp_path):
        # Create a year dir that has no draft_results.csv
        os.makedirs(tmp_path / "2023")
        save_draft_results(2025, _make_draft_results(), history_dir=str(tmp_path))
        assert list_available_years(history_dir=str(tmp_path)) == [2025]

    def test_ignores_non_integer_directory_names(self, tmp_path):
        os.makedirs(tmp_path / "profiles")
        save_draft_results(2026, _make_draft_results(), history_dir=str(tmp_path))
        assert list_available_years(history_dir=str(tmp_path)) == [2026]


# ---------------------------------------------------------------------------
# build_draft_results_from_engine
# ---------------------------------------------------------------------------

class TestBuildDraftResultsFromEngine:
    def _make_order_csv(self, picks):
        """picks: list of (team_name, pick_number)"""
        lines = ["player_name,pick_number"]
        for team, num in picks:
            lines.append(f"{team},{num}")
        return "\n".join(lines) + "\n"

    def test_drafted_players_included(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        engine.process_pick("b1", "Alpha", is_pitcher=False)
        engine.process_pick("p1", "Beta", is_pitcher=True)

        order_csv = self._make_order_csv([("Alpha", 1), ("Beta", 2)])
        result = build_draft_results_from_engine(engine, order_csv)

        assert len(result) == 2
        assert set(result["team_name"]) == {"Alpha", "Beta"}

    def test_keeper_players_included(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        engine.process_keeper("b2", "Alpha", cost=5.0, is_pitcher=False)
        engine.process_pick("p1", "Beta", is_pitcher=True)

        order_csv = self._make_order_csv([("Alpha", 1), ("Beta", 2)])
        result = build_draft_results_from_engine(engine, order_csv)

        assert len(result) == 2
        alpha_row = result[result["team_name"] == "Alpha"].iloc[0]
        assert alpha_row["player_id"] == "b2"

    def test_result_has_correct_columns(self):
        engine = _make_engine(team_names=["Alpha"])
        engine.process_pick("b1", "Alpha", is_pitcher=False)
        order_csv = self._make_order_csv([("Alpha", 1)])
        result = build_draft_results_from_engine(engine, order_csv)
        assert list(result.columns) == DRAFT_RESULTS_COLUMNS

    def test_is_pitcher_flag_correct(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        engine.process_pick("b1", "Alpha", is_pitcher=False)
        engine.process_pick("p1", "Beta", is_pitcher=True)

        order_csv = self._make_order_csv([("Alpha", 1), ("Beta", 2)])
        result = build_draft_results_from_engine(engine, order_csv)

        alpha_row = result[result["team_name"] == "Alpha"].iloc[0]
        beta_row = result[result["team_name"] == "Beta"].iloc[0]
        assert alpha_row["is_pitcher"] is False or alpha_row["is_pitcher"] == False
        assert beta_row["is_pitcher"] is True or beta_row["is_pitcher"] == True

    def test_pick_numbers_preserved(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        engine.process_pick("b1", "Alpha", is_pitcher=False)
        engine.process_pick("p1", "Beta", is_pitcher=True)

        order_csv = self._make_order_csv([("Alpha", 1), ("Beta", 2)])
        result = build_draft_results_from_engine(engine, order_csv)

        assert result.iloc[0]["pick_number"] == 1
        assert result.iloc[1]["pick_number"] == 2

    def test_empty_engine_returns_empty_dataframe(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        # No picks made
        order_csv = self._make_order_csv([("Alpha", 1), ("Beta", 2)])
        result = build_draft_results_from_engine(engine, order_csv)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == DRAFT_RESULTS_COLUMNS
        assert len(result) == 0

    def test_sorted_by_pick_number(self):
        engine = _make_engine(team_names=["Alpha", "Beta"])
        engine.process_pick("p1", "Beta", is_pitcher=True)
        engine.process_pick("b1", "Alpha", is_pitcher=False)

        # provide order with Beta picking first
        order_csv = self._make_order_csv([("Beta", 1), ("Alpha", 2)])
        result = build_draft_results_from_engine(engine, order_csv)

        assert list(result["pick_number"]) == [1, 2]
        assert result.iloc[0]["team_name"] == "Beta"


# ---------------------------------------------------------------------------
# collect_projection_files
# ---------------------------------------------------------------------------

class TestCollectProjectionFiles:
    def test_returns_empty_dict_for_missing_dir(self, tmp_path):
        result = collect_projection_files(data_dir=str(tmp_path / "nonexistent"))
        assert result == {}

    def test_returns_empty_dict_for_empty_dir(self, tmp_path):
        result = collect_projection_files(data_dir=str(tmp_path))
        assert result == {}

    def test_collects_csv_files(self, tmp_path):
        (tmp_path / "batters.csv").write_text("Name,HR\nPlayer,30\n")
        (tmp_path / "pitchers.csv").write_text("Name,ERA\nPitcher,3.50\n")
        result = collect_projection_files(data_dir=str(tmp_path))
        assert len(result) == 2
        assert "batters.csv" in result
        assert "pitchers.csv" in result
        assert "Player,30" in result["batters.csv"]

    def test_ignores_non_csv_files(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b\n1,2\n")
        (tmp_path / "readme.txt").write_text("not a csv")
        (tmp_path / "config.json").write_text("{}")
        result = collect_projection_files(data_dir=str(tmp_path))
        assert list(result.keys()) == ["data.csv"]

    def test_ignores_subdirectories(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b\n1,2\n")
        sub = tmp_path / "subdir.csv"
        sub.mkdir()
        result = collect_projection_files(data_dir=str(tmp_path))
        assert list(result.keys()) == ["data.csv"]

    def test_returns_sorted_filenames(self, tmp_path):
        (tmp_path / "z_file.csv").write_text("z\n")
        (tmp_path / "a_file.csv").write_text("a\n")
        (tmp_path / "m_file.csv").write_text("m\n")
        result = collect_projection_files(data_dir=str(tmp_path))
        assert list(result.keys()) == ["a_file.csv", "m_file.csv", "z_file.csv"]
