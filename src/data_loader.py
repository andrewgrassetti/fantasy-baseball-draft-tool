import pandas as pd
import os

# --- COLUMN DEFINITIONS (matching R script) ---
COLUMNS_TO_KEEP = {
    'batting': ['AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'ADP', 'PlayerId'],
    'pitching': ['IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 'QS', 'ADP', 'PlayerId'],
    'auction': ['Name', 'POS', 'PlayerId', 'Dollars'],
    'statcast': ['PlayerId', 'Barrel%', 'maxEV']
}

# Average patterns (columns to collapse via row-wise mean)
BATTING_AVERAGES = ['AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'ADP', 'Dollars']
PITCHING_AVERAGES = ['IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 'QS', 'ADP', 'Dollars']


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
    Sequentially merge DataFrames with deterministic suffixes for duplicate columns.
    Mimics R's Reduce(merge, ..., all=TRUE).
    Uses suffixes based on merge index for reproducibility.
    """
    if not df_list:
        return pd.DataFrame()
    
    # Filter out None values
    df_list = [df for df in df_list if df is not None and not df.empty]
    
    if not df_list:
        return pd.DataFrame()
    
    result = df_list[0]
    
    for idx, df in enumerate(df_list[1:], start=1):
        # Use deterministic suffix based on merge index
        suffix = f's{idx}'
        result = pd.merge(result, df, on=by_col, how='outer', suffixes=('', f'.{suffix}'))
    
    return result


def _average_columns(df, patterns, digits=3):
    """
    Row-wise average columns matching each pattern.
    Mimics R's rowMeans(..., na.rm=TRUE).
    For each pattern, finds base column and all suffixed variants (e.g., 'HR', 'HR.s1', 'HR.s2'),
    then computes row mean.
    """
    for pattern in patterns:
        # Find all columns matching this pattern (base + suffixed versions with .sN format)
        # Must match exact pattern or pattern with suffix like ".s1", ".s2", etc.
        import re
        pattern_regex = re.compile(f'^{re.escape(pattern)}(\\.s\\d+)?$')
        matching_cols = [col for col in df.columns if pattern_regex.match(col)]
        
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
        "2026_batx_bat.csv", "2026_steamer_bat.csv", 
        "2026_zips_bat.csv", "2026_oopsy_bat.csv"
    ]
    pitching_files = [
        "2026_batx_pitch.csv", "2026_steamer_pitch.csv", 
        "2026_zips_pitch.csv", "2026_oopsy_pitch.csv"
    ]
    
    auction_bat_files = ["2026_batx_auction_bat.csv", "2026_oopsy_auction_bat.csv"]
    auction_pitch_files = ["2026_oopsy_auction_pitch.csv", "2026_batx_auction_pitch.csv"]
    
    # Extract year from projection files and use previous year for statcast
    # Statcast data is always from the prior season
    import re
    year_match = re.search(r'(\d{4})_', batting_files[0])
    if year_match:
        projection_year = int(year_match.group(1))
        statcast_year = projection_year - 1
        statcast_bat_file = f"{statcast_year}_statcast_bat.csv"
    else:
        # Fallback if year pattern not found
        statcast_bat_file = "2025_statcast_bat.csv"
    
    # --- PROCESS BATTERS ---
    
    # 1. Load and filter auction sources (base of merge chain)
    bat_auctions = []
    for f in auction_bat_files:
        path = os.path.join(data_dir, f)
        df = _safe_read_csv(path)
        if df is not None:
            df = _standardize_columns(df)
            df = _filter_columns(df, COLUMNS_TO_KEEP['auction'])
            if df is not None:
                bat_auctions.append(df)
    
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
    
    # 4. Collect auction PlayerIds (defines the draftable player universe)
    bat_auction_ids = set()
    for adf in bat_auctions:
        if 'PlayerId' in adf.columns:
            bat_auction_ids.update(adf['PlayerId'].values)
    
    # 5. Wide merge: auctions + projections + statcast
    merge_list = []
    merge_list.extend(bat_auctions)
    merge_list.extend(bat_projections)
    if statcast_bat is not None:
        merge_list.append(statcast_bat)
    
    if not merge_list:
        raise FileNotFoundError("No batting data files found!")
    
    bat_merged = _merge_dfs(merge_list, by_col='PlayerId')
    
    # 6. Filter to only include players from auction sources
    # Projection-only players (not in any auction file) have no fantasy value
    # and would otherwise swamp the available player pool with thousands of $0 entries
    if bat_auction_ids:
        bat_merged = bat_merged[bat_merged['PlayerId'].isin(bat_auction_ids)]
    
    # 7. Row-wise averaging
    bat_merged = _average_columns(bat_merged, BATTING_AVERAGES, digits=3)
    
    # 8. Add Barrel_prc if Barrel% exists
    # Note: Barrel% from statcast is a decimal (0-1, e.g., 0.268 = 26.8% barrel rate)
    # Barrel_prc converts to percentage scale (0-100) for easier interpretation
    # Keeping both for flexibility in downstream visualizations
    if 'Barrel%' in bat_merged.columns:
        bat_merged['Barrel_prc'] = (bat_merged['Barrel%'] * 100).round(3)
    
    # 9. Ensure downstream compatibility columns
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
    
    # Add Team column if missing or fill NaN values
    if 'Team' not in bat_merged.columns or bat_merged.get('Team', pd.Series()).isna().any():
        for f in auction_bat_files + batting_files:
            if 'Team' in bat_merged.columns and not bat_merged['Team'].isna().any():
                break
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Team' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                team_map = df.drop_duplicates('PlayerId').set_index('PlayerId')['Team']
                if 'Team' not in bat_merged.columns:
                    bat_merged['Team'] = bat_merged['PlayerId'].map(team_map)
                else:
                    mask = bat_merged['Team'].isna()
                    bat_merged.loc[mask, 'Team'] = bat_merged.loc[mask, 'PlayerId'].map(team_map)
    
    # Add Name column if missing or fill NaN values
    if 'Name' not in bat_merged.columns or bat_merged.get('Name', pd.Series()).isna().any():
        for f in auction_bat_files + batting_files:
            if 'Name' in bat_merged.columns and not bat_merged['Name'].isna().any():
                break
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Name' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                name_map = df.drop_duplicates('PlayerId').set_index('PlayerId')['Name']
                if 'Name' not in bat_merged.columns:
                    bat_merged['Name'] = bat_merged['PlayerId'].map(name_map)
                else:
                    mask = bat_merged['Name'].isna()
                    bat_merged.loc[mask, 'Name'] = bat_merged.loc[mask, 'PlayerId'].map(name_map)
    
    # Select final columns (only those that exist)
    bat_final_cols = ['Name', 'POS', 'PlayerId', 'Team', 'Type', 
                     'AB', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 
                     'ADP', 'Dollars', 'maxEV', 'Barrel_prc']
    bat_final_cols = [col for col in bat_final_cols if col in bat_merged.columns]
    bat_final = bat_merged[bat_final_cols].copy()
    
    # --- PROCESS PITCHERS ---
    
    # 1. Load and filter auction sources (base of merge chain)
    pitch_auctions = []
    for f in auction_pitch_files:
        path = os.path.join(data_dir, f)
        df = _safe_read_csv(path)
        if df is not None:
            df = _standardize_columns(df)
            df = _filter_columns(df, COLUMNS_TO_KEEP['auction'])
            if df is not None:
                pitch_auctions.append(df)
    
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
    
    # 3. Collect auction PlayerIds (defines the draftable player universe)
    pitch_auction_ids = set()
    for adf in pitch_auctions:
        if 'PlayerId' in adf.columns:
            pitch_auction_ids.update(adf['PlayerId'].values)
    
    # 4. Wide merge: auctions + projections
    merge_list = []
    merge_list.extend(pitch_auctions)
    merge_list.extend(pitch_projections)
    
    if not merge_list:
        raise FileNotFoundError("No pitching data files found!")
    
    pitch_merged = _merge_dfs(merge_list, by_col='PlayerId')
    
    # 5. Filter to only include players from auction sources
    # Projection-only players (not in any auction file) have no fantasy value
    # and would otherwise swamp the available player pool with thousands of $0 entries
    if pitch_auction_ids:
        pitch_merged = pitch_merged[pitch_merged['PlayerId'].isin(pitch_auction_ids)]
    
    # 6. Row-wise averaging
    pitch_merged = _average_columns(pitch_merged, PITCHING_AVERAGES, digits=3)
    
    # 7. Ensure downstream compatibility columns
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
    
    # Add Team column if missing or fill NaN values
    if 'Team' not in pitch_merged.columns or pitch_merged.get('Team', pd.Series()).isna().any():
        for f in auction_pitch_files + pitching_files:
            if 'Team' in pitch_merged.columns and not pitch_merged['Team'].isna().any():
                break
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Team' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                team_map = df.drop_duplicates('PlayerId').set_index('PlayerId')['Team']
                if 'Team' not in pitch_merged.columns:
                    pitch_merged['Team'] = pitch_merged['PlayerId'].map(team_map)
                else:
                    mask = pitch_merged['Team'].isna()
                    pitch_merged.loc[mask, 'Team'] = pitch_merged.loc[mask, 'PlayerId'].map(team_map)
    
    # Add Name column if missing or fill NaN values
    if 'Name' not in pitch_merged.columns or pitch_merged.get('Name', pd.Series()).isna().any():
        for f in auction_pitch_files + pitching_files:
            if 'Name' in pitch_merged.columns and not pitch_merged['Name'].isna().any():
                break
            path = os.path.join(data_dir, f)
            df = _safe_read_csv(path)
            if df is not None and 'Name' in df.columns and 'PlayerId' in df.columns:
                df = _standardize_columns(df)
                name_map = df.drop_duplicates('PlayerId').set_index('PlayerId')['Name']
                if 'Name' not in pitch_merged.columns:
                    pitch_merged['Name'] = pitch_merged['PlayerId'].map(name_map)
                else:
                    mask = pitch_merged['Name'].isna()
                    pitch_merged.loc[mask, 'Name'] = pitch_merged.loc[mask, 'PlayerId'].map(name_map)
    
    # Reverse engineering for ERA/WHIP
    if 'ERA' in pitch_merged.columns and 'IP' in pitch_merged.columns:
        pitch_merged['ER'] = (pitch_merged['ERA'] * pitch_merged['IP']) / 9
    if 'WHIP' in pitch_merged.columns and 'IP' in pitch_merged.columns:
        pitch_merged['H_BB'] = pitch_merged['WHIP'] * pitch_merged['IP']
    
    # Select final columns (only those that exist)
    pitch_final_cols = ['Name', 'POS', 'PlayerId', 'Team', 'Type',
                       'IP', 'SO', 'ERA', 'WHIP', 'WAR', 'K/9', 'SV', 'QS',
                       'ADP', 'Dollars', 'ER', 'H_BB']
    pitch_final_cols = [col for col in pitch_final_cols if col in pitch_merged.columns]
    pitch_final = pitch_merged[pitch_final_cols].copy()
    
    # --- NORMALIZE DOLLAR VALUES ---
    # Auction dollar values can be negative (e.g., min around -70).
    # Shift all values up so the lowest becomes 1, ensuring every player
    # has a positive value for proper sorting and simulator weighting.
    if not bat_final.empty and not pitch_final.empty:
        overall_min = min(bat_final['Dollars'].min(), pitch_final['Dollars'].min())
    elif not bat_final.empty:
        overall_min = bat_final['Dollars'].min()
    elif not pitch_final.empty:
        overall_min = pitch_final['Dollars'].min()
    else:
        overall_min = 0
    
    if overall_min < 1:
        shift = abs(overall_min) + 1
        if not bat_final.empty:
            bat_final['Dollars'] = (bat_final['Dollars'] + shift).round(3)
        if not pitch_final.empty:
            pitch_final['Dollars'] = (pitch_final['Dollars'] + shift).round(3)
    
    return bat_final, pitch_final