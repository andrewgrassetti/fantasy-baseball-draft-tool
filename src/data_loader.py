import pandas as pd
import os

def load_and_merge_data(data_dir="data"):
    """
    Loads projection CSVs AND Auction Value CSVs, safely merging metadata.
    """
    
    # --- FILE CONFIGURATION ---
    batting_files = [
        "2025_batx_bat.csv", "2025_steamer_bat.csv", 
        "2025_zips_bat.csv", "2025_oopsy_bat.csv"
    ]
    pitching_files = [
        "2025_batx_pitch.csv", "2025_steamer_pitch.csv", 
        "2025_zips_pitch.csv", "2025_oopsy_pitch.csv"
    ]
    
    auction_bat_file = "2025_batx_auction_bat.csv"
    auction_pitch_file = "2025_oopsy_auction_pitch.csv"

    # --- ROBUST COLUMN DEFINITIONS ---
    # We list possible names for key columns to handle capitalization differences
    # format: 'TargetName': ['PossibleName1', 'PossibleName2']
    
    # 1. Batting Projections (Numeric stats only)
    bat_stat_cols = ['AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'ADP']
    
    # 2. Pitching Projections (Numeric stats only)
    pitch_stat_cols = ['IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS', 'ADP']

    # --- HELPER: SAFE LOAD ---
    def load_group(filenames, required_stats):
        dfs = []
        for f in filenames:
            path = os.path.join(data_dir, f)
            if os.path.exists(path):
                # Load carefully
                try:
                    df = pd.read_csv(path, encoding='utf-8-sig') # Handle special chars
                except UnicodeDecodeError:
                    df = pd.read_csv(path, encoding='latin-1')

                # Rename columns to standard names if needed (e.g. "Pos" -> "POS")
                df.rename(columns={'Pos': 'POS', 'Position': 'POS', 'playerid': 'PlayerId'}, inplace=True)

                # Filter for PlayerId + Stats that exist in this file
                cols_to_grab = ['PlayerId'] + [c for c in required_stats if c in df.columns]
                
                # Also try to grab metadata if it exists (Name, Team)
                for meta in ['Name', 'Team', 'POS']:
                    if meta in df.columns:
                        cols_to_grab.append(meta)

                dfs.append(df[cols_to_grab])
        
        if not dfs:
            return pd.DataFrame()
        return pd.concat(dfs, ignore_index=True)

    # --- PROCESS BATTERS ---
    raw_bat = load_group(batting_files, bat_stat_cols)
    if raw_bat.empty:
        raise FileNotFoundError("No batting projection files found!")

    # 1. Average the numeric stats
    bat_final = raw_bat.groupby('PlayerId').mean(numeric_only=True).reset_index()
    
    # 2. Extract Metadata (Name, Team) from projections if available
    # We drop 'POS' from here because it might be missing
    meta_cols = [c for c in ['PlayerId', 'Name', 'Team'] if c in raw_bat.columns]
    bat_meta = raw_bat[meta_cols].drop_duplicates('PlayerId')
    bat_final = pd.merge(bat_final, bat_meta, on='PlayerId', how='left')

    # 3. Load Auction File (CRITICAL: Get POS from here if needed)
    auc_bat_path = os.path.join(data_dir, auction_bat_file)
    if os.path.exists(auc_bat_path):
        auc_df = pd.read_csv(auc_bat_path)
        auc_df.rename(columns={'Pos': 'POS', 'Position': 'POS'}, inplace=True)
        
        # We need PlayerId, Dollars, and POS (if we don't have it yet)
        auc_cols = ['PlayerId', 'Dollars']
        if 'POS' in auc_df.columns:
            auc_cols.append('POS')
        
        auc_subset = auc_df[auc_cols]
        bat_final = pd.merge(bat_final, auc_subset, on='PlayerId', how='left')
        
        # Fill missing Dollars with 0
        bat_final['Dollars'] = bat_final['Dollars'].fillna(0)
    else:
        bat_final['Dollars'] = 0

    # 4. Fallback for missing POS (Default to 'Unknown' so app doesn't crash)
    if 'POS' not in bat_final.columns:
        bat_final['POS'] = 'Unknown'
    else:
        # If POS came from both files, pandas creates POS_x and POS_y. Coalesce them.
        if 'POS_x' in bat_final.columns and 'POS_y' in bat_final.columns:
            bat_final['POS'] = bat_final['POS_y'].combine_first(bat_final['POS_x'])
            bat_final.drop(columns=['POS_x', 'POS_y'], inplace=True)

    bat_final['Type'] = 'Batter'

    # --- PROCESS PITCHERS ---
    raw_pitch = load_group(pitching_files, pitch_stat_cols)
    if raw_pitch.empty:
        raise FileNotFoundError("No pitching projection files found!")

    # 1. Average Stats
    pitch_final = raw_pitch.groupby('PlayerId').mean(numeric_only=True).reset_index()
    
    # 2. Metadata
    meta_cols = [c for c in ['PlayerId', 'Name', 'Team'] if c in raw_pitch.columns]
    pitch_meta = raw_pitch[meta_cols].drop_duplicates('PlayerId')
    pitch_final = pd.merge(pitch_final, pitch_meta, on='PlayerId', how='left')

    # 3. Auction File
    auc_pitch_path = os.path.join(data_dir, auction_pitch_file)
    if os.path.exists(auc_pitch_path):
        auc_df = pd.read_csv(auc_pitch_path)
        auc_df.rename(columns={'Pos': 'POS', 'Position': 'POS'}, inplace=True)
        
        auc_cols = ['PlayerId', 'Dollars']
        # Pitchers usually just default to 'P', but we grab POS if there
        if 'POS' in auc_df.columns:
            auc_cols.append('POS')

        auc_subset = auc_df[auc_cols]
        pitch_final = pd.merge(pitch_final, auc_subset, on='PlayerId', how='left')
        pitch_final['Dollars'] = pitch_final['Dollars'].fillna(0)
    else:
        pitch_final['Dollars'] = 0
    
    # 4. Fallback POS
    if 'POS' not in pitch_final.columns:
        pitch_final['POS'] = 'P'
    else:
        if 'POS_x' in pitch_final.columns and 'POS_y' in pitch_final.columns:
            pitch_final['POS'] = pitch_final['POS_y'].combine_first(pitch_final['POS_x'])
            pitch_final.drop(columns=['POS_x', 'POS_y'], inplace=True)

    pitch_final['Type'] = 'Pitcher'

    # --- REVERSE ENGINEERING (ERA/WHIP) ---
    pitch_final['ER'] = (pitch_final['ERA'] * pitch_final['IP']) / 9
    pitch_final['H_BB'] = pitch_final['WHIP'] * pitch_final['IP']

    return bat_final, pitch_final