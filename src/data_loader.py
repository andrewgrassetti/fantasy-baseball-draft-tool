import pandas as pd
import os
import string
import random

# --- COLUMN DEFINITIONS (matching R script) ---
COLUMNS_TO_KEEP = {
    'batting': ['AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'ADP', 'PlayerId'],
    'pitching': ['IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 'ADP', 'PlayerId'],
    'auction': ['Name', 'POS', 'PlayerId', 'Dollars'],
    'statcast': ['PlayerId', 'Barrel%', 'maxEV']
}

# Average patterns (columns to collapse via row-wise mean)
BATTING_AVERAGES = ['AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'ADP', 'Dollars']
PITCHING_AVERAGES = ['IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 'ADP', 'Dollars']


def _safe_read_csv(path):
    """Safely read CSV with encoding fallback."""
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path, encoding='utf-8-sig')
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding='latin-1')


def _standardize_columns(df):
    """Standardize column name variations to canonical forms."""
    rename_map = {
        'Pos': 'POS',
        'Position': 'POS',
        'playerid': 'PlayerId',
        'wRC.': 'wRC+',
        'Barrel.': 'Barrel%',
        'K.9': 'K/9'
    }
    df = df.rename(columns=rename_map)
    
    # Ensure PlayerId is string for consistent merging
    if 'PlayerId' in df.columns:
        df['PlayerId'] = df['PlayerId'].astype(str)
    
    return df


def _filter_columns(df, keep_cols):
    """Filter DataFrame to only specified columns that exist."""
    if df is None:
        return None
    available_cols = [col for col in keep_cols if col in df.columns]
    if not available_cols:
        return None
    return df[available_cols].copy()


def _merge_dfs(df_list, by_col='PlayerId'):
    """
    Sequentially merge DataFrames with auto-generated suffixes for duplicate columns.
    Mimics R's Reduce(merge, ..., all=TRUE) with random suffixes.
    """
    if not df_list:
        return pd.DataFrame()
    
    # Filter out None values
    df_list = [df for df in df_list if df is not None and not df.empty]
    
    if not df_list:
        return pd.DataFrame()
    
    result = df_list[0]
    
    for df in df_list[1:]:
        # Generate random suffix (like R script)
        suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
        result = pd.merge(result, df, on=by_col, how='outer', suffixes=('', f'.{suffix}'))
    
    return result


def _average_columns(df, patterns, digits=3):
    """
    Row-wise average columns matching each pattern.
    Mimics R's rowMeans(..., na.rm=TRUE).
    For each pattern, finds base column and all suffixed variants, then computes row mean.
    """
    for pattern in patterns:
        # Find all columns matching this pattern (base + suffixed versions)
        # Match exact pattern or pattern with suffix like ".xxxx"
        matching_cols = [col for col in df.columns 
                        if col == pattern or col.startswith(f"{pattern}.")]
        
        if len(matching_cols) > 0:
            # Compute row-wise mean, ignoring NaN values
            df[pattern] = df[matching_cols].mean(axis=1, skipna=True).round(digits)
    
    return df


def load_and_merge_data(data_dir="data"):
    """
    Loads projection CSVs AND Auction Value CSVs using wide merge strategy.
    Matches the logic from the R script for proper row-wise averaging.
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
    statcast_bat_file = "2025_statcast_bat.csv"
    
    # --- PROCESS BATTERS ---
    
    # 1. Load and filter auction (base of merge chain)
    bat_auc_path = os.path.join(data_dir, auction_bat_file)
    bat_auc = _safe_read_csv(bat_auc_path)
    if bat_auc is not None:
        bat_auc = _standardize_columns(bat_auc)
        bat_auc = _filter_columns(bat_auc, COLUMNS_TO_KEEP['auction'])
    
    # 2. Load and filter projection sources
    bat_projections = []
    for f in batting_files:
        path = os.path.join(data_dir, f)
        df = _safe_read_csv(path)
        if df is not None:
            df = _standardize_columns(df)
            df = _filter_columns(df, COLUMNS_TO_KEEP['batting'])
            if df is not None:
                bat_projections.append(df)
    
    # 3. Load and filter statcast
    statcast_path = os.path.join(data_dir, statcast_bat_file)
    statcast_bat = _safe_read_csv(statcast_path)
    if statcast_bat is not None:
        statcast_bat = _standardize_columns(statcast_bat)
        statcast_bat = _filter_columns(statcast_bat, COLUMNS_TO_KEEP['statcast'])
    
    # 4. Wide merge: auction + projections + statcast
    merge_list = []
    if bat_auc is not None:
        merge_list.append(bat_auc)
    merge_list.extend(bat_projections)
    if statcast_bat is not None:
        merge_list.append(statcast_bat)
    
    if not merge_list:
        raise FileNotFoundError("No batting data files found!")
    
    bat_merged = _merge_dfs(merge_list, by_col='PlayerId')
    
    # 5. Row-wise averaging
    bat_merged = _average_columns(bat_merged, BATTING_AVERAGES, digits=3)
    
    # 6. Add Barrel_prc if Barrel% exists
    if 'Barrel%' in bat_merged.columns:
        bat_merged['Barrel_prc'] = (bat_merged['Barrel%'] * 100).round(3)
    
    # 7. Ensure downstream compatibility columns
    bat_merged['Type'] = 'Batter'
    
    # Fill Dollars with 0 if missing
    if 'Dollars' not in bat_merged.columns:
        bat_merged['Dollars'] = 0
    else:
        bat_merged['Dollars'] = bat_merged['Dollars'].fillna(0)
    
    # Ensure POS exists
    if 'POS' not in bat_merged.columns:
        bat_merged['POS'] = 'Unknown'
    else:
        bat_merged['POS'] = bat_merged['POS'].fillna('Unknown')
    
    # Add Team column if missing (extract from first available metadata)
    if 'Team' not in bat_merged.columns:
        # Try to get Team from any projection file
        for f in batting_files:
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Team' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                team_map = df[['PlayerId', 'Team']].drop_duplicates('PlayerId')
                bat_merged = pd.merge(bat_merged, team_map, on='PlayerId', how='left')
                break
    
    # Add Name column if missing
    if 'Name' not in bat_merged.columns:
        for f in [auction_bat_file] + batting_files:
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Name' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                name_map = df[['PlayerId', 'Name']].drop_duplicates('PlayerId')
                bat_merged = pd.merge(bat_merged, name_map, on='PlayerId', how='left')
                break
    
    # Select final columns (only those that exist)
    bat_final_cols = ['Name', 'POS', 'PlayerId', 'Team', 'Type', 
                     'AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 
                     'ADP', 'Dollars', 'maxEV', 'Barrel_prc']
    bat_final_cols = [col for col in bat_final_cols if col in bat_merged.columns]
    bat_final = bat_merged[bat_final_cols].copy()
    
    # --- PROCESS PITCHERS ---
    
    # 1. Load and filter auction (base of merge chain)
    pitch_auc_path = os.path.join(data_dir, auction_pitch_file)
    pitch_auc = _safe_read_csv(pitch_auc_path)
    if pitch_auc is not None:
        pitch_auc = _standardize_columns(pitch_auc)
        pitch_auc = _filter_columns(pitch_auc, COLUMNS_TO_KEEP['auction'])
    
    # 2. Load and filter projection sources
    pitch_projections = []
    for f in pitching_files:
        path = os.path.join(data_dir, f)
        df = _safe_read_csv(path)
        if df is not None:
            df = _standardize_columns(df)
            df = _filter_columns(df, COLUMNS_TO_KEEP['pitching'])
            if df is not None:
                pitch_projections.append(df)
    
    # 3. Wide merge: auction + projections
    merge_list = []
    if pitch_auc is not None:
        merge_list.append(pitch_auc)
    merge_list.extend(pitch_projections)
    
    if not merge_list:
        raise FileNotFoundError("No pitching data files found!")
    
    pitch_merged = _merge_dfs(merge_list, by_col='PlayerId')
    
    # 4. Row-wise averaging
    pitch_merged = _average_columns(pitch_merged, PITCHING_AVERAGES, digits=3)
    
    # 5. Ensure downstream compatibility columns
    pitch_merged['Type'] = 'Pitcher'
    
    # Fill Dollars with 0 if missing
    if 'Dollars' not in pitch_merged.columns:
        pitch_merged['Dollars'] = 0
    else:
        pitch_merged['Dollars'] = pitch_merged['Dollars'].fillna(0)
    
    # Ensure POS exists (default to 'P' for pitchers)
    if 'POS' not in pitch_merged.columns:
        pitch_merged['POS'] = 'P'
    else:
        pitch_merged['POS'] = pitch_merged['POS'].fillna('P')
    
    # Add Team column if missing
    if 'Team' not in pitch_merged.columns:
        for f in pitching_files:
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Team' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                team_map = df[['PlayerId', 'Team']].drop_duplicates('PlayerId')
                pitch_merged = pd.merge(pitch_merged, team_map, on='PlayerId', how='left')
                break
    
    # Add Name column if missing
    if 'Name' not in pitch_merged.columns:
        for f in [auction_pitch_file] + pitching_files:
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Name' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                name_map = df[['PlayerId', 'Name']].drop_duplicates('PlayerId')
                pitch_merged = pd.merge(pitch_merged, name_map, on='PlayerId', how='left')
                break
    
    # Reverse engineering for ERA/WHIP
    if 'ERA' in pitch_merged.columns and 'IP' in pitch_merged.columns:
        pitch_merged['ER'] = (pitch_merged['ERA'] * pitch_merged['IP']) / 9
    if 'WHIP' in pitch_merged.columns and 'IP' in pitch_merged.columns:
        pitch_merged['H_BB'] = pitch_merged['WHIP'] * pitch_merged['IP']
    
    # Select final columns (only those that exist)
    pitch_final_cols = ['Name', 'POS', 'PlayerId', 'Team', 'Type',
                       'IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 
                       'ADP', 'Dollars', 'ER', 'H_BB']
    pitch_final_cols = [col for col in pitch_final_cols if col in pitch_merged.columns]
    pitch_final = pitch_merged[pitch_final_cols].copy()
    
    return bat_final, pitch_final