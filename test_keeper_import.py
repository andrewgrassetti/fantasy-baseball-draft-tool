#!/usr/bin/env python3
"""
Test script to verify keeper import/export functionality works correctly
with different PlayerId types (string vs int).
"""
import pandas as pd
import json
import os
import sys
from src.draft_engine import DraftEngine
from src.persistence import save_keeper_config, load_keeper_config, list_saved_configs

def test_keeper_with_string_playerid():
    """Test keeper functionality when DataFrame has string PlayerId."""
    print("\n" + "="*60)
    print("TEST 1: Keeper Import/Export with STRING PlayerId")
    print("="*60)
    
    # Create test DataFrames with STRING PlayerId
    bat_df = pd.DataFrame({
        'PlayerId': ['1001', '1002', '1003'],
        'Name': ['Player A', 'Player B', 'Player C'],
        'POS': ['SS', '1B', 'OF'],
        'Team': ['NYY', 'LAD', 'BOS'],
        'AB': [500, 450, 520],
        'R': [80, 70, 85],
        'HR': [25, 30, 20],
        'RBI': [75, 80, 70],
        'SB': [15, 5, 25],
        'OBP': [0.350, 0.360, 0.340],
        'WAR': [4.5, 5.0, 4.0],
        'Dollars': [30, 35, 28]
    })
    
    pitch_df = pd.DataFrame({
        'PlayerId': ['2001', '2002', '2003'],
        'Name': ['Pitcher X', 'Pitcher Y', 'Pitcher Z'],
        'POS': ['SP', 'RP', 'SP'],
        'Team': ['NYY', 'LAD', 'BOS'],
        'IP': [180, 65, 170],
        'SO': [200, 80, 190],
        'ERA': [3.50, 2.80, 3.75],
        'WHIP': [1.15, 1.05, 1.20],
        'WAR': [4.0, 2.5, 3.8],
        'SV': [0, 35, 0],
        'Dollars': [25, 20, 22]
    })
    
    print(f"Created DataFrames with PlayerId type: {bat_df['PlayerId'].dtype}")
    
    # Create engine
    engine = DraftEngine(bat_df, pitch_df, team_names=['Team1', 'Team2', 'Team3'])
    
    # Process some keepers - using STRING player_id
    print("\nAdding keepers...")
    success1 = engine.process_keeper('1001', 'Team1', cost=15.0, is_pitcher=False)
    success2 = engine.process_keeper('2001', 'Team1', cost=10.0, is_pitcher=True)
    success3 = engine.process_keeper('1002', 'Team2', cost=20.0, is_pitcher=False)
    
    print(f"  Keeper 1 (string '1001'): {'SUCCESS' if success1 else 'FAILED'}")
    print(f"  Keeper 2 (string '2001'): {'SUCCESS' if success2 else 'FAILED'}")
    print(f"  Keeper 3 (string '1002'): {'SUCCESS' if success3 else 'FAILED'}")
    
    # Export configuration
    print("\nExporting keeper configuration...")
    config_data = engine.export_keeper_config()
    print(f"  Exported {sum(len(keepers) for keepers in config_data['keepers'].values())} keepers")
    
    # Save to file
    os.makedirs('saves', exist_ok=True)
    filepath = save_keeper_config("Test Config Strings", 
                                 config_data['team_names'], 
                                 config_data['keepers'])
    print(f"  Saved to: {filepath}")
    
    # Load configuration
    print("\nLoading keeper configuration...")
    loaded_config = load_keeper_config(filepath)
    print(f"  Loaded config name: {loaded_config['name']}")
    print(f"  Number of teams with keepers: {len(loaded_config['keepers'])}")
    
    # Create new engine and import
    print("\nImporting into new engine...")
    engine2 = DraftEngine(bat_df, pitch_df, team_names=['Team1', 'Team2', 'Team3'])
    import_success = engine2.import_keeper_config(loaded_config)
    print(f"  Import result: {'SUCCESS' if import_success else 'FAILED'}")
    
    # Verify keepers were imported
    print("\nVerifying imported keepers...")
    team1_roster = engine2.get_team_roster_df('Team1')
    team2_roster = engine2.get_team_roster_df('Team2')
    print(f"  Team1 roster size: {len(team1_roster)} (expected 2)")
    print(f"  Team2 roster size: {len(team2_roster)} (expected 1)")
    
    if len(team1_roster) == 2 and len(team2_roster) == 1:
        print("\n✅ TEST 1 PASSED: All keepers imported correctly with STRING PlayerId")
        return True
    else:
        print("\n❌ TEST 1 FAILED: Not all keepers were imported")
        return False


