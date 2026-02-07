import pandas as pd
import os

def load_and_merge_data(data_dir="data"):
    """
    Loads projection CSVs AND Auction Value CSVs, merging them by PlayerId.
    """
    
    # --- FILE CONFIGURATION ---
    # Projection Files
    batting_files = [
        "2025_batx_bat.csv", "2025_steamer_bat.csv", 
        "2025_zips_bat.csv", "2025_oopsy_bat.csv"
    ]
    pitching_files = [
        "2025_batx_pitch.csv", "2025_steamer_pitch.csv", 
        "2025_zips_pitch.csv", "2025_oopsy_pitch.csv"
    ]
    
    # Auction Files (Single source as per your R code)
    auction_bat_file = "2025_batx_auction_bat.csv"
    auction_pitch_file = "2025_oopsy_auction_pitch.csv"

    # Columns to Keep
    bat_cols = ['PlayerId', 'Name', 'Team', 'POS', 'AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'ADP']
    pitch_cols = ['PlayerId', 'Name', 'Team', 'POS', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS', 'ADP']
    auction_cols = ['PlayerId', 'Dollars']  # We only need the ID and the Value

    # --- HELPER FUNCTION ---
    def load_group(filenames, cols):
        dfs = []
        for f in filenames:
            path = os.path.join(data_dir, f)
            if os.path.exists(path):
                # Only load columns that actually exist in the file
                df = pd.read_csv(path)
                valid_cols = [c for c in cols if c in df.columns]
                dfs.append(df[valid_cols])
        
        if not dfs:
            return pd.DataFrame()
        return pd.concat(dfs, ignore_index=True)

    # --- LOAD & PROCESS BATTERS ---
    # 1. Load Projections
    raw_bat = load_group(batting_files, bat_cols)
    if raw_bat.empty:
        raise FileNotFoundError("No batting projection files found in /data folder!")

    # 2. Average the Projections
    bat_final = raw_bat.groupby('PlayerId').mean(numeric_only=True).reset_index()
    
    # 3. Merge Metadata (Name, Team, POS) from the first file found
    bat_meta = raw_bat[['PlayerId', 'Name', 'Team', 'POS']].drop_duplicates('PlayerId')
    bat_final = pd.merge(bat_final, bat_meta, on='PlayerId', how='left')

    # 4. Load & Merge Auction Values
    auc_bat_path = os.path.join(data_dir, auction_bat_file)
    if os.path.exists(auc_bat_path):
        auc_df = pd.read_csv(auc_bat_path)[auction_cols]
        # Merge on PlayerId, keep all batters even if they have no auction value
        bat_final = pd.merge(bat_final, auc_df, on='PlayerId', how='left')
        bat_final['Dollars'] = bat_final['Dollars'].fillna(0) # Fill missing with $0
    else:
        bat_final['Dollars'] = 0

    bat_final['Type'] = 'Batter'

    # --- LOAD & PROCESS PITCHERS ---
    # 1. Load Projections
    raw_pitch = load_group(pitching_files, pitch_cols)
    if raw_pitch.empty:
        raise FileNotFoundError("No pitching projection files found in /data folder!")

    # 2. Average the Projections
    pitch_final = raw_pitch.groupby('PlayerId').mean(numeric_only=True).reset_index()
    
    # 3. Merge Metadata
    pitch_meta = raw_pitch[['PlayerId', 'Name', 'Team', 'POS']].drop_duplicates('PlayerId')
    pitch_final = pd.merge(pitch_final, pitch_meta, on='PlayerId', how='left')

    # 4. Load & Merge Auction Values
    auc_pitch_path = os.path.join(data_dir, auction_pitch_file)
    if os.path.exists(auc_pitch_path):
        auc_df = pd.read_csv(auc_pitch_path)[auction_cols]
        pitch_final = pd.merge(pitch_final, auc_df, on='PlayerId', how='left')
        pitch_final['Dollars'] = pitch_final['Dollars'].fillna(0)
    else:
        pitch_final['Dollars'] = 0

    pitch_final['Type'] = 'Pitcher'

    # --- REVERSE ENGINEERING (ERA/WHIP) ---
    pitch_final['ER'] = (pitch_final['ERA'] * pitch_final['IP']) / 9
    pitch_final['H_BB'] = pitch_final['WHIP'] * pitch_final['IP']

    return bat_final, pitch_final