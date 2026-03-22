"""Tests for custom columns persistence and data-transformation logic."""
import json
import os

import pandas as pd
import pytest

from src.persistence import (
    save_custom_columns_config,
    load_custom_columns_config,
    list_custom_columns_configs,
    delete_custom_columns_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_bat_df():
    return pd.DataFrame(
        {
            "PlayerId": ["101", "102", "103"],
            "Name": ["Alice", "Bob", "Charlie"],
            "POS": ["SS", "1B", "OF"],
            "Team": ["NYY", "LAD", "BOS"],
            "Dollars": [30, 25, 20],
            "Status": ["Available", "Available", "Drafted"],
        }
    )


def _sample_pitch_df():
    return pd.DataFrame(
        {
            "PlayerId": ["201", "202"],
            "Name": ["Ace", "Reliever"],
            "POS": ["SP", "RP"],
            "Team": ["NYY", "LAD"],
            "Dollars": [28, 15],
            "Status": ["Available", "Available"],
        }
    )


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------

class TestSaveCustomColumnsConfig:
    def test_creates_file(self, tmp_path):
        fp = save_custom_columns_config(
            name="Test",
            hitter_columns=["Tier"],
            pitcher_columns=[],
            hitter_values={"101": {"Tier": "A"}},
            pitcher_values={},
            saves_dir=str(tmp_path),
        )
        assert os.path.exists(fp)

    def test_round_trips_columns_and_values(self, tmp_path):
        hc = ["Tier", "Notes"]
        pc = ["Stuff"]
        hv = {"101": {"Tier": "A", "Notes": "keeper target"}}
        pv = {"201": {"Stuff": "elite"}}

        fp = save_custom_columns_config(
            "Round Trip", hc, pc, hv, pv, saves_dir=str(tmp_path)
        )
        loaded = load_custom_columns_config(fp)

        assert loaded["hitter_columns"] == hc
        assert loaded["pitcher_columns"] == pc
        assert loaded["hitter_values"] == hv
        assert loaded["pitcher_values"] == pv

    def test_overwrite_same_name(self, tmp_path):
        save_custom_columns_config(
            "Dup", ["A"], [], {}, {}, saves_dir=str(tmp_path)
        )
        fp2 = save_custom_columns_config(
            "Dup", ["B"], [], {}, {}, saves_dir=str(tmp_path)
        )
        loaded = load_custom_columns_config(fp2)
        assert loaded["hitter_columns"] == ["B"]


class TestListCustomColumnsConfigs:
    def test_empty_dir(self, tmp_path):
        assert list_custom_columns_configs(str(tmp_path)) == []

    def test_nonexistent_dir(self, tmp_path):
        assert list_custom_columns_configs(str(tmp_path / "nope")) == []

    def test_lists_saved_configs(self, tmp_path):
        save_custom_columns_config("A", [], [], {}, {}, saves_dir=str(tmp_path))
        save_custom_columns_config("B", [], [], {}, {}, saves_dir=str(tmp_path))
        configs = list_custom_columns_configs(str(tmp_path))
        assert len(configs) == 2
        names = {c["name"] for c in configs}
        assert names == {"A", "B"}

    def test_skips_invalid_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        save_custom_columns_config("Good", [], [], {}, {}, saves_dir=str(tmp_path))
        configs = list_custom_columns_configs(str(tmp_path))
        assert len(configs) == 1
        assert configs[0]["name"] == "Good"


class TestDeleteCustomColumnsConfig:
    def test_deletes_existing(self, tmp_path):
        fp = save_custom_columns_config("X", [], [], {}, {}, saves_dir=str(tmp_path))
        assert delete_custom_columns_config(fp) is True
        assert not os.path.exists(fp)

    def test_returns_false_for_missing(self, tmp_path):
        assert delete_custom_columns_config(str(tmp_path / "nope.json")) is False


# ---------------------------------------------------------------------------
# Column-name validation helpers  (mirrors UI logic)
# ---------------------------------------------------------------------------

def _validate_new_column(name: str, existing: list) -> str | None:
    """Return an error message, or None if valid."""
    stripped = name.strip()
    if not stripped:
        return "Column name cannot be empty."
    if stripped in existing:
        return f"Column '{stripped}' already exists."
    return None


class TestColumnNameValidation:
    def test_reject_empty(self):
        assert _validate_new_column("", []) is not None

    def test_reject_whitespace_only(self):
        assert _validate_new_column("   ", []) is not None

    def test_reject_duplicate(self):
        assert _validate_new_column("Tier", ["Tier", "Notes"]) is not None

    def test_accept_valid(self):
        assert _validate_new_column("Tier", []) is None

    def test_same_name_different_tables(self):
        # Hitters and pitchers may independently have the same column name
        assert _validate_new_column("Tier", []) is None  # hitter first
        assert _validate_new_column("Tier", []) is None  # pitcher second (own list)


# ---------------------------------------------------------------------------
# Player-name validation
# ---------------------------------------------------------------------------

def _validate_player_name(name: str, player_df: pd.DataFrame) -> str | None:
    """Return an error message, or None if valid."""
    matches = player_df[player_df['Name'].str.lower() == name.strip().lower()]
    if matches.empty:
        return f"Player '{name}' not found."
    return None


class TestPlayerNameValidation:
    def test_valid_hitter(self):
        assert _validate_player_name("Alice", _sample_bat_df()) is None

    def test_case_insensitive(self):
        assert _validate_player_name("alice", _sample_bat_df()) is None

    def test_invalid_hitter(self):
        assert _validate_player_name("Nobody", _sample_bat_df()) is not None

    def test_valid_pitcher(self):
        assert _validate_player_name("Ace", _sample_pitch_df()) is None

    def test_invalid_pitcher(self):
        assert _validate_player_name("Nobody", _sample_pitch_df()) is not None


# ---------------------------------------------------------------------------
# Rendering: custom columns appear with blanks by default
# ---------------------------------------------------------------------------

def _apply_custom_columns(df, custom_columns, custom_values):
    """Apply custom columns to a copy of *df* and return it."""
    df = df.copy()
    for col_name in custom_columns:
        df[col_name] = df['PlayerId'].apply(
            lambda pid, cn=col_name: custom_values.get(str(pid), {}).get(cn, '')
        )
    return df


class TestApplyCustomColumns:
    def test_blank_defaults(self):
        df = _apply_custom_columns(_sample_bat_df(), ["Tier"], {})
        assert "Tier" in df.columns
        assert (df["Tier"] == "").all()

    def test_assigned_value_appears(self):
        vals = {"101": {"Tier": "A"}}
        df = _apply_custom_columns(_sample_bat_df(), ["Tier"], vals)
        row = df[df["PlayerId"] == "101"].iloc[0]
        assert row["Tier"] == "A"

    def test_unassigned_stays_blank(self):
        vals = {"101": {"Tier": "A"}}
        df = _apply_custom_columns(_sample_bat_df(), ["Tier"], vals)
        row = df[df["PlayerId"] == "102"].iloc[0]
        assert row["Tier"] == ""

    def test_multiple_columns(self):
        vals = {"101": {"Tier": "A", "Notes": "keeper"}}
        df = _apply_custom_columns(_sample_bat_df(), ["Tier", "Notes"], vals)
        assert df.loc[df["PlayerId"] == "101", "Tier"].iloc[0] == "A"
        assert df.loc[df["PlayerId"] == "101", "Notes"].iloc[0] == "keeper"
        # Other players blank
        assert df.loc[df["PlayerId"] == "102", "Tier"].iloc[0] == ""
        assert df.loc[df["PlayerId"] == "102", "Notes"].iloc[0] == ""

    def test_hitter_pitcher_independence(self):
        bat = _apply_custom_columns(_sample_bat_df(), ["Tier"], {"101": {"Tier": "A"}})
        pit = _apply_custom_columns(_sample_pitch_df(), ["Stuff"], {"201": {"Stuff": "elite"}})
        # Hitter DF has Tier but not Stuff
        assert "Tier" in bat.columns
        assert "Stuff" not in bat.columns
        # Pitcher DF has Stuff but not Tier
        assert "Stuff" in pit.columns
        assert "Tier" not in pit.columns