def test_keeper_with_int_playerid():
    """Test keeper functionality when DataFrame has integer PlayerId."""
    print("\n" + "="*60)
    print("TEST 2: Keeper Import/Export with INTEGER PlayerId")
    print("="*60)
    
    # Create test DataFrames with INTEGER PlayerId
    bat_df = pd.DataFrame({
        'PlayerId': [1001, 1002, 1003],
        'Name': ['Player A', 'Player B', 'Player C'],
        'POS': ['SS', '1B', 'OF'],
        'Team': ['NYY', 'LAD', 'BOS'],
        'AB': [500, 450, 520],
        'R': [80, 70, 85],
        'HR': [25, 30, 20],
        'RBI': [75, 80, 70],
        'SB': [15, 5, 25],
        'OBP': [0.350, 0.360, 0.340],
        'WAR': [4.5, 5.0, 4.0],
        'Dollars': [30, 35, 28]
    })
    
    pitch_df = pd.DataFrame({
        'PlayerId': [2001, 2002, 2003],
        'Name': ['Pitcher X', 'Pitcher Y', 'Pitcher Z'],
        'POS': ['SP', 'RP', 'SP'],
        'Team': ['NYY', 'LAD', 'BOS'],
        'IP': [180, 65, 170],
        'SO': [200, 80, 190],
        'ERA': [3.50, 2.80, 3.75],
        'WHIP': [1.15, 1.05, 1.20],
        'WAR': [4.0, 2.5, 3.8],
        'SV': [0, 35, 0],
        'Dollars': [25, 20, 22]
    })
    
    print(f"Created DataFrames with PlayerId type: {bat_df['PlayerId'].dtype}")
    
    # Create engine
    engine = DraftEngine(bat_df, pitch_df, team_names=['Team1', 'Team2', 'Team3'])
    
    # Process some keepers - using STRING player_id (as they would come from JSON)
    print("\nAdding keepers (passing as strings to simulate JSON load)...")
    success1 = engine.process_keeper('1001', 'Team1', cost=15.0, is_pitcher=False)
    success2 = engine.process_keeper('2001', 'Team1', cost=10.0, is_pitcher=True)
    success3 = engine.process_keeper('1002', 'Team2', cost=20.0, is_pitcher=False)
    
    print(f"  Keeper 1 (string '1001' -> int): {'SUCCESS' if success1 else 'FAILED'}")
    print(f"  Keeper 2 (string '2001' -> int): {'SUCCESS' if success2 else 'FAILED'}")
    print(f"  Keeper 3 (string '1002' -> int): {'SUCCESS' if success3 else 'FAILED'}")
    
    # Export configuration
    print("\nExporting keeper configuration...")
    config_data = engine.export_keeper_config()
    print(f"  Exported {sum(len(keepers) for keepers in config_data['keepers'].values())} keepers")
    
    # Save to file
    os.makedirs('saves', exist_ok=True)
    filepath = save_keeper_config("Test Config Integers", 
                                 config_data['team_names'], 
                                 config_data['keepers'])
    print(f"  Saved to: {filepath}")
    
    # Load configuration
    print("\nLoading keeper configuration...")
    loaded_config = load_keeper_config(filepath)
    print(f"  Loaded config name: {loaded_config['name']}")
    
    # Create new engine and import
    print("\nImporting into new engine...")
    engine2 = DraftEngine(bat_df, pitch_df, team_names=['Team1', 'Team2', 'Team3'])
    import_success = engine2.import_keeper_config(loaded_config)
    print(f"  Import result: {'SUCCESS' if import_success else 'FAILED'}")
    
    # Verify keepers were imported
    print("\nVerifying imported keepers...")
    team1_roster = engine2.get_team_roster_df('Team1')
    team2_roster = engine2.get_team_roster_df('Team2')
    print(f"  Team1 roster size: {len(team1_roster)} (expected 2)")
    print(f"  Team2 roster size: {len(team2_roster)} (expected 1)")
    
    if len(team1_roster) == 2 and len(team2_roster) == 1:
        print("\n✅ TEST 2 PASSED: All keepers imported correctly with INTEGER PlayerId")
        return True
    else:
        print("\n❌ TEST 2 FAILED: Not all keepers were imported")
        return False


def test_dropdown_display():
    """Test that saved configs include filename in metadata."""
    print("\n" + "="*60)
    print("TEST 3: Dropdown Display Shows Filename")
    print("="*60)
    
    # List saved configurations
    configs = list_saved_configs()
    print(f"\nFound {len(configs)} saved configurations")
    
    if len(configs) == 0:
        print("⚠️  No saved configurations to test")
        return True
    
    all_have_filename = True
    for cfg in configs:
        has_filename = 'filename' in cfg and cfg['filename']
        print(f"  - {cfg.get('name', 'Unknown')}")
        print(f"    Filename: {cfg.get('filename', 'MISSING')}")
        print(f"    Has filename: {'✓' if has_filename else '✗'}")
        if not has_filename:
            all_have_filename = False
    
    if all_have_filename:
        print("\n✅ TEST 3 PASSED: All configs have filename metadata")
        return True
    else:
        print("\n❌ TEST 3 FAILED: Some configs missing filename")
        return False


if __name__ == '__main__':
    print("\n" + "="*60)
    print("KEEPER IMPORT/EXPORT TEST SUITE")
    print("="*60)
    
    test1_pass = test_keeper_with_string_playerid()
    test2_pass = test_keeper_with_int_playerid()
    test3_pass = test_dropdown_display()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Test 1 (String PlayerId): {'✅ PASSED' if test1_pass else '❌ FAILED'}")
    print(f"Test 2 (Integer PlayerId): {'✅ PASSED' if test2_pass else '❌ FAILED'}")
    print(f"Test 3 (Dropdown Filename): {'✅ PASSED' if test3_pass else '❌ FAILED'}")
    
    if test1_pass and test2_pass and test3_pass:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n💥 SOME TESTS FAILED")
        sys.exit(1)
