"""
Unit tests for src/tendency_evaluator.py
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from src.history_manager import DRAFT_RESULTS_COLUMNS, save_draft_results
from src.tendency_evaluator import (
    _compute_chaos_score,
    _compute_tendency_score,
    evaluate_all_teams,
    evaluate_team,
    load_profiles,
    save_profiles,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(picks):
    """Build a draft_results DataFrame from a compact list of pick dicts.

    Each dict must have at minimum ``team_name`` and ``is_pitcher``.
    Defaults are filled in for the remaining columns.
    """
    rows = []
    for i, pick in enumerate(picks):
        rows.append({
            "pick_number": pick.get("pick_number", i + 1),
            "round": pick.get("round", 1),
            "team_name": pick["team_name"],
            "player_name": pick.get("player_name", f"Player {i + 1}"),
            "player_id": pick.get("player_id", str(1000 + i)),
            "position": pick.get("position", "SP" if pick["is_pitcher"] else "OF"),
            "is_pitcher": pick["is_pitcher"],
            "dollars": pick.get("dollars", 10.0),
        })
    return pd.DataFrame(rows, columns=DRAFT_RESULTS_COLUMNS)


def _save_year(tmp_path, year, picks):
    """Save a synthetic draft to ``<tmp_path>/<year>/draft_results.csv``."""
    df = _make_results(picks)
    save_draft_results(year, df, history_dir=str(tmp_path))
    return df


# ---------------------------------------------------------------------------
# _compute_tendency_score
# ---------------------------------------------------------------------------

class TestComputeTendencyScore:
    def test_all_batters_returns_negative_one(self):
        df = _make_results([
            {"team_name": "A", "is_pitcher": False},
            {"team_name": "A", "is_pitcher": False},
            {"team_name": "A", "is_pitcher": False},
        ])
        assert _compute_tendency_score(df, "A") == -1.0

    def test_all_pitchers_returns_positive_one(self):
        df = _make_results([
            {"team_name": "A", "is_pitcher": True},
            {"team_name": "A", "is_pitcher": True},
        ])
        assert _compute_tendency_score(df, "A") == 1.0

    def test_balanced_returns_zero(self):
        df = _make_results([
            {"team_name": "A", "is_pitcher": False},
            {"team_name": "A", "is_pitcher": True},
        ])
        assert _compute_tendency_score(df, "A") == 0.0

    def test_no_picks_returns_zero(self):
        df = _make_results([
            {"team_name": "B", "is_pitcher": False},
        ])
        assert _compute_tendency_score(df, "A") == 0.0

    def test_hitting_leaning(self):
        # 7 batters, 3 pitchers → (3 - 7) / 10 = -0.4
        picks = (
            [{"team_name": "A", "is_pitcher": False}] * 7
            + [{"team_name": "A", "is_pitcher": True}] * 3
        )
        df = _make_results(picks)
        assert _compute_tendency_score(df, "A") == pytest.approx(-0.4)

    def test_only_considers_specified_team(self):
        df = _make_results([
            {"team_name": "A", "is_pitcher": True},
            {"team_name": "B", "is_pitcher": False},
            {"team_name": "B", "is_pitcher": False},
        ])
        assert _compute_tendency_score(df, "A") == 1.0
        assert _compute_tendency_score(df, "B") == -1.0


# ---------------------------------------------------------------------------
# _compute_chaos_score
# ---------------------------------------------------------------------------

class TestComputeChaosScore:
    def test_optimal_picks_returns_zero(self):
        """Team always picks the highest available dollar value → chaos ≈ 0."""
        df = _make_results([
            {"team_name": "A", "is_pitcher": False, "dollars": 30.0,
             "player_id": "p1", "pick_number": 1},
            {"team_name": "A", "is_pitcher": False, "dollars": 20.0,
             "player_id": "p2", "pick_number": 2},
            {"team_name": "A", "is_pitcher": True, "dollars": 10.0,
             "player_id": "p3", "pick_number": 3},
        ])
        assert _compute_chaos_score(df, "A") == pytest.approx(0.0)

    def test_suboptimal_picks_positive_chaos(self):
        """Team skips best-available value → chaos > 0."""
        # Available pool: p1($30), p2($20), p3($10)
        # Team A picks p3 first (worst), then p2, then p1
        df = _make_results([
            {"team_name": "A", "is_pitcher": False, "dollars": 10.0,
             "player_id": "p3", "pick_number": 1},
            {"team_name": "A", "is_pitcher": False, "dollars": 20.0,
             "player_id": "p2", "pick_number": 2},
            {"team_name": "A", "is_pitcher": True, "dollars": 30.0,
             "player_id": "p1", "pick_number": 3},
        ])
        score = _compute_chaos_score(df, "A")
        assert score > 0.0

    def test_no_picks_returns_zero(self):
        df = _make_results([
            {"team_name": "B", "is_pitcher": False, "dollars": 10.0,
             "player_id": "p1", "pick_number": 1},
        ])
        assert _compute_chaos_score(df, "A") == 0.0

    def test_chaos_increases_with_deviation(self):
        """Larger deviations from optimal produce higher chaos."""
        # Scenario A: slight miss (picks $25 when $30 available)
        df_low = _make_results([
            {"team_name": "A", "is_pitcher": False, "dollars": 25.0,
             "player_id": "p2", "pick_number": 1},
            {"team_name": "B", "is_pitcher": False, "dollars": 30.0,
             "player_id": "p1", "pick_number": 2},
        ])
        # Scenario B: big miss (picks $5 when $30 available)
        df_high = _make_results([
            {"team_name": "A", "is_pitcher": False, "dollars": 5.0,
             "player_id": "p3", "pick_number": 1},
            {"team_name": "B", "is_pitcher": False, "dollars": 30.0,
             "player_id": "p1", "pick_number": 2},
        ])
        assert _compute_chaos_score(df_high, "A") > _compute_chaos_score(df_low, "A")

    def test_uses_external_dollar_lookup(self):
        """When all_player_dollars is provided, it should be used."""
        df = _make_results([
            {"team_name": "A", "is_pitcher": False, "dollars": 0.0,
             "player_id": "p1", "pick_number": 1},
        ])
        lookup = pd.DataFrame({
            "player_id": ["p1", "p2"],
            "dollars": [50.0, 100.0],
        })
        # p1 is worth 50, but optimal was 100 → deviation = 50/100 = 0.5
        score = _compute_chaos_score(df, "A", all_player_dollars=lookup)
        assert score == pytest.approx(0.5)

    def test_multi_team_draft_tracks_availability(self):
        """Chaos score correctly tracks players drafted by other teams."""
        # p1($30) picked by B at #1, then A picks p2($20) at #2 → optimal for
        # A is $20 (p1 already gone) → deviation 0
        df = _make_results([
            {"team_name": "B", "is_pitcher": False, "dollars": 30.0,
             "player_id": "p1", "pick_number": 1},
            {"team_name": "A", "is_pitcher": False, "dollars": 20.0,
             "player_id": "p2", "pick_number": 2},
        ])
        assert _compute_chaos_score(df, "A") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# evaluate_team (multi-year)
# ---------------------------------------------------------------------------

class TestEvaluateTeam:
    def test_averages_across_years(self, tmp_path):
        # Year 1: all batters → tendency -1.0
        _save_year(tmp_path, 2024, [
            {"team_name": "A", "is_pitcher": False},
            {"team_name": "A", "is_pitcher": False},
        ])
        # Year 2: all pitchers → tendency +1.0
        _save_year(tmp_path, 2025, [
            {"team_name": "A", "is_pitcher": True},
            {"team_name": "A", "is_pitcher": True},
        ])

        result = evaluate_team("A", history_dir=str(tmp_path))
        assert result["tendency"] == pytest.approx(0.0)
        assert result["tendency_label"] == "balanced"
        assert len(result["yearly_details"]) == 2

    def test_single_year(self, tmp_path):
        _save_year(tmp_path, 2025, [
            {"team_name": "A", "is_pitcher": True},
            {"team_name": "A", "is_pitcher": True},
        ])
        result = evaluate_team("A", years=[2025], history_dir=str(tmp_path))
        assert result["tendency"] == pytest.approx(1.0)
        assert result["tendency_label"] == "pitching"

    def test_team_not_present_returns_zeros(self, tmp_path):
        _save_year(tmp_path, 2025, [
            {"team_name": "B", "is_pitcher": False},
        ])
        result = evaluate_team("Missing", history_dir=str(tmp_path))
        assert result["tendency"] == 0.0
        assert result["chaos_raw"] == 0.0
        assert result["chaos_score"] == 1

    def test_chaos_normalization_optimal(self, tmp_path):
        """Optimal drafter → chaos_raw ≈ 0 → chaos_score = 1."""
        _save_year(tmp_path, 2025, [
            {"team_name": "A", "is_pitcher": False, "dollars": 30.0,
             "player_id": "p1", "pick_number": 1},
            {"team_name": "A", "is_pitcher": False, "dollars": 20.0,
             "player_id": "p2", "pick_number": 2},
        ])
        result = evaluate_team("A", history_dir=str(tmp_path))
        assert result["chaos_score"] == 1

    def test_chaos_normalization_chaotic(self, tmp_path):
        """Highly suboptimal drafter → chaos_score > 1."""
        _save_year(tmp_path, 2025, [
            {"team_name": "A", "is_pitcher": False, "dollars": 1.0,
             "player_id": "p3", "pick_number": 1},
            {"team_name": "A", "is_pitcher": False, "dollars": 5.0,
             "player_id": "p2", "pick_number": 2},
            {"team_name": "A", "is_pitcher": True, "dollars": 50.0,
             "player_id": "p1", "pick_number": 3},
        ])
        result = evaluate_team("A", history_dir=str(tmp_path))
        assert result["chaos_score"] > 1

    def test_result_dict_structure(self, tmp_path):
        _save_year(tmp_path, 2025, [
            {"team_name": "A", "is_pitcher": False},
        ])
        result = evaluate_team("A", history_dir=str(tmp_path))
        assert "team_name" in result
        assert "tendency" in result
        assert "tendency_label" in result
        assert "chaos_score" in result
        assert "chaos_raw" in result
        assert "yearly_details" in result

    def test_tendency_label_hitting(self, tmp_path):
        # 8 batters, 2 pitchers → tendency -0.6 → "hitting"
        picks = (
            [{"team_name": "A", "is_pitcher": False}] * 8
            + [{"team_name": "A", "is_pitcher": True}] * 2
        )
        _save_year(tmp_path, 2025, picks)
        result = evaluate_team("A", history_dir=str(tmp_path))
        assert result["tendency_label"] == "hitting"

    def test_tendency_label_pitching(self, tmp_path):
        # 2 batters, 8 pitchers → tendency 0.6 → "pitching"
        picks = (
            [{"team_name": "A", "is_pitcher": False}] * 2
            + [{"team_name": "A", "is_pitcher": True}] * 8
        )
        _save_year(tmp_path, 2025, picks)
        result = evaluate_team("A", history_dir=str(tmp_path))
        assert result["tendency_label"] == "pitching"


# ---------------------------------------------------------------------------
# evaluate_all_teams
# ---------------------------------------------------------------------------

class TestEvaluateAllTeams:
    def test_discovers_all_teams(self, tmp_path):
        _save_year(tmp_path, 2025, [
            {"team_name": "Alpha", "is_pitcher": False},
            {"team_name": "Beta", "is_pitcher": True},
            {"team_name": "Gamma", "is_pitcher": False},
        ])
        profiles = evaluate_all_teams(history_dir=str(tmp_path))
        names = [p["team_name"] for p in profiles]
        assert names == ["Alpha", "Beta", "Gamma"]

    def test_sorted_by_team_name(self, tmp_path):
        _save_year(tmp_path, 2025, [
            {"team_name": "Zulu", "is_pitcher": False},
            {"team_name": "Alpha", "is_pitcher": True},
        ])
        profiles = evaluate_all_teams(history_dir=str(tmp_path))
        assert profiles[0]["team_name"] == "Alpha"
        assert profiles[1]["team_name"] == "Zulu"

    def test_empty_history(self, tmp_path):
        profiles = evaluate_all_teams(history_dir=str(tmp_path))
        assert profiles == []


# ---------------------------------------------------------------------------
# save_profiles / load_profiles
# ---------------------------------------------------------------------------

class TestPersistence:
    def _sample_profiles(self):
        return [
            {
                "team_name": "Alpha",
                "tendency": -0.3,
                "tendency_label": "hitting",
                "chaos_score": 3,
                "chaos_raw": 0.22,
                "yearly_details": [
                    {"year": 2024, "tendency": -0.3, "chaos_raw": 0.22, "picks": 10},
                ],
            },
        ]

    def test_save_creates_file(self, tmp_path):
        profiles_dir = str(tmp_path / "profiles")
        path = save_profiles(self._sample_profiles(), profiles_dir=profiles_dir)
        assert os.path.exists(path)
        assert path.endswith("tendencies.json")

    def test_save_file_structure(self, tmp_path):
        profiles_dir = str(tmp_path / "profiles")
        save_profiles(self._sample_profiles(), profiles_dir=profiles_dir)
        data = json.loads(open(os.path.join(profiles_dir, "tendencies.json")).read())
        assert "generated_at" in data
        assert "years_analyzed" in data
        assert "profiles" in data
        assert data["years_analyzed"] == [2024]

    def test_round_trip(self, tmp_path):
        profiles_dir = str(tmp_path / "profiles")
        original = self._sample_profiles()
        save_profiles(original, profiles_dir=profiles_dir)
        loaded = load_profiles(profiles_dir=profiles_dir)
        assert loaded is not None
        assert loaded["profiles"] == original

    def test_load_returns_none_when_missing(self, tmp_path):
        result = load_profiles(profiles_dir=str(tmp_path / "no_such_dir"))
        assert result is None
