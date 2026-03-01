"""
Unit tests for write-in player support.
"""
import pandas as pd
import pytest

from src.draft_engine import DraftEngine
from src.models import Player, Team


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(team_names=None):
    """Create a minimal DraftEngine with small DataFrames."""
    if team_names is None:
        team_names = ["Alpha", "Beta"]

    bat_df = pd.DataFrame({
        "PlayerId": ["b1", "b2"],
        "Name": ["Batter One", "Batter Two"],
        "POS": ["SS", "OF"],
        "Team": ["NYY", "LAD"],
        "AB": [500, 450],
        "R": [80, 70],
        "HR": [25, 20],
        "RBI": [75, 65],
        "SB": [10, 15],
        "OBP": [0.350, 0.340],
        "Dollars": [30.0, 20.0],
    })
    pitch_df = pd.DataFrame({
        "PlayerId": ["p1", "p2"],
        "Name": ["Pitcher One", "Pitcher Two"],
        "POS": ["SP", "RP"],
        "Team": ["BOS", "CHC"],
        "IP": [180, 70],
        "SO": [200, 80],
        "ERA": [3.20, 2.80],
        "WHIP": [1.10, 1.05],
        "SV": [0, 30],
        "QS": [20, 0],
        "Dollars": [25.0, 15.0],
    })
    return DraftEngine(bat_df, pitch_df, team_names=team_names)


# ---------------------------------------------------------------------------
# Player model
# ---------------------------------------------------------------------------

class TestPlayerWriteinFlag:
    def test_default_is_false(self):
        p = Player("id1", "Name", "SS", "NYY", 10.0, {}, False)
        assert p.is_writein is False

    def test_can_set_writein(self):
        p = Player("id1", "Name", "SS", "NYY", 10.0, {}, False, is_writein=True)
        assert p.is_writein is True


# ---------------------------------------------------------------------------
# DraftEngine.process_writein
# ---------------------------------------------------------------------------

class TestProcessWritein:
    def test_returns_writein_id(self):
        engine = _make_engine()
        pid = engine.process_writein("Minor Leaguer", "Alpha", is_pitcher=False, position="SS")
        assert pid.startswith("WRITEIN-")

    def test_player_added_to_roster(self):
        engine = _make_engine()
        engine.process_writein("Minor Leaguer", "Alpha", is_pitcher=False, position="SS")
        roster = engine.teams["Alpha"].roster
        assert len(roster) == 1
        assert roster[0].name == "Minor Leaguer"
        assert roster[0].is_writein is True
        assert roster[0].stats == {}

    def test_writein_keeper(self):
        engine = _make_engine()
        engine.process_writein("Keeper Kid", "Beta", is_pitcher=True, position="SP", cost=5.0, status="Keeper")
        roster = engine.teams["Beta"].roster
        assert len(roster) == 1
        assert roster[0].dollars == 5.0
        assert roster[0].is_pitcher is True

    def test_writein_default_position_batter(self):
        engine = _make_engine()
        engine.process_writein("No Pos Bat", "Alpha", is_pitcher=False)
        p = engine.teams["Alpha"].roster[0]
        # Batter with no position specified gets empty string; assigned to Util or BN
        assert p.position == ""

    def test_writein_default_position_pitcher(self):
        engine = _make_engine()
        engine.process_writein("No Pos Pitch", "Alpha", is_pitcher=True)
        p = engine.teams["Alpha"].roster[0]
        assert p.position == "P"


# ---------------------------------------------------------------------------
# Undo write-in
# ---------------------------------------------------------------------------

class TestUndoWritein:
    def test_undo_writein_pick(self):
        engine = _make_engine()
        pid = engine.process_writein("Write In Guy", "Alpha", is_pitcher=False, position="OF")
        assert len(engine.teams["Alpha"].roster) == 1
        result = engine.undo_pick(pid)
        assert result is True
        assert len(engine.teams["Alpha"].roster) == 0

    def test_undo_nonexistent_writein(self):
        engine = _make_engine()
        result = engine.undo_pick("WRITEIN-doesnotexist")
        assert result is False


