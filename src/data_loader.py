import pandas as pd
import os
import glob

def load_and_merge_data(data_dir="data"):
    """
    Loads all CSVs from the data directory, merges them by PlayerId,
    and calculates the average projections.
    """
    
    # 1. Define the files and their categories (Mapping your R list)
    # You can update these filenames as needed
    batting_files = [
        "2025_batx_bat.csv", "2025_steamer_bat.csv", 
        "2025_zips_bat.csv", "2025_oopsy_bat.csv"
    ]
    pitching_files = [
        "2025_batx_pitch.csv", "2025_steamer_pitch.csv", 
        "2025_zips_pitch.csv", "2025_oopsy_pitch.csv"
    ]
    
    # Columns to keep (The Python equivalent of your R vectors)
    bat_cols = ['PlayerId', 'Name', 'Team', 'POS', 'AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'ADP']
    pitch_cols = ['PlayerId', 'Name', 'Team', 'POS', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'K/9', 'QS', 'ADP']

    # 2. Helper to load and concat list of files
    def load_group(filenames, cols):
        dfs = []
        for f in filenames:
            path = os.path.join(data_dir, f)
            if os.path.exists(path):
                df = pd.read_csv(path)
                # Standardize column names if necessary here
                # ensure we only grab columns that exist in this specific file
                available_cols = [c for c in cols if c in df.columns] 
                dfs.append(df[available_cols])
        
        if not dfs:
            return pd.DataFrame()
            
        # Stack them all on top of each other
        return pd.concat(dfs, ignore_index=True)

    # 3. Process Batters
    raw_bat = load_group(batting_files, bat_cols)
    # Group by PlayerId and take the mean of numeric columns
    bat_final = raw_bat.groupby('PlayerId').mean(numeric_only=True).reset_index()
    # Merge back names/teams (taking the first occurrence)
    bat_meta = raw_bat[['PlayerId', 'Name', 'Team', 'POS']].drop_duplicates('PlayerId')
    bat_final = pd.merge(bat_final, bat_meta, on='PlayerId')
    bat_final['Type'] = 'Batter'

    # 4. Process Pitchers
    raw_pitch = load_group(pitching_files, pitch_cols)
    pitch_final = raw_pitch.groupby('PlayerId').mean(numeric_only=True).reset_index()
    pitch_meta = raw_pitch[['PlayerId', 'Name', 'Team', 'POS']].drop_duplicates('PlayerId')
    pitch_final = pd.merge(pitch_final, pitch_meta, on='PlayerId')
    pitch_final['Type'] = 'Pitcher'

    # 5. CRITICAL: Reverse Engineering for Accurate Team Totals
    # We cannot sum ERA/WHIP. We must sum ER and (H+BB).
    # ER = (ERA * IP) / 9
    pitch_final['ER'] = (pitch_final['ERA'] * pitch_final['IP']) / 9
    # H_BB = WHIP * IP
    pitch_final['H_BB'] = pitch_final['WHIP'] * pitch_final['IP']

    return bat_final, pitch_final