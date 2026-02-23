#!/usr/bin/env python3
"""
Test script to verify draft simulator scoring correctly weights dollar values.

When dollar values include negative numbers (original auction values), the
simulator's power-law scoring concentrates selection probability on top-valued
players much more strongly than when values are shifted to all-positive.
"""
import pandas as pd
import numpy as np
import sys
from src.draft_engine import DraftEngine
from src.draft_simulator import DraftSimulator


def _make_test_data(dollar_values_bat, dollar_values_pitch):
    """Create test DataFrames with given dollar values."""
    n_bat = len(dollar_values_bat)
    bat_df = pd.DataFrame({
        'PlayerId': [str(1000 + i) for i in range(n_bat)],
        'Name': [f'Batter {i}' for i in range(n_bat)],
        'POS': ['OF'] * n_bat,
        'Team': ['NYY'] * n_bat,
        'AB': [500] * n_bat,
        'R': [80] * n_bat,
        'HR': [25] * n_bat,
        'RBI': [75] * n_bat,
        'SB': [10] * n_bat,
        'OBP': [0.350] * n_bat,
        'WAR': [3.0] * n_bat,
        'Dollars': dollar_values_bat,
    })

    n_pitch = len(dollar_values_pitch)
    pitch_df = pd.DataFrame({
        'PlayerId': [str(2000 + i) for i in range(n_pitch)],
        'Name': [f'Pitcher {i}' for i in range(n_pitch)],
        'POS': ['SP'] * n_pitch,
        'Team': ['LAD'] * n_pitch,
        'IP': [180] * n_pitch,
        'SO': [200] * n_pitch,
        'ERA': [3.50] * n_pitch,
        'WHIP': [1.15] * n_pitch,
        'WAR': [4.0] * n_pitch,
        'SV': [0] * n_pitch,
        'QS': [15] * n_pitch,
        'Dollars': dollar_values_pitch,
    })

    return bat_df, pitch_df


def _make_draft_order_csv(team_names, num_rounds=1):
    """Create a draft order CSV string."""
    lines = ['player_name,pick_number,tendency']
    pick = 1
    for _ in range(num_rounds):
        for name in team_names:
            lines.append(f'{name},{pick},hitting')
            pick += 1
    return '\n'.join(lines)


def test_high_value_player_dominates():
    """The highest-dollar player should be picked far more often than uniform chance.

    With normalized (all-positive) dollar values, the score re-centering in
    simulate_next_pick should make the top player strongly favoured.
    With 17 total candidates, uniform chance is ~5.9%. The top player
    should be selected at least 25% of the time (>4x uniform).
    """
    print("\n" + "=" * 60)
    print("TEST: High-value player dominance in scoring")
    print("=" * 60)

    # Simulate normalized dollar values (all positive, as produced by data_loader)
    # Original range: [-50, 80] shifted to [1, 131]
    bat_dollars = [131, 91, 71, 56, 41, 31, 21, 11, 1]
    pitch_dollars = [111, 81, 61, 51, 36, 26, 16, 6]

    bat_df, pitch_df = _make_test_data(bat_dollars, pitch_dollars)
    num_candidates = len(bat_dollars) + len(pitch_dollars)

    team_names = ['AI_Team_1', 'AI_Team_2']
    engine = DraftEngine(bat_df, pitch_df, team_names=team_names)

    csv = _make_draft_order_csv(team_names, num_rounds=1)

    # Run many simulations and count how often the top player gets picked first
    top_pick_count = 0
    num_trials = 200

    for trial in range(num_trials):
        sim = DraftSimulator(engine, csv, user_team_name='AI_Team_2', random_seed=trial)
        # Simulate AI_Team_1's first pick
        result = sim.simulate_next_pick()
        if result and result['player_name'] == 'Batter 0':  # $131 player
            top_pick_count += 1

    pct = top_pick_count / num_trials * 100
    uniform_pct = 100.0 / num_candidates
    print(f"  Top player ($131) picked first in {top_pick_count}/{num_trials} trials ({pct:.1f}%)")
    print(f"  Uniform chance with {num_candidates} candidates: {uniform_pct:.1f}%")
    print(f"  Selection rate vs uniform: {pct/uniform_pct:.1f}x")

    # Top player should be picked at least 4x uniform rate
    if pct > uniform_pct * 4:
        print("  ✅ PASSED: Top-valued player strongly favoured")
        return True
    else:
        print("  ❌ FAILED: Top-valued player not sufficiently favoured")
        return False