# ---------------------------------------------------------------------------
# Remove keeper write-in
# ---------------------------------------------------------------------------

class TestRemoveKeeperWritein:
    def test_remove_writein_keeper(self):
        engine = _make_engine()
        pid = engine.process_writein("Keeper WI", "Beta", is_pitcher=True, position="SP", status="Keeper")
        assert len(engine.teams["Beta"].roster) == 1
        result = engine.remove_keeper(pid)
        assert result is True
        assert len(engine.teams["Beta"].roster) == 0

    def test_remove_nonexistent_writein_keeper(self):
        engine = _make_engine()
        result = engine.remove_keeper("WRITEIN-nope")
        assert result is False


# ---------------------------------------------------------------------------
# Roster display
# ---------------------------------------------------------------------------

class TestRosterDisplay:
    def test_writein_marked_in_roster_df(self):
        engine = _make_engine()
        engine.process_writein("Prospect X", "Alpha", is_pitcher=False, position="OF")
        df = engine.get_team_roster_df("Alpha")
        assert len(df) == 1
        assert "✏️" in df.iloc[0]["Name"]

    def test_writein_marked_in_slot_assignments(self):
        engine = _make_engine()
        engine.process_writein("Prospect X", "Alpha", is_pitcher=False, position="OF")
        assignments = engine.get_team_slot_assignments("Alpha")
        names = list(assignments.values())
        assert any("✏️" in n for n in names)


# ---------------------------------------------------------------------------
# Standings warning
# ---------------------------------------------------------------------------

class TestStandingsWarning:
    def test_team_with_writein_has_warning(self):
        engine = _make_engine()
        engine.process_writein("Write-in", "Alpha", is_pitcher=False)
        standings = engine.get_standings()
        alpha_row = standings[standings["Team"].str.contains("Alpha")]
        assert not alpha_row.empty
        assert "⚠️" in alpha_row.iloc[0]["Team"]

    def test_team_without_writein_no_warning(self):
        engine = _make_engine()
        engine.process_writein("Write-in", "Alpha", is_pitcher=False)
        standings = engine.get_standings()
        beta_row = standings[standings["Team"].str.contains("Beta")]
        assert not beta_row.empty
        assert "⚠️" not in beta_row.iloc[0]["Team"]


# ---------------------------------------------------------------------------
# Export / Import keeper config with write-ins
# ---------------------------------------------------------------------------

class TestExportImportWritein:
    def test_export_includes_writein(self):
        engine = _make_engine()
        engine.process_writein("WI Player", "Alpha", is_pitcher=False, position="3B", mlb_team="TEX", cost=2.0, status="Keeper")
        config = engine.export_keeper_config()
        keepers = config["keepers"]["Alpha"]
        assert len(keepers) == 1
        k = keepers[0]
        assert k["is_writein"] is True
        assert k["name"] == "WI Player"
        assert k["position"] == "3B"
        assert k["cost"] == 2.0

    def test_import_restores_writein(self):
        engine = _make_engine()
        engine.process_writein("WI Player", "Alpha", is_pitcher=False, position="3B", mlb_team="TEX", cost=2.0, status="Keeper")
        config = engine.export_keeper_config()

        engine2 = _make_engine()
        result = engine2.import_keeper_config(config)
        assert result is True
        roster = engine2.teams["Alpha"].roster
        assert len(roster) == 1
        assert roster[0].name == "WI Player"
        assert roster[0].is_writein is True
        assert roster[0].position == "3B"


# ---------------------------------------------------------------------------
# set_team_names with write-ins
# ---------------------------------------------------------------------------

class TestSetTeamNamesWritein:
    def test_removing_team_with_writein_does_not_crash(self):
        engine = _make_engine(team_names=["A", "B"])
        engine.process_writein("WI", "A", is_pitcher=False)
        # Removing team A should not crash when write-in player is not in DFs
        engine.set_team_names(["B", "C"])
        assert "A" not in engine.teams
        assert "C" in engine.teams