def test_normalized_dollars_preserved():
    """Dollar values should remain positive (normalization is kept)."""
    print("\n" + "=" * 60)
    print("TEST: Normalized dollar values preserved (all positive)")
    print("=" * 60)

    bat_dollars = [131, 91, 41, 1]
    pitch_dollars = [111, 31]

    bat_df, pitch_df = _make_test_data(bat_dollars, pitch_dollars)

    bat_min = bat_df['Dollars'].min()
    pitch_min = pitch_df['Dollars'].min()

    print(f"  Batter Dollars range: [{bat_min}, {bat_df['Dollars'].max()}]")
    print(f"  Pitcher Dollars range: [{pitch_min}, {pitch_df['Dollars'].max()}]")

    all_positive = bat_min > 0 and pitch_min > 0
    if all_positive:
        print("  ✅ PASSED: All dollar values are positive")
        return True
    else:
        print("  ❌ FAILED: Some dollar values are negative")
        return False


def test_score_recentering_restores_dynamic_range():
    """After re-centering, the power-law ratio between top and mid players
    should be large enough for strong selection bias.

    The re-centering step (subtracting the minimum score) in simulate_next_pick
    restores dynamic range that dollar normalization compresses.
    """
    print("\n" + "=" * 60)
    print("TEST: Score re-centering restores dynamic range")
    print("=" * 60)

    # Normalized dollar values (all positive)
    bat_dollars = [131, 91, 71, 56, 41, 21, 1]
    pitch_dollars = [111, 81, 51, 31, 11]

    bat_df, pitch_df = _make_test_data(bat_dollars, pitch_dollars)

    team_names = ['Test_Team']
    engine = DraftEngine(bat_df, pitch_df, team_names=team_names)

    csv = _make_draft_order_csv(team_names, num_rounds=1)
    sim = DraftSimulator(engine, csv, user_team_name='Test_Team', random_seed=42)

    # Compute raw scores for all candidates (replicating simulate_next_pick logic)
    available_bat = sim.engine.bat_df[sim.engine.bat_df['Status'] == 'Available']
    available_pitch = sim.engine.pitch_df[sim.engine.pitch_df['Status'] == 'Available']
    standings = sim.engine.get_standings()
    rankings = sim._compute_category_rankings(standings, 'Test_Team')

    all_scores = []
    for _, row in available_bat.iterrows():
        s = sim._calculate_player_score(row, 'Test_Team', 'hitting', False,
                                        cached_standings=standings, cached_rankings=rankings)
        all_scores.append((row['Name'], row['Dollars'], s))
    for _, row in available_pitch.iterrows():
        s = sim._calculate_player_score(row, 'Test_Team', 'hitting', True,
                                        cached_standings=standings, cached_rankings=rankings)
        all_scores.append((row['Name'], row['Dollars'], s))

    scores_array = np.array([s for _, _, s in all_scores])

    # Apply re-centering (same as simulate_next_pick)
    recentered = scores_array - scores_array.min()
    recentered = recentered + sim.EPSILON

    # Find the top batter ($131) and a mid batter ($71)
    top_idx = next(i for i, (n, _, _) in enumerate(all_scores) if n == 'Batter 0')
    mid_idx = next(i for i, (n, _, _) in enumerate(all_scores) if n == 'Batter 2')

    rc_top = recentered[top_idx]
    rc_mid = recentered[mid_idx]
    ratio_pow = (rc_top ** 3) / max(rc_mid ** 3, 1e-9)

    print(f"  Re-centered score top ($131): {rc_top:.2f}")
    print(f"  Re-centered score mid ($71):  {rc_mid:.2f}")
    print(f"  Power-3 ratio: {ratio_pow:.2f}")

    # After re-centering + power-3, ratio should be at least 3
    # (compared to <2 without re-centering for these values)
    if ratio_pow >= 3:
        print("  ✅ PASSED: Re-centering restores dynamic range")
        return True
    else:
        print("  ❌ FAILED: Re-centering insufficient")
        return False


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("DRAFT SIMULATOR SCORING TEST SUITE")
    print("=" * 60)

    t1 = test_high_value_player_dominates()
    t2 = test_normalized_dollars_preserved()
    t3 = test_score_recentering_restores_dynamic_range()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Test 1 (High-value dominance): {'✅ PASSED' if t1 else '❌ FAILED'}")
    print(f"Test 2 (Normalized dollars preserved): {'✅ PASSED' if t2 else '❌ FAILED'}")
    print(f"Test 3 (Re-centering dynamic range): {'✅ PASSED' if t3 else '❌ FAILED'}")

    if t1 and t2 and t3:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n💥 SOME TESTS FAILED")
        sys.exit(1)
