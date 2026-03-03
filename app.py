import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import os
import random
from src.data_loader import load_and_merge_data
from src.draft_engine import DraftEngine
from src.persistence import save_keeper_config, load_keeper_config, list_saved_configs, delete_keeper_config
from src.draft_simulator import DraftSimulator, run_monte_carlo_snapshot

# Page Config (Wide layout is better for dashboards)
st.set_page_config(page_title="Fantasy Draft Tool", layout="wide")

# --- SESSION STATE SETUP ---
# Streamlit re-runs the script on every click. 
# We use session_state to persist the DraftEngine across re-runs.
if 'engine' not in st.session_state:
    with st.spinner("Loading Data..."):
        bat_df, pitch_df = load_and_merge_data()
        st.session_state.engine = DraftEngine(bat_df, pitch_df)

engine = st.session_state.engine

# --- DRAFT ROOM STATE ---
if 'draft_queue' not in st.session_state:
    st.session_state.draft_queue = []
if 'selected_player' not in st.session_state:
    st.session_state.selected_player = None
if 'table_key_counter' not in st.session_state:
    st.session_state.table_key_counter = 0
if 'user_team_name' not in st.session_state:
    st.session_state.user_team_name = None

# --- SIMULATOR STATE ---
if 'sim_draft_queue' not in st.session_state:
    st.session_state.sim_draft_queue = []
if 'sim_selected_player' not in st.session_state:
    st.session_state.sim_selected_player = None
if 'sim_table_key_counter' not in st.session_state:
    st.session_state.sim_table_key_counter = 0
if 'sim_new_picks' not in st.session_state:
    st.session_state.sim_new_picks = []
if 'sim_random_seed' not in st.session_state:
    st.session_state.sim_random_seed = random.randint(1, 10000)

# --- AUTO-LOAD TENDENCY PROFILES ---
# On first run, automatically load profiles/tendencies.json if it exists.
if 'team_profiles' not in st.session_state:
    _auto_profiles_path = os.path.join("profiles", "tendencies.json")
    if os.path.exists(_auto_profiles_path):
        try:
            import json as _json_auto
            with open(_auto_profiles_path, 'r') as _apf:
                _auto_loaded = _json_auto.load(_apf)
            _auto_profiles_list = _auto_loaded.get("profiles", [])
            st.session_state.team_profiles = {p["team_name"]: p for p in _auto_profiles_list}
        except Exception:
            st.session_state.team_profiles = {}
    else:
        st.session_state.team_profiles = {}
if 'tendencies_enabled' not in st.session_state:
    # Enable by default when profiles were auto-loaded
    st.session_state.tendencies_enabled = bool(st.session_state.get('team_profiles'))

# Auto-cleanup: remove unavailable players from the draft queue
if st.session_state.draft_queue:
    available_pids = set(
        engine.bat_df[engine.bat_df['Status'] == 'Available']['PlayerId'].tolist() +
        engine.pitch_df[engine.pitch_df['Status'] == 'Available']['PlayerId'].tolist()
    )
    st.session_state.draft_queue = [
        p for p in st.session_state.draft_queue if p['PlayerId'] in available_pids
    ]

# Auto-cleanup: remove unavailable players from the simulator draft queue
if st.session_state.sim_draft_queue and 'simulator' in st.session_state:
    sim_available_pids = set(
        st.session_state.simulator.engine.bat_df[st.session_state.simulator.engine.bat_df['Status'] == 'Available']['PlayerId'].tolist() +
        st.session_state.simulator.engine.pitch_df[st.session_state.simulator.engine.pitch_df['Status'] == 'Available']['PlayerId'].tolist()
    )
    st.session_state.sim_draft_queue = [
        p for p in st.session_state.sim_draft_queue if p['PlayerId'] in sim_available_pids
    ]

# --- TABS ---
tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(["⚙️ Pre-Draft Setup", "⚾ Draft Room", "📊 Market Analysis", "👥 Team Rosters", "🎲 Draft Simulator", "📊 Player Tendencies"])

# ==========================================
# TAB 0: PRE-DRAFT SETUP
# ==========================================
with tab0:
    st.header("⚙️ Pre-Draft Configuration")
    
    # --- TEAM NAMES CONFIGURATION ---
    st.subheader("1. Configure Team Names")
    
    # Get current team names
    current_teams = list(engine.teams.keys())
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Number of teams selector
        num_teams = st.number_input(
            "Number of Teams",
            min_value=2,
            max_value=20,
            value=len(current_teams),
            step=1
        )
        
        # Text area for team names (one per line)
        team_names_text = st.text_area(
            "Team Names (one per line)",
            value="\n".join(current_teams),
            height=200,
            help="Enter one team name per line. The number of lines should match the number of teams."
        )
        
        if st.button("Update Team Names", type="primary"):
            # Parse team names from text area
            new_names = [name.strip() for name in team_names_text.split("\n") if name.strip()]
            
            if len(new_names) != num_teams:
                st.error(f"Please enter exactly {num_teams} team names (one per line)")
            elif len(new_names) != len(set(new_names)):
                st.error("Team names must be unique")
            else:
                # Update team names
                engine.set_team_names(new_names)
                st.success(f"Updated to {len(new_names)} teams")
                st.rerun()
    
    with col2:
        st.info(f"**Current:** {len(current_teams)} teams")
    
    st.divider()
    
    # --- KEEPER ASSIGNMENTS ---
    st.subheader("2. Assign Keepers")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("**Add Keeper**")
        
        # Team selector
        keeper_team = st.selectbox("Select Team", list(engine.teams.keys()), key="keeper_team")
        
        # Combined player search (same as Draft Room)
        avail_bat = engine.bat_df[engine.bat_df['Status'] == 'Available']
        avail_pitch = engine.pitch_df[engine.pitch_df['Status'] == 'Available']
        
        search_options = {}
        
        for _, row in avail_bat.iterrows():
            label = f"{row['Name']} ({row['POS']}) - {row.get('Team', 'N/A')}"
            search_options[label] = (row['PlayerId'], False)
        
        for _, row in avail_pitch.iterrows():
            label = f"{row['Name']} (P) - {row.get('Team', 'N/A')}"
            search_options[label] = (row['PlayerId'], True)
        
        if search_options:
            selected_keeper_label = st.selectbox(
                "Search Player",
                options=list(search_options.keys()),
                key="keeper_player"
            )
            
            keeper_cost = st.number_input(
                "Keeper Cost ($)",
                min_value=0.0,
                max_value=1000.0,
                value=0.0,
                step=1.0,
                help="Optional: Set the draft cost for this keeper"
            )
            
            if st.button("Add Keeper", type="primary"):
                pid, is_pitcher = search_options[selected_keeper_label]
                if engine.process_keeper(pid, keeper_team, cost=keeper_cost, is_pitcher=is_pitcher):
                    st.success(f"Added {selected_keeper_label} to {keeper_team}")
                    st.rerun()
                else:
                    st.error("Failed to add keeper")
        else:
            st.info("All players have been assigned. No available players remaining.")

        # --- Write-in Keeper ---
        st.divider()
        st.markdown("**✏️ Write-in Keeper** (player not in projections)")
        wi_keeper_name = st.text_input("Player Name", key="wi_keeper_name")
        wi_col1, wi_col2 = st.columns(2)
        with wi_col1:
            wi_keeper_pos = st.text_input("Position (e.g. SS, SP)", key="wi_keeper_pos")
        with wi_col2:
            wi_keeper_mlb = st.text_input("MLB Team", key="wi_keeper_mlb")
        wi_col3, wi_col4 = st.columns(2)
        with wi_col3:
            wi_keeper_type = st.radio("Player Type", ["Batter", "Pitcher"], horizontal=True, key="wi_keeper_type")
        with wi_col4:
            wi_keeper_cost = st.number_input("Keeper Cost ($)", min_value=0.0, max_value=1000.0, value=0.0, step=1.0, key="wi_keeper_cost")
        if st.button("Add Write-in Keeper", type="secondary"):
            if not wi_keeper_name.strip():
                st.error("Player name is required")
            else:
                engine.process_writein(
                    name=wi_keeper_name.strip(),
                    team_name=keeper_team,
                    is_pitcher=(wi_keeper_type == "Pitcher"),
                    position=wi_keeper_pos.strip(),
                    mlb_team=wi_keeper_mlb.strip(),
                    cost=wi_keeper_cost,
                    status='Keeper',
                )
                st.success(f"Added write-in keeper {wi_keeper_name.strip()} to {keeper_team}")
                st.rerun()
    
    with col2:
        st.markdown("**Current Keepers**")
        
        # Get all keepers from all teams
        all_keepers = []
        for team_name, team in engine.teams.items():
            for player in team.roster:
                # Write-in players are always considered keepers
                if player.is_writein:
                    all_keepers.append({
                        'Team': team_name,
                        'Player': f"✏️ {player.name}",
                        'Position': player.position,
                        'Cost': player.dollars,
                        'ID': player.player_id,
                        'is_pitcher': player.is_pitcher
                    })
                    continue
                # Check if player is a keeper
                if player.is_pitcher:
                    mask = engine.pitch_df['PlayerId'] == player.player_id
                    if not engine.pitch_df.loc[mask].empty:
                        status = engine.pitch_df.loc[mask, 'Status'].iloc[0]
                        if status == 'Keeper':
                            all_keepers.append({
                                'Team': team_name,
                                'Player': player.name,
                                'Position': player.position,
                                'Cost': player.dollars,
                                'ID': player.player_id,
                                'is_pitcher': True
                            })
                else:
                    mask = engine.bat_df['PlayerId'] == player.player_id
                    if not engine.bat_df.loc[mask].empty:
                        status = engine.bat_df.loc[mask, 'Status'].iloc[0]
                        if status == 'Keeper':
                            all_keepers.append({
                                'Team': team_name,
                                'Player': player.name,
                                'Position': player.position,
                                'Cost': player.dollars,
                                'ID': player.player_id,
                                'is_pitcher': False
                            })
        
        if all_keepers:
            # Group by team
            for team_name in sorted(set(k['Team'] for k in all_keepers)):
                team_keepers = [k for k in all_keepers if k['Team'] == team_name]
                with st.expander(f"**{team_name}** ({len(team_keepers)} keepers)"):
                    for idx, keeper in enumerate(team_keepers):
                        col_a, col_b = st.columns([3, 1])
                        with col_a:
                            st.text(f"{keeper['Player']} ({keeper['Position']}) - ${keeper['Cost']:.0f}")
                        with col_b:
                            player_type = "P" if keeper['is_pitcher'] else "B"
                            if st.button("Remove", key=f"remove_{keeper['ID']}_{player_type}_{keeper['Team']}_{idx}"):
                                if engine.remove_keeper(keeper['ID'], keeper['is_pitcher']):
                                    st.success("Removed")
                                    st.rerun()
                                else:
                                    st.error("Failed")
        else:
            st.info("No keepers assigned yet")
    
    st.divider()
    
    # --- SAVE/LOAD CONFIGURATION ---
    st.subheader("3. Save/Load Configuration")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("**Save Current Configuration**")
        
        config_name = st.text_input(
            "Configuration Name",
            value="Keepers 2026",
            help="Enter a name for this keeper configuration"
        )
        
        if st.button("💾 Save Configuration", type="primary"):
            if not config_name.strip():
                st.error("Please enter a configuration name")
            else:
                try:
                    # Export current configuration
                    config_data = engine.export_keeper_config()
                    
                    # Save to file
                    filepath = save_keeper_config(
                        name=config_name,
                        team_names=config_data['team_names'],
                        keepers=config_data['keepers']
                    )
                    
                    st.success(f"✅ Saved to: {filepath}")
                except Exception as e:
                    st.error(f"Failed to save: {str(e)}")
    
    with col2:
        st.markdown("**Load Saved Configuration**")
        
        # List saved configurations
        saved_configs = list_saved_configs()
        
        if saved_configs:
            config_options = {}
            for cfg in saved_configs:
                created_date = cfg['created_at']
                if created_date != 'Unknown':
                    created_date = created_date[:10]  # Extract YYYY-MM-DD
                # Include the filename in the display for clarity
                display_name = f"{cfg['name']} ({cfg['filename']})"
                config_options[display_name] = cfg['filepath']
            
            selected_config = st.selectbox(
                "Select Configuration",
                options=list(config_options.keys()),
                key="load_config"
            )
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                if st.button("📂 Load", type="primary"):
                    try:
                        filepath = config_options[selected_config]
                        config = load_keeper_config(filepath)
                        
                        if engine.import_keeper_config(config):
                            st.success(f"✅ Loaded: {config['name']}")
                            st.rerun()
                        else:
                            st.error("Failed to import configuration")
                    except Exception as e:
                        st.error(f"Failed to load: {str(e)}")
            
            with col_b:
                if st.button("🗑️ Delete"):
                    try:
                        filepath = config_options[selected_config]
                        if delete_keeper_config(filepath):
                            st.success("Deleted")
                            st.rerun()
                        else:
                            st.error("Failed to delete")
                    except Exception as e:
                        st.error(f"Failed: {str(e)}")
        else:
            st.info("No saved configurations found")

# ==========================================
# TAB 1: DRAFT ROOM (MAIN DASHBOARD)
# ==========================================
with tab1:
    # Pre-compute selected_player from table selection state.  Streamlit stores
    # widget state in st.session_state before the script body runs on each rerun,
    # so we can read the table's selection here before rendering col1 which
    # depends on it — avoiding a one-rerun lag.
    _view_pre = st.session_state.get('available_players_view', 'Batters')
    if _view_pre == 'Batters':
        _df_pre = engine.bat_df[engine.bat_df['Status'] == 'Available'].copy()
        _pre_cols = ['Name', 'POS', 'Team', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA',
                     'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'ADP', 'Dollars']
    elif _view_pre == 'Pitchers':
        _df_pre = engine.pitch_df[engine.pitch_df['Status'] == 'Available'].copy()
        _pre_cols = ['Name', 'POS', 'Team', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS',
                     'K/9', 'WAR', 'ADP', 'Dollars']
    else:
        _df_bat = engine.bat_df[engine.bat_df['Status'] == 'Available'].copy()
        _df_bat['_is_pitcher'] = False
        _df_pitch = engine.pitch_df[engine.pitch_df['Status'] == 'Available'].copy()
        _df_pitch['_is_pitcher'] = True
        _pre_cols = ['Name', 'POS', 'Team', 'WAR', 'ADP', 'Dollars']
        _df_pre = pd.concat([_df_bat, _df_pitch], ignore_index=True)
    _pre_cols = [c for c in _pre_cols if c in _df_pre.columns]
    _pos_pre = st.session_state.get('avail_pos_filter', 'All')
    if _pos_pre and _pos_pre != 'All':
        _df_pre = _df_pre[_df_pre['POS'].fillna('').apply(
            lambda x: _pos_pre in [p.strip() for p in str(x).split('/')])]
    _sort_by_pre = st.session_state.get('avail_sort_by', 'Dollars')
    _sort_order_pre = st.session_state.get('avail_sort_order', 'Descending')
    if _sort_by_pre and _sort_by_pre in _df_pre.columns:
        _df_pre = _df_pre.sort_values(
            by=_sort_by_pre, ascending=(_sort_order_pre == 'Ascending'), na_position='last')
    _tbl_key = f"available_players_table_{st.session_state.table_key_counter}"
    _tbl_state = st.session_state.get(_tbl_key)
    if _tbl_state is not None and hasattr(_tbl_state, 'selection') and _tbl_state.selection.rows:
        _ridx = _tbl_state.selection.rows[0]
        if _ridx < len(_df_pre):
            _r = _df_pre.iloc[_ridx]
            _dollars = _r.get('Dollars') if 'Dollars' in _df_pre.columns else None
            st.session_state.selected_player = {
                'PlayerId': _r['PlayerId'],
                'Name': _r['Name'],
                'POS': _r['POS'],
                'is_pitcher': bool(_r.get('_is_pitcher', _view_pre == 'Pitchers')),
                'Dollars': float(_dollars) if _dollars is not None and not pd.isna(_dollars) else None,
            }
        else:
            st.session_state.selected_player = None
    elif _tbl_state is not None:
        # Table rendered with no selection
        st.session_state.selected_player = None

    # --- DRAFT ORDER & USER TEAM SETUP ---
    st.subheader("📋 Draft Setup")

    # --- PROFILE STATUS INDICATOR ---
    _draft_profiles = st.session_state.get('team_profiles') if st.session_state.get('tendencies_enabled') else None
    if _draft_profiles:
        st.success(f"✅ Tendency profiles active — {len(_draft_profiles)} teams loaded from 📊 Player Tendencies")
    else:
        st.info("ℹ️ No tendency profiles active — using default tendencies. Toggle profiles on in the 📊 Player Tendencies tab.")

    _setup_col1, _setup_col2 = st.columns([2, 1])

    with _setup_col1:
        _draft_order_uploaded = st.file_uploader(
            "Upload Draft Order CSV",
            type=['csv'],
            key="draft_room_csv_uploader",
            help="CSV must have columns: player_name, pick_number (tendency column is optional)",
        )
        if _draft_order_uploaded is not None:
            st.session_state.draft_csv = _draft_order_uploaded.getvalue().decode('utf-8')
            st.success("✅ Draft order CSV loaded.")

    with _setup_col2:
        st.markdown("**CSV Format:**")
        st.code("player_name,pick_number\nTeam A,1\nTeam B,2\nTeam A,3\nTeam B,4", language="csv")
        st.caption("💡 Tendency column is optional. Load profiles in the 📊 Player Tendencies tab for data-driven tendencies.")

    if 'draft_csv' in st.session_state and st.session_state.draft_csv:
        from io import StringIO
        _draft_order_df = pd.read_csv(StringIO(st.session_state.draft_csv))
        _csv_team_names = sorted(_draft_order_df['player_name'].unique())

        _user_team = st.selectbox(
            "Your Team",
            options=_csv_team_names,
            key="user_team_select",
            help="Select your team from the draft order",
        )
        st.session_state.user_team_name = _user_team
    else:
        st.info("Upload a draft order CSV to enable auto-drafter and snapshot features.")
        _draft_order_df = None

    # Determine auto-drafter from draft order + picks made
    _auto_drafter = None
    _auto_pick_number = None
    _is_user_turn = False
    if _draft_order_df is not None:
        _auto_pick_index = engine.get_total_picks_made()
        if _auto_pick_index < len(_draft_order_df):
            _auto_drafter = _draft_order_df.iloc[_auto_pick_index]['player_name']
            _auto_pick_number = int(_draft_order_df.iloc[_auto_pick_index]['pick_number'])
            _is_user_turn = (_auto_drafter == st.session_state.get('user_team_name'))

    if _auto_drafter:
        if _is_user_turn:
            st.success(f"🎯 **YOUR PICK!** Pick #{_auto_pick_number} — {_auto_drafter}")
        else:
            st.info(f"📍 Pick #{_auto_pick_number} — {_auto_drafter}")

    st.divider()

    # Top Row: Standings and Undo
    top_col1, top_col2 = st.columns([2, 1])

    with top_col1:
        st.header("Live Standings (5x5)")
        standings = engine.get_standings()
        st.dataframe(standings, hide_index=True, width="stretch")

    with top_col2:
        st.header("Undo Pick")

        # Get all drafted players (not keepers)
        drafted_bat = engine.bat_df[engine.bat_df['Status'] == 'Drafted']
        drafted_pitch = engine.pitch_df[engine.pitch_df['Status'] == 'Drafted']

        # Create a display string: "Name (POS) — Team Name"
        undo_options = {}  # Map "Display Name" -> player_id

        for _, row in drafted_bat.iterrows():
            label = f"{row['Name']} ({row['POS']}) — {row['DraftedBy']}"
            undo_options[label] = row['PlayerId']

        for _, row in drafted_pitch.iterrows():
            label = f"{row['Name']} (P) — {row['DraftedBy']}"
            undo_options[label] = row['PlayerId']

        # Include write-in drafted players (not in DataFrames)
        for team_name, team in engine.teams.items():
            for player in team.roster:
                if player.is_writein:
                    pos = player.position or ('P' if player.is_pitcher else '??')
                    label = f"✏️ {player.name} ({pos}) — {team_name}"
                    undo_options[label] = player.player_id

        if undo_options:
            selected_undo_label = st.selectbox("Select Drafted Player to Undo", options=list(undo_options.keys()))

            if st.button("⚠️ Undo Pick", type="secondary"):
                undo_pid = undo_options[selected_undo_label]
                if engine.undo_pick(undo_pid):
                    st.success(f"Undone: {selected_undo_label}")
                    st.session_state.pop('snapshot_availability', None)
                    st.rerun()
                else:
                    st.error("Failed to undo pick. Player may be a keeper or not found.")
        else:
            st.info("No drafted players to undo.")

    # Available Players section with action panel to the left
    st.divider()
    st.subheader("Top Available Players")

    if 'available_players_view' not in st.session_state:
        st.session_state.available_players_view = "Batters"

    view_options = ["Batters", "Pitchers", "All Players"]
    view_option = st.radio("View", view_options, horizontal=True,
                           index=view_options.index(st.session_state.available_players_view))
    st.session_state.available_players_view = view_option

    if view_option == "Batters":
        df_show = engine.bat_df[engine.bat_df['Status'] == 'Available'].copy()
        cols = ['Name', 'POS', 'Team', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'ADP', 'Dollars']
        # Filter to only columns that exist in the DataFrame
        cols = [col for col in cols if col in df_show.columns]
        # Collect unique individual positions from multi-position strings
        all_positions = set()
        for pos in df_show['POS'].dropna().unique():
            for p in str(pos).split('/'):
                all_positions.add(p.strip())
        all_positions = sorted(all_positions)
    elif view_option == "Pitchers":
        df_show = engine.pitch_df[engine.pitch_df['Status'] == 'Available'].copy()
        cols = ['Name', 'POS', 'Team', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS', 'K/9', 'WAR', 'ADP', 'Dollars']
        # Filter to only columns that exist in the DataFrame
        cols = [col for col in cols if col in df_show.columns]
        all_positions = sorted(df_show['POS'].dropna().unique())
    else:
        # All Players: combine batters and pitchers with shared columns
        df_bat = engine.bat_df[engine.bat_df['Status'] == 'Available'].copy()
        df_bat['_is_pitcher'] = False
        df_pitch = engine.pitch_df[engine.pitch_df['Status'] == 'Available'].copy()
        df_pitch['_is_pitcher'] = True
        df_show = pd.concat([df_bat, df_pitch], ignore_index=True)
        cols = ['Name', 'POS', 'Team', 'WAR', 'ADP', 'Dollars']
        cols = [col for col in cols if col in df_show.columns]
        all_positions = set()
        for pos in df_show['POS'].dropna().unique():
            for p in str(pos).split('/'):
                all_positions.add(p.strip())
        all_positions = sorted(all_positions)

    # Position filter and sort controls
    pos_filter_col, sort_col1, sort_col2 = st.columns([2, 2, 1])
    with pos_filter_col:
        pos_filter = st.selectbox("Filter by Position", ["All"] + all_positions, index=0, key="avail_pos_filter")
    if pos_filter != "All":
        df_show = df_show[df_show['POS'].fillna('').apply(lambda x: pos_filter in [p.strip() for p in str(x).split('/')])]

    # Sort controls for the full player pool
    with sort_col1:
        sort_by = st.selectbox("Sort by", cols, index=cols.index('Dollars') if 'Dollars' in cols else 0, key="avail_sort_by")
    with sort_col2:
        sort_order = st.radio("Order", ["Descending", "Ascending"], horizontal=True, key="avail_sort_order")

    df_show = df_show.sort_values(by=sort_by, ascending=(sort_order == "Ascending"), na_position='last')

    total_players = len(df_show)

    # Side-by-side: action panel (left) + player table (right)
    action_col, table_col = st.columns([1, 3])

    with action_col:
        st.markdown("#### Make a Pick")

        # 1. Select Team making the pick (auto-defaults to draft order; override for pick trades)
        _team_list = list(engine.teams.keys())
        _default_team_idx = 0
        if _auto_drafter and _auto_drafter in _team_list:
            _default_team_idx = _team_list.index(_auto_drafter)
        drafting_team = st.selectbox(
            "Drafting Team",
            _team_list,
            index=_default_team_idx,
            help="Auto-set from draft order. Override for mid-draft pick trades.",
        )

        # 2. Display selected player (populated by clicking a row in the table)
        sel = st.session_state.selected_player
        if sel:
            st.info(f"**Selected:** {sel['Name']} ({sel['POS']})")
        else:
            st.caption("Click a player row to select")

        # 3. Action buttons
        draft_btn_col, queue_btn_col = st.columns(2)
        with draft_btn_col:
            if st.button("⚾ Draft Player", type="primary", disabled=(sel is None)):
                engine.process_pick(sel['PlayerId'], drafting_team, sel['is_pitcher'])
                st.toast(f"Drafted {sel['Name']} to {drafting_team}!")
                st.session_state.selected_player = None
                st.session_state.table_key_counter += 1
                st.session_state.pop('snapshot_availability', None)
                st.rerun()
        with queue_btn_col:
            if st.button("📋 Add to Queue", disabled=(sel is None)):
                if not any(q['PlayerId'] == sel['PlayerId'] for q in st.session_state.draft_queue):
                    st.session_state.draft_queue.append(sel.copy())
                    st.toast(f"Added {sel['Name']} to queue!")
                else:
                    st.toast(f"{sel['Name']} is already in the queue.")

        # 4. Draft Queue panel
        if st.session_state.draft_queue:
            st.divider()
            st.subheader("📋 Draft Queue")
            top = st.session_state.draft_queue[0]
            if st.button(f"⚾ Draft #1: {top['Name']}", type="secondary"):
                engine.process_pick(top['PlayerId'], drafting_team, top['is_pitcher'])
                st.toast(f"Drafted {top['Name']} to {drafting_team}!")
                st.session_state.draft_queue.pop(0)
                st.session_state.selected_player = None
                st.session_state.table_key_counter += 1
                st.session_state.pop('snapshot_availability', None)
                st.rerun()
            for i, qp in enumerate(st.session_state.draft_queue):
                dollars_str = f" — ${qp['Dollars']:.0f}" if pd.notna(qp.get('Dollars')) else ""
                qc1, qc2, qc3, qc4 = st.columns([4, 1, 1, 1])
                with qc1:
                    st.text(f"{i + 1}. {qp['Name']} ({qp['POS']}){dollars_str}")
                with qc2:
                    if i > 0 and st.button("⬆️", key=f"q_up_{i}"):
                        st.session_state.draft_queue[i], st.session_state.draft_queue[i - 1] = \
                            st.session_state.draft_queue[i - 1], st.session_state.draft_queue[i]
                        st.rerun()
                with qc3:
                    if i < len(st.session_state.draft_queue) - 1 and st.button("⬇️", key=f"q_down_{i}"):
                        st.session_state.draft_queue[i], st.session_state.draft_queue[i + 1] = \
                            st.session_state.draft_queue[i + 1], st.session_state.draft_queue[i]
                        st.rerun()
                with qc4:
                    if st.button("❌", key=f"q_remove_{i}"):
                        st.session_state.draft_queue.pop(i)
                        st.rerun()

        # 5. Write-in Player
        st.divider()
        st.markdown("#### ✏️ Write-in Player")
        wi_name = st.text_input("Player Name", key="wi_draft_name")
        wi_d1, wi_d2 = st.columns(2)
        with wi_d1:
            wi_pos = st.text_input("Position", key="wi_draft_pos")
        with wi_d2:
            wi_mlb = st.text_input("MLB Team", key="wi_draft_mlb")
        wi_type = st.radio("Type", ["Batter", "Pitcher"], horizontal=True, key="wi_draft_type")
        if st.button("⚾ Draft Write-in", type="secondary"):
            if not wi_name.strip():
                st.error("Player name is required")
            else:
                engine.process_writein(
                    name=wi_name.strip(),
                    team_name=drafting_team,
                    is_pitcher=(wi_type == "Pitcher"),
                    position=wi_pos.strip(),
                    mlb_team=wi_mlb.strip(),
                    status='Drafted',
                )
                st.toast(f"Drafted write-in {wi_name.strip()} to {drafting_team}!")
                st.session_state.selected_player = None
                st.session_state.table_key_counter += 1
                st.session_state.pop('snapshot_availability', None)
                st.rerun()

    with table_col:
        if total_players > 0:
            st.caption(f"{total_players} available players")
            # Add Queued column to indicate players already in the draft queue
            queued_pids = {q['PlayerId'] for q in st.session_state.draft_queue}
            df_show['Queued'] = df_show['PlayerId'].apply(lambda pid: '✅' if pid in queued_pids else '')
            # Add availability probability column if snapshot data exists
            _avail_probs = st.session_state.get('snapshot_availability')
            if _avail_probs:
                df_show['Prob_avail'] = df_show['PlayerId'].apply(
                    lambda pid: round(_avail_probs[pid], 2) if pid in _avail_probs else 0.00
                )
                display_cols = ['Queued', 'Prob_avail'] + cols
            else:
                display_cols = ['Queued'] + cols
            st.dataframe(
                df_show[display_cols],
                hide_index=True,
                height=600,
                selection_mode="single-row",
                on_select="rerun",
                key=_tbl_key,
            )
        else:
            st.info("No available players found.")
            st.session_state.selected_player = None

    # ==========================================
    # SNAPSHOT PROJECTIONS SECTION (tab1)
    # ==========================================
    st.divider()
    st.subheader("📸 Draft Snapshot Projections")
    st.markdown(
        "Run Monte Carlo simulations from the **current draft state** to project "
        "end-of-draft 5×5 category totals for all teams. "
        "The live draft is never modified — all simulations use isolated copies."
    )

    if 'draft_csv' in st.session_state and st.session_state.draft_csv:
        snap_col1, snap_col2 = st.columns([1, 1])

        with snap_col1:
            n_sims = st.number_input(
                "Simulations",
                min_value=10,
                max_value=1000,
                value=50,
                step=10,
                key="snap_n_sims",
                help="Number of Monte Carlo simulations to run (100–1000 recommended).",
            )

        with snap_col2:
            st.write("")
            st.write("")
            run_snapshot = st.button("🔮 Run Snapshot", type="primary", key="run_snapshot_btn")

        auto_pick_index = engine.get_total_picks_made()
        st.caption(f"📍 Auto-detected draft position: {auto_pick_index} picks made")

        if run_snapshot:
            snap_progress = st.progress(0.0, text="Running simulations…")
            snap_start = time.time()

            try:
                def _snap_cb(frac):
                    snap_progress.progress(frac, text=f"Running simulations… {int(frac * n_sims)}/{int(n_sims)}")

                snapshot_results = run_monte_carlo_snapshot(
                    engine=engine,
                    draft_order_csv=st.session_state.draft_csv,
                    n_simulations=int(n_sims),
                    progress_callback=_snap_cb,
                    user_team_name=st.session_state.get('user_team_name'),
                    team_profiles=st.session_state.get('team_profiles') if st.session_state.get('tendencies_enabled') else None,
                )
                snap_elapsed = time.time() - snap_start
                st.session_state.snapshot_results = snapshot_results
                st.session_state.snapshot_elapsed = snap_elapsed
                st.session_state.snapshot_availability = snapshot_results.get('availability_probabilities', {})
                snap_progress.progress(1.0, text="Done!")
                st.rerun()
            except Exception as exc:
                snap_progress.empty()
                st.error(f"❌ Snapshot failed: {exc}")

        # Display results if available
        if 'snapshot_results' in st.session_state and st.session_state.snapshot_results:
            snap_res = st.session_state.snapshot_results
            mean_df = snap_res['mean_standings']
            std_df = snap_res['std_standings']
            elapsed = st.session_state.get('snapshot_elapsed', 0)

            st.caption(
                f"⏱️ Runtime: {elapsed:.1f}s  |  "
                f"{snap_res['n_simulations']} simulations  |  "
                f"Starting from pick #{snap_res['current_pick_index']}"
            )

            # Build heatmap
            teams = mean_df.index.tolist()
            categories = mean_df.columns.tolist()
            n_teams = len(teams)
            lower_is_better = {'ERA', 'WHIP'}

            import numpy as np
            norm_ranks = {}
            for cat in categories:
                vals = mean_df[cat].values.astype(float)
                ranks = np.argsort(np.argsort(vals))  # 0=lowest value
                if cat in lower_is_better:
                    norm_ranks[cat] = (n_teams - 1 - ranks) / max(n_teams - 1, 1)
                else:
                    norm_ranks[cat] = ranks / max(n_teams - 1, 1)

            z_values = [[float(norm_ranks[cat][ti]) for cat in categories] for ti, _ in enumerate(teams)]

            cell_text = []
            for team in teams:
                row = []
                for cat in categories:
                    mv = float(mean_df.loc[team, cat])
                    sv = float(std_df.loc[team, cat])
                    if cat in {'OBP', 'ERA', 'WHIP'}:
                        row.append(f"{mv:.3f}<br>±{sv:.3f}")
                    else:
                        row.append(f"{mv:.0f}<br>±{sv:.0f}")
                cell_text.append(row)

            hover_text = []
            for ti, team in enumerate(teams):
                row = []
                for cat in categories:
                    mv = float(mean_df.loc[team, cat])
                    sv = float(std_df.loc[team, cat])
                    rk = int(round((1 - norm_ranks[cat][ti]) * (n_teams - 1))) + 1
                    row.append(
                        f"<b>{team}</b><br>Category: {cat}<br>"
                        f"Projected: {mv:.2f}<br>Std Dev: {sv:.2f}<br>Rank: {rk}/{n_teams}"
                    )
                hover_text.append(row)

            snap_fig = go.Figure(data=go.Heatmap(
                z=z_values,
                x=categories,
                y=teams,
                colorscale='Viridis',
                zmin=0.0,
                zmax=1.0,
                text=cell_text,
                texttemplate='%{text}',
                hovertext=hover_text,
                hovertemplate='%{hovertext}<extra></extra>',
                showscale=True,
                colorbar=dict(
                    title='Rank',
                    tickvals=[0, 0.5, 1],
                    ticktext=['Last', 'Mid', '1st'],
                ),
            ))
            snap_fig.update_layout(
                title='Projected End-of-Draft Standings — Monte Carlo Snapshot',
                xaxis_title='Category',
                yaxis_title='Team',
                height=max(400, 35 * n_teams + 120),
                template='plotly_white',
                margin=dict(l=120, r=40, t=60, b=40),
            )
            st.plotly_chart(snap_fig, use_container_width=True)
    else:
        st.info("Upload a draft order CSV above to enable the snapshot feature.")

    # ==========================================
    # SAVE DRAFT TO HISTORY SECTION (tab1)
    # ==========================================
    st.divider()
    st.subheader("💾 Save Draft to History")
    st.markdown(
        "One-click save of **draft results**, **keeper assignments**, **draft order**, "
        "and **projection data** to the ``history/`` folder for future reference and tendency analysis."
    )

    _dr_has_drafted = (
        (engine.bat_df['Status'].isin(['Drafted', 'Keeper'])).any()
        or (engine.pitch_df['Status'].isin(['Drafted', 'Keeper'])).any()
    )

    if _dr_has_drafted:
        from datetime import datetime as _dt
        _dr_save_year = st.number_input(
            "Year for this draft",
            min_value=2000,
            max_value=2099,
            value=_dt.now().year,
            key="draft_room_save_year",
        )

        if st.button("💾 Save Draft to History", type="primary", key="draft_room_save_btn"):
            try:
                from src.history_manager import (
                    save_draft_results as _dr_save,
                    build_draft_results_from_engine as _dr_build,
                    collect_projection_files as _dr_collect,
                )

                _dr_csv = st.session_state.get('draft_csv', '')
                _dr_results_df = _dr_build(engine, _dr_csv) if _dr_csv else None

                if _dr_results_df is None or _dr_results_df.empty:
                    st.warning("⚠️ Could not build draft results — upload a draft order CSV first.")
                else:
                    _dr_proj_files = _dr_collect()
                    _dr_save(
                        year=int(_dr_save_year),
                        draft_results=_dr_results_df,
                        draft_order_csv=_dr_csv if _dr_csv else None,
                        keeper_config=engine.export_keeper_config(),
                        projection_files=_dr_proj_files if _dr_proj_files else None,
                    )
                    _proj_msg = f", and {len(_dr_proj_files)} projection files" if _dr_proj_files else ""
                    st.success(
                        f"✅ Draft saved to `history/{_dr_save_year}/`! "
                        f"Includes results, keepers, draft order{_proj_msg}."
                    )
            except Exception as _dr_save_err:
                st.error(f"❌ Error saving draft: {_dr_save_err}")
    else:
        st.info("No draft in progress. Draft or assign keepers first to save results.")


with tab2:
    st.header("Player Value Visualization")
    
    # Controls
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
    
    with col_ctrl1:
        plot_type = st.radio("Player Type", ["Batters", "Pitchers"], horizontal=True)
    
    # Prepare Data based on selection
    if plot_type == "Batters":
        plot_df = engine.bat_df.copy()
        numeric_cols = ['ADP', 'HR', 'RBI', 'R', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'Dollars']
        default_x = 'ADP'
        default_y = 'HR'
    else:
        plot_df = engine.pitch_df.copy()
        numeric_cols = ['ADP', 'ERA', 'WHIP', 'SO', 'SV', 'QS', 'K/9', 'WAR', 'IP', 'Dollars']
        default_x = 'ADP'
        default_y = 'ERA'

    with col_ctrl2:
        x_axis = st.selectbox("X Axis", numeric_cols, index=numeric_cols.index(default_x) if default_x in numeric_cols else 0)
        
    with col_ctrl3:
        y_axis = st.selectbox("Y Axis", numeric_cols, index=numeric_cols.index(default_y) if default_y in numeric_cols else 0)
    
    # Color Logic: Define a map for Status
    # Available = Blue, Drafted = Red (Low opacity)
    color_discrete_map = {'Available': '#1f77b4', 'Drafted': '#d62728'}
    
    # Create the Plotly Figure
    fig = px.scatter(
        plot_df,
        x=x_axis,
        y=y_axis,
        color='Status',
        color_discrete_map=color_discrete_map,
        hover_name='Name',
        hover_data=['Team', 'POS', 'Status'],
        title=f"{y_axis} vs {x_axis} ({plot_type})",
        template="plotly_white",
        height=600
    )
    
    # Customize: Make 'Drafted' dots smaller and transparent so they don't distract
    # We can do this by updating traces
    fig.update_traces(marker=dict(size=10, line=dict(width=1, color='DarkSlateGrey')))
    
    st.plotly_chart(fig, width="stretch")


# ==========================================
# TAB 3: TEAM ROSTERS
# ==========================================
with tab3:
    st.header("Team Rosters")

    # Get all teams sorted by name
    team_names = sorted(engine.teams.keys())

    # Build the roster grid: positions as rows, teams as columns
    from src.models import Team

    # Define row labels in display order (expand multi-slot positions)
    _slot_rows = []
    for slot, limit in Team.SLOT_LIMITS.items():
        if limit > 1:
            for i in range(1, limit + 1):
                _slot_rows.append(f"{slot} {i}")
        else:
            _slot_rows.append(slot)

    # Build grid data: each team is a column, each slot row a cell
    grid_data = {'Slot': _slot_rows}
    for team_name in team_names:
        assignments = engine.get_team_slot_assignments(team_name)
        grid_data[team_name] = [assignments.get(slot, '') for slot in _slot_rows]

    roster_grid_df = pd.DataFrame(grid_data).set_index('Slot')

    # --- Styled roster table with group shading and bold boundaries ---
    # Define logical slot groups for visual separation
    _batter_slots = {'C', '1B', '2B', '3B', 'SS', 'OF 1', 'OF 2', 'OF 3', 'Util 1', 'Util 2'}
    _pitcher_slots = {'SP 1', 'SP 2', 'SP 3', 'RP 1', 'RP 2', 'P'}
    _bench_slots = {f'BN {i}' for i in range(1, 7)}
    # IL/NA slots are the remainder

    def _slot_group(slot):
        if slot in _batter_slots:
            return 'batter'
        elif slot in _pitcher_slots:
            return 'pitcher'
        elif slot in _bench_slots:
            return 'bench'
        return 'reserve'

    _group_colors = {
        'batter': '#e8f4fd',
        'pitcher': '#fce4ec',
        'bench': '#f1f8e9',
        'reserve': '#f5f5f5',
    }

    # Build HTML table
    _html_parts = []
    _html_parts.append('<div style="overflow-x:auto;">')
    _html_parts.append(
        '<table style="width:100%;border-collapse:collapse;font-family:sans-serif;font-size:14px;">'
    )
    # Header row
    _html_parts.append('<thead><tr>')
    _html_parts.append(
        '<th style="padding:10px 12px;text-align:center;font-weight:bold;'
        'border:2px solid #555;background:#37474f;color:#fff;">Slot</th>'
    )
    for tn in team_names:
        _html_parts.append(
            f'<th style="padding:10px 12px;text-align:center;font-weight:bold;'
            f'border:2px solid #555;background:#37474f;color:#fff;">{tn}</th>'
        )
    _html_parts.append('</tr></thead><tbody>')

    # Data rows with group shading and bold group boundaries
    prev_group = None
    for slot in _slot_rows:
        grp = _slot_group(slot)
        bg = _group_colors[grp]
        top_border = '3px solid #333' if prev_group is not None and grp != prev_group else '1px solid #bbb'
        _html_parts.append(f'<tr style="background:{bg};">')
        _html_parts.append(
            f'<td style="padding:6px 10px;text-align:center;font-weight:bold;'
            f'border-left:2px solid #555;border-right:2px solid #555;'
            f'border-top:{top_border};border-bottom:1px solid #bbb;">{slot}</td>'
        )
        for tn in team_names:
            val = roster_grid_df.loc[slot, tn] if slot in roster_grid_df.index else ''
            _html_parts.append(
                f'<td style="padding:6px 10px;text-align:center;'
                f'border-left:2px solid #555;border-right:2px solid #555;'
                f'border-top:{top_border};border-bottom:1px solid #bbb;">{val}</td>'
            )
        _html_parts.append('</tr>')
        prev_group = grp

    _html_parts.append('</tbody></table></div>')
    st.markdown(''.join(_html_parts), unsafe_allow_html=True)


# ==========================================
# TAB 4: DRAFT SIMULATOR
# ==========================================
with tab4:
    st.header("🎲 Draft Simulator")
    st.markdown("Simulate a fantasy draft with probabilistic AI picks. Upload a draft order CSV and watch the simulation unfold!")
    
    # --- SETUP SECTION ---
    st.subheader("⚙️ Setup")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # CSV Upload
        uploaded_file = st.file_uploader(
            "Upload Draft Order CSV",
            type=['csv'],
            help="CSV must have columns: player_name, pick_number (tendency column is optional)"
        )
        
        if uploaded_file is not None:
            # Read CSV content
            csv_content = uploaded_file.getvalue().decode('utf-8')
            
            try:
                # Parse and validate CSV
                from io import StringIO
                draft_df = pd.read_csv(StringIO(csv_content))
                
                st.success("✅ CSV uploaded successfully!")
                
                # Display preview
                with st.expander("📋 Preview Draft Order", expanded=False):
                    st.dataframe(draft_df, hide_index=True, width="stretch")
                    st.caption(f"Total picks: {len(draft_df)}")
                    
                    # Show team summary
                    team_counts = draft_df['player_name'].value_counts()
                    st.caption(f"Teams: {', '.join([f'{team} ({count})' for team, count in team_counts.items()])}")
                
                # Store CSV content in session state
                st.session_state.draft_csv = csv_content
                
            except Exception as e:
                st.error(f"❌ Error parsing CSV: {str(e)}")
                st.session_state.draft_csv = None
    
    with col2:
        st.markdown("**CSV Format Example:**")
        st.code("""player_name,pick_number
Team Alpha,1
Team Beta,2
Team Gamma,3
Team Alpha,4""", language="csv")
        st.caption("💡 Tendency column is optional. Load profiles in the 📊 Player Tendencies tab for data-driven tendencies.")
    
    st.divider()

    # --- PROFILE STATUS INDICATOR ---
    _sim_profiles = st.session_state.get('team_profiles') if st.session_state.get('tendencies_enabled') else None
    if _sim_profiles:
        st.success(f"✅ Tendency profiles active — {len(_sim_profiles)} teams loaded from 📊 Player Tendencies")
    else:
        st.info("ℹ️ No tendency profiles active — using default tendencies. Toggle profiles on in the 📊 Player Tendencies tab.")

    st.divider()

    # Only show rest of UI if CSV is uploaded
    if 'draft_csv' in st.session_state and st.session_state.draft_csv:
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            # Get unique team names from CSV
            from io import StringIO
            draft_df = pd.read_csv(StringIO(st.session_state.draft_csv))
            csv_team_names = sorted(draft_df['player_name'].unique())
            
            user_team = st.selectbox(
                "Your Team Name",
                options=csv_team_names,
                help="Select your team from the draft order"
            )
        
        with col2:
            random_seed = st.number_input(
                "Random Seed (optional)",
                min_value=1,
                max_value=10000,
                value=st.session_state.sim_random_seed,
                help="Set a seed for reproducible simulation results"
            )
        
        with col3:
            st.write("")  # Spacing
            st.write("")  # Spacing
            run_simulation = st.button("▶️ Run Simulation", type="primary", width="stretch")
        
        # Validate keeper team names against draft order CSV team names
        bat_keeper_teams = engine.bat_df.loc[engine.bat_df['Status'] == 'Keeper', 'DraftedBy'].dropna().unique()
        pitch_keeper_teams = engine.pitch_df.loc[engine.pitch_df['Status'] == 'Keeper', 'DraftedBy'].dropna().unique()
        keeper_team_names = set(bat_keeper_teams) | set(pitch_keeper_teams)
        
        if keeper_team_names:
            csv_team_set = set(csv_team_names)
            mismatched_teams = keeper_team_names - csv_team_set
            if mismatched_teams:
                st.warning(
                    f"⚠️ Keeper team names not found in draft order CSV: **{', '.join(sorted(mismatched_teams))}**. "
                    f"Draft order CSV teams: {', '.join(sorted(csv_team_set))}. "
                    f"Please update team names in Pre-Draft Setup or draft order CSV to match."
                )
        
        # Initialize or reset simulator
        if run_simulation:
            try:
                simulator = DraftSimulator(
                    engine=engine,
                    draft_order_csv=st.session_state.draft_csv,
                    user_team_name=user_team,
                    random_seed=random_seed,
                    team_profiles=st.session_state.get('team_profiles') if st.session_state.get('tendencies_enabled') else None,
                )
                st.session_state.simulator = simulator
                st.session_state.simulation_started = True
                st.session_state.sim_draft_queue = []
                st.session_state.sim_selected_player = None
                st.session_state.sim_table_key_counter = 0
                st.session_state.sim_new_picks = []
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error starting simulation: {str(e)}")
        
        # --- SIMULATION SECTION ---
        if 'simulation_started' in st.session_state and st.session_state.simulation_started:
            simulator = st.session_state.simulator

            # Pre-compute sim_selected_player from table selection state
            _sim_view_pre = st.session_state.get('sim_view_option', 'Batters')
            if _sim_view_pre == 'Batters':
                _sim_df_pre = simulator.engine.bat_df[simulator.engine.bat_df['Status'] == 'Available'].copy()
                _sim_pre_cols = ['Name', 'POS', 'Team', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA',
                                 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'ADP', 'Dollars']
            else:
                _sim_df_pre = simulator.engine.pitch_df[simulator.engine.pitch_df['Status'] == 'Available'].copy()
                _sim_pre_cols = ['Name', 'POS', 'Team', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS',
                                 'K/9', 'WAR', 'ADP', 'Dollars']
            _sim_pre_cols = [c for c in _sim_pre_cols if c in _sim_df_pre.columns]
            _sim_pos_pre = st.session_state.get('sim_pos_filter', 'All')
            if _sim_pos_pre and _sim_pos_pre != 'All':
                _sim_df_pre = _sim_df_pre[_sim_df_pre['POS'].fillna('').apply(
                    lambda x: _sim_pos_pre in [p.strip() for p in str(x).split('/')])]
            _sim_sort_by_pre = st.session_state.get('sim_sort_by', 'Dollars')
            _sim_sort_order_pre = st.session_state.get('sim_sort_order', 'Descending')
            if _sim_sort_by_pre and _sim_sort_by_pre in _sim_df_pre.columns:
                _sim_df_pre = _sim_df_pre.sort_values(
                    by=_sim_sort_by_pre, ascending=(_sim_sort_order_pre == 'Ascending'), na_position='last')
            _sim_tbl_key = f"sim_available_players_table_{st.session_state.sim_table_key_counter}"
            _sim_tbl_state = st.session_state.get(_sim_tbl_key)
            if _sim_tbl_state is not None and hasattr(_sim_tbl_state, 'selection') and _sim_tbl_state.selection.rows:
                _sim_ridx = _sim_tbl_state.selection.rows[0]
                if _sim_ridx < len(_sim_df_pre):
                    _sim_r = _sim_df_pre.iloc[_sim_ridx]
                    _sim_dollars = _sim_r.get('Dollars') if 'Dollars' in _sim_df_pre.columns else None
                    st.session_state.sim_selected_player = {
                        'PlayerId': _sim_r['PlayerId'],
                        'Name': _sim_r['Name'],
                        'POS': _sim_r['POS'],
                        'is_pitcher': (_sim_view_pre == 'Pitchers'),
                        'Dollars': float(_sim_dollars) if _sim_dollars is not None and not pd.isna(_sim_dollars) else None,
                    }
                else:
                    st.session_state.sim_selected_player = None
            elif _sim_tbl_state is not None:
                st.session_state.sim_selected_player = None

            st.divider()
            st.subheader("🎯 Simulation Progress")

            # Run simulation until user's turn or completion
            if not simulator.simulation_complete and not simulator.is_paused:
                new_picks = simulator.simulate_until_user_or_complete()
                st.session_state.sim_new_picks = new_picks

            # Show current pick status
            if simulator.simulation_complete:
                st.success("🎉 Simulation Complete!")
            elif simulator.is_user_turn():
                st.info("🎯 **YOUR PICK!** Click a player row below to select, then draft.")
            else:
                st.info(f"Pick {simulator.current_pick_index + 1} / {len(simulator.draft_order)}")

            # Top Row: Standings and Pick Log
            sim_top_col1, sim_top_col2 = st.columns([2, 1])

            with sim_top_col1:
                st.header("📊 Current Standings")
                standings = simulator.get_standings()
                st.dataframe(standings, hide_index=True, width="stretch")

            with sim_top_col2:
                st.header("📜 Pick Log")
                if simulator.pick_log:
                    recent_picks = simulator.pick_log[-10:]
                    for pick in reversed(recent_picks):
                        player_type = "⚾" if not pick['is_pitcher'] else "🥎"
                        st.text(f"#{pick['pick_number']}: {pick['team_name']} — {player_type} {pick['player_name']} ({pick['position']})")
                    if len(simulator.pick_log) > 10:
                        with st.expander(f"📋 View All {len(simulator.pick_log)} Picks"):
                            for pick in reversed(simulator.pick_log):
                                st.text(f"#{pick['pick_number']}: {pick['team_name']} - {pick['player_name']} ({pick['position']}) - {pick['rationale']}")
                else:
                    st.info("No picks yet.")

            # --- SIMULATED PICKS ---
            if st.session_state.sim_new_picks:
                st.divider()
                st.subheader("🤖 Simulated Picks")
                for pick in st.session_state.sim_new_picks:
                    col1, col2, col3, col4 = st.columns([1, 2, 3, 4])
                    with col1:
                        st.text(f"#{pick['pick_number']}")
                    with col2:
                        st.text(pick['team_name'])
                    with col3:
                        player_type = "⚾" if not pick['is_pitcher'] else "🥎"
                        st.text(f"{player_type} {pick['player_name']} ({pick['position']})")
                    with col4:
                        st.caption(pick['rationale'])

            # Available Players section with action panel to the left
            st.divider()
            st.subheader("Top Available Players")

            if 'sim_view_option' not in st.session_state:
                st.session_state.sim_view_option = "Batters"

            sim_view_option = st.radio("View", ["Batters", "Pitchers"], horizontal=True, key="sim_view_option")

            if sim_view_option == "Batters":
                sim_df_show = simulator.engine.bat_df[simulator.engine.bat_df['Status'] == 'Available'].copy()
                sim_cols = ['Name', 'POS', 'Team', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'ADP', 'Dollars']
                sim_cols = [col for col in sim_cols if col in sim_df_show.columns]
                sim_all_positions = set()
                for pos in sim_df_show['POS'].dropna().unique():
                    for p in str(pos).split('/'):
                        sim_all_positions.add(p.strip())
                sim_all_positions = sorted(sim_all_positions)
            else:
                sim_df_show = simulator.engine.pitch_df[simulator.engine.pitch_df['Status'] == 'Available'].copy()
                sim_cols = ['Name', 'POS', 'Team', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'QS', 'K/9', 'WAR', 'ADP', 'Dollars']
                sim_cols = [col for col in sim_cols if col in sim_df_show.columns]
                sim_all_positions = sorted(sim_df_show['POS'].dropna().unique())

            # Position filter and sort controls
            sim_pos_filter_col, sim_sort_col1, sim_sort_col2 = st.columns([2, 2, 1])
            with sim_pos_filter_col:
                sim_pos_filter = st.selectbox("Filter by Position", ["All"] + sim_all_positions, index=0, key="sim_pos_filter")
            if sim_pos_filter != "All":
                sim_df_show = sim_df_show[sim_df_show['POS'].fillna('').apply(lambda x: sim_pos_filter in [p.strip() for p in str(x).split('/')])]

            with sim_sort_col1:
                sim_sort_by = st.selectbox("Sort by", sim_cols, index=sim_cols.index('Dollars') if 'Dollars' in sim_cols else 0, key="sim_sort_by")
            with sim_sort_col2:
                sim_sort_order = st.radio("Order", ["Descending", "Ascending"], horizontal=True, key="sim_sort_order")

            sim_df_show = sim_df_show.sort_values(by=sim_sort_by, ascending=(sim_sort_order == "Ascending"), na_position='last')

            sim_total_players = len(sim_df_show)

            # Side-by-side: action panel (left) + player table (right)
            sim_action_col, sim_table_col = st.columns([1, 3])

            with sim_action_col:
                if simulator.is_user_turn() and not simulator.simulation_complete:
                    st.markdown("#### Make a Pick")

                    # Display selected player (populated by clicking a row in the table)
                    sim_sel = st.session_state.sim_selected_player
                    if sim_sel:
                        st.info(f"**Selected:** {sim_sel['Name']} ({sim_sel['POS']})")
                    else:
                        st.caption("Click a player row to select")

                    # Action buttons
                    sim_draft_btn_col, sim_queue_btn_col = st.columns(2)
                    with sim_draft_btn_col:
                        if st.button("⚾ Draft Player", type="primary", disabled=(sim_sel is None), key="sim_draft_btn"):
                            if simulator.make_user_pick(sim_sel['PlayerId'], sim_sel['is_pitcher']):
                                st.toast(f"Drafted {sim_sel['Name']}!")
                                st.session_state.sim_selected_player = None
                                st.session_state.sim_table_key_counter += 1
                                st.rerun()
                            else:
                                st.error("Failed to process pick")
                    with sim_queue_btn_col:
                        if st.button("📋 Add to Queue", disabled=(sim_sel is None), key="sim_queue_btn"):
                            if not any(q['PlayerId'] == sim_sel['PlayerId'] for q in st.session_state.sim_draft_queue):
                                st.session_state.sim_draft_queue.append(sim_sel.copy())
                                st.toast(f"Added {sim_sel['Name']} to queue!")
                            else:
                                st.toast(f"{sim_sel['Name']} is already in the queue.")

                    # Draft Queue panel
                    if st.session_state.sim_draft_queue:
                        st.divider()
                        st.subheader("📋 Draft Queue")
                        sim_top_q = st.session_state.sim_draft_queue[0]
                        if st.button(f"⚾ Draft #1: {sim_top_q['Name']}", type="secondary", key="sim_draft_q_top"):
                            if simulator.make_user_pick(sim_top_q['PlayerId'], sim_top_q['is_pitcher']):
                                st.toast(f"Drafted {sim_top_q['Name']}!")
                                st.session_state.sim_draft_queue.pop(0)
                                st.session_state.sim_selected_player = None
                                st.session_state.sim_table_key_counter += 1
                                st.rerun()
                            else:
                                st.error("Failed to process pick")
                        for i, qp in enumerate(st.session_state.sim_draft_queue):
                            dollars_str = f" — ${qp['Dollars']:.0f}" if pd.notna(qp.get('Dollars')) else ""
                            qc1, qc2, qc3, qc4 = st.columns([4, 1, 1, 1])
                            with qc1:
                                st.text(f"{i + 1}. {qp['Name']} ({qp['POS']}){dollars_str}")
                            with qc2:
                                if i > 0 and st.button("⬆️", key=f"sim_q_up_{i}"):
                                    st.session_state.sim_draft_queue[i], st.session_state.sim_draft_queue[i - 1] = \
                                        st.session_state.sim_draft_queue[i - 1], st.session_state.sim_draft_queue[i]
                                    st.rerun()
                            with qc3:
                                if i < len(st.session_state.sim_draft_queue) - 1 and st.button("⬇️", key=f"sim_q_down_{i}"):
                                    st.session_state.sim_draft_queue[i], st.session_state.sim_draft_queue[i + 1] = \
                                        st.session_state.sim_draft_queue[i + 1], st.session_state.sim_draft_queue[i]
                                    st.rerun()
                            with qc4:
                                if st.button("❌", key=f"sim_q_remove_{i}"):
                                    st.session_state.sim_draft_queue.pop(i)
                                    st.rerun()
                elif not simulator.simulation_complete:
                    st.caption("Waiting for your turn...")
                    if st.session_state.sim_draft_queue:
                        st.divider()
                        st.subheader("📋 Draft Queue")
                        for i, qp in enumerate(st.session_state.sim_draft_queue):
                            dollars_str = f" — ${qp['Dollars']:.0f}" if pd.notna(qp.get('Dollars')) else ""
                            st.text(f"{i + 1}. {qp['Name']} ({qp['POS']}){dollars_str}")

            with sim_table_col:
                if sim_total_players > 0:
                    st.caption(f"{sim_total_players} available players")
                    # Add Queued column to indicate players already in the draft queue
                    sim_queued_pids = {q['PlayerId'] for q in st.session_state.sim_draft_queue}
                    sim_df_show['Queued'] = sim_df_show['PlayerId'].apply(lambda pid: '✅' if pid in sim_queued_pids else '')
                    sim_display_cols = ['Queued'] + sim_cols
                    st.dataframe(
                        sim_df_show[sim_display_cols],
                        hide_index=True,
                        height=600,
                        selection_mode="single-row",
                        on_select="rerun",
                        key=_sim_tbl_key,
                    )
                else:
                    st.info("No available players found.")
                    st.session_state.sim_selected_player = None

            # --- TEAM ROSTERS ---
            st.divider()
            st.subheader("👥 Team Rosters")
            
            sim_roster_view_mode = st.radio("View Mode", ["All Teams", "Single Team"], horizontal=True, key="sim_roster_view_mode")
            
            sim_team_names = sorted(simulator.engine.teams.keys())
            
            sim_selected_team = None
            if sim_roster_view_mode == "Single Team":
                sim_selected_team = st.selectbox("Select Team", sim_team_names, key="sim_roster_team")
            
            for sim_team_name in sim_team_names:
                sim_roster_df = simulator.engine.get_team_roster_df(sim_team_name)
                sim_player_count = len(sim_roster_df)
                
                sim_is_expanded = False
                if sim_roster_view_mode == "Single Team" and sim_team_name == sim_selected_team:
                    sim_is_expanded = True
                
                with st.expander(f"**{sim_team_name}** — {sim_player_count} players", expanded=sim_is_expanded):
                    if sim_roster_df.empty:
                        st.info("No players drafted yet.")
                    else:
                        sim_summary = simulator.engine.get_roster_summary(sim_team_name)
                        
                        st.markdown("**Roster Slot Summary**")
                        scol1, scol2, scol3 = st.columns(3)
                        
                        with scol1:
                            st.markdown("**Batting Slots**")
                            for slot in ['C', '1B', '2B', '3B', 'SS', 'OF', 'Util']:
                                filled = sim_summary[slot]['filled']
                                limit = sim_summary[slot]['limit']
                                st.text(f"{slot}: {filled}/{limit}")
                        
                        with scol2:
                            st.markdown("**Pitching Slots**")
                            for slot in ['SP', 'RP', 'P']:
                                filled = sim_summary[slot]['filled']
                                limit = sim_summary[slot]['limit']
                                st.text(f"{slot}: {filled}/{limit}")
                        
                        with scol3:
                            st.markdown("**Bench / Reserve**")
                            for slot in ['BN', 'IL', 'NA']:
                                filled = sim_summary[slot]['filled']
                                limit = sim_summary[slot]['limit']
                                st.text(f"{slot}: {filled}/{limit}")
                        
                        st.divider()
                        
                        st.markdown("**Roster Table**")
                        rcol_left, rcol_right = st.columns(2)
                        
                        with rcol_left:
                            st.markdown("**Batters**")
                            sim_batters = sim_roster_df[sim_roster_df['Type'] == 'Batter']
                            if sim_batters.empty:
                                st.caption("None drafted.")
                            else:
                                st.dataframe(
                                    sim_batters[['Name', 'POS', 'MLB Team', 'Dollars']],
                                    hide_index=True,
                                    width="stretch"
                                )
                        
                        with rcol_right:
                            st.markdown("**Pitchers**")
                            sim_pitchers = sim_roster_df[sim_roster_df['Type'] == 'Pitcher']
                            if sim_pitchers.empty:
                                st.caption("None drafted.")
                            else:
                                st.dataframe(
                                    sim_pitchers[['Name', 'POS', 'MLB Team', 'Dollars']],
                                    hide_index=True,
                                    width="stretch"
                                )
            
            # --- PLAYER VALUE VISUALIZATION ---
            st.divider()
            st.subheader("Player Value Visualization")
            
            col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
            
            with col_ctrl1:
                sim_plot_type = st.radio("Player Type", ["Batters", "Pitchers"], horizontal=True, key="sim_plot_type")
            
            if sim_plot_type == "Batters":
                sim_plot_df = simulator.engine.bat_df.copy()
                sim_numeric_cols = ['ADP', 'HR', 'RBI', 'R', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'Dollars']
                sim_default_x = 'ADP'
                sim_default_y = 'HR'
            else:
                sim_plot_df = simulator.engine.pitch_df.copy()
                sim_numeric_cols = ['ADP', 'ERA', 'WHIP', 'SO', 'SV', 'QS', 'K/9', 'WAR', 'IP', 'Dollars']
                sim_default_x = 'ADP'
                sim_default_y = 'ERA'
            
            sim_numeric_cols = [col for col in sim_numeric_cols if col in sim_plot_df.columns]
            
            with col_ctrl2:
                sim_x_axis = st.selectbox("X Axis", sim_numeric_cols, index=sim_numeric_cols.index(sim_default_x) if sim_default_x in sim_numeric_cols else 0, key="sim_x_axis")
            
            with col_ctrl3:
                sim_y_axis = st.selectbox("Y Axis", sim_numeric_cols, index=sim_numeric_cols.index(sim_default_y) if sim_default_y in sim_numeric_cols else 0, key="sim_y_axis")
            
            sim_color_map = {'Available': '#1f77b4', 'Drafted': '#d62728', 'Keeper': '#2ca02c'}
            
            sim_fig = px.scatter(
                sim_plot_df,
                x=sim_x_axis,
                y=sim_y_axis,
                color='Status',
                color_discrete_map=sim_color_map,
                hover_name='Name',
                hover_data=['Team', 'POS', 'Status'],
                title=f"{sim_y_axis} vs {sim_x_axis} ({sim_plot_type})",
                template="plotly_white",
                height=600
            )
            
            sim_fig.update_traces(marker=dict(size=10, line=dict(width=1, color='DarkSlateGrey')))
            
            st.plotly_chart(sim_fig, use_container_width=True)
            
            # --- FINAL RESULTS ---
            if simulator.simulation_complete:
                st.divider()
                st.subheader("🏆 Final Rosters")
                
                team_names = sorted(simulator.engine.teams.keys())
                
                for team_name in team_names:
                    roster_df = simulator.get_team_roster(team_name)
                    
                    with st.expander(f"**{team_name}** — {len(roster_df)} players"):
                        if not roster_df.empty:
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.markdown("**Batters**")
                                batters = roster_df[roster_df['Type'] == 'Batter']
                                if not batters.empty:
                                    st.dataframe(batters[['Name', 'POS', 'Dollars']], hide_index=True, width="stretch")
                                else:
                                    st.caption("None")
                            
                            with col2:
                                st.markdown("**Pitchers**")
                                pitchers = roster_df[roster_df['Type'] == 'Pitcher']
                                if not pitchers.empty:
                                    st.dataframe(pitchers[['Name', 'POS', 'Dollars']], hide_index=True, width="stretch")
                                else:
                                    st.caption("None")
                        else:
                            st.info("No players drafted")
                
                # Reset button
                if st.button("🔄 Reset Simulator"):
                    if 'simulator' in st.session_state:
                        del st.session_state.simulator
                    if 'simulation_started' in st.session_state:
                        del st.session_state.simulation_started
                    st.session_state.sim_draft_queue = []
                    st.session_state.sim_selected_player = None
                    st.session_state.sim_table_key_counter = 0
                    st.session_state.sim_new_picks = []
                    st.rerun()
    else:
        st.info("👆 Upload a draft order CSV to begin")

# ==========================================
# TAB 5: PLAYER TENDENCIES
# ==========================================
with tab5:
    st.header("📊 Player Tendencies")
    st.markdown("""**Follow these steps to set up data-driven draft tendencies:**

1. **Upload historical draft CSVs** — Upload one or more past draft result files and assign each a year.
2. **Run the Evaluator** — Select the years to analyze and click **Run Evaluation** to generate tendency and chaos scores.
3. **Save Profiles** — After evaluation, click **Save Profiles** to write results to `profiles/tendencies.json`. Profiles are automatically activated across all tabs.
4. **Toggle Profiles** — Use the toggle below to enable or disable tendency profiles. Profiles from `profiles/tendencies.json` are loaded automatically on startup.
""")

    # --- Section 1: Upload Historical Drafts ---
    st.subheader("📁 Upload Historical Drafts")
    _hist_col1, _hist_col2 = st.columns([2, 1])
    with _hist_col1:
        _hist_file = st.file_uploader(
            "Upload draft_results.csv",
            type=['csv'],
            key="tendency_hist_upload",
            help="Upload a historical draft results CSV file.",
        )
        _hist_year = st.number_input("Year", min_value=2000, max_value=2099, value=2024, key="tendency_hist_year")
        if st.button("📤 Upload Historical Data", key="tendency_upload_btn"):
            if _hist_file is not None:
                try:
                    from src.history_manager import save_draft_results
                    import pandas as _hist_pd
                    from io import StringIO as _HistSIO
                    _hist_df = _hist_pd.read_csv(_HistSIO(_hist_file.getvalue().decode('utf-8')))
                    save_draft_results(year=int(_hist_year), draft_results=_hist_df)
                    st.success(f"✅ Saved historical draft data for {_hist_year}.")
                except Exception as _hist_err:
                    st.error(f"❌ Error saving historical data: {_hist_err}")
            else:
                st.warning("Please upload a CSV file first.")

    with _hist_col2:
        try:
            from src.history_manager import list_available_years
            _avail_years = list_available_years()
            if _avail_years:
                st.markdown("**Available Years:**")
                st.write(", ".join(str(y) for y in sorted(_avail_years)))
            else:
                st.info("No historical data uploaded yet.")
        except Exception:
            st.info("No historical data available.")

    st.divider()

    # --- Section 2: Run Evaluator ---
    st.subheader("🔬 Run Evaluator")
    try:
        from src.history_manager import list_available_years as _list_years
        _eval_years = _list_years()
    except Exception:
        _eval_years = []

    if _eval_years:
        _selected_years = st.multiselect("Select years to analyze", options=sorted(_eval_years), default=sorted(_eval_years), key="tendency_eval_years")
        if st.button("🔍 Run Evaluation", key="tendency_eval_btn"):
            if _selected_years:
                try:
                    from src.tendency_evaluator import evaluate_all_teams
                    _eval_results = evaluate_all_teams(years=_selected_years)
                    st.session_state.tendency_eval_results = _eval_results
                except Exception as _eval_err:
                    st.error(f"❌ Error running evaluation: {_eval_err}")
            else:
                st.warning("Please select at least one year.")
    else:
        st.info("Upload historical draft data first to run the evaluator.")

    # Display previously computed results if available
    if 'tendency_eval_results' in st.session_state and st.session_state.tendency_eval_results:
        _prev_results = st.session_state.tendency_eval_results
        _prev_rows = []
        for profile in _prev_results:
            _prev_rows.append({
                'Team': profile.get('team_name', '?'),
                'Tendency': round(profile.get('tendency', 0), 3),
                'Tendency Label': profile.get('tendency_label', 'balanced'),
                'Chaos Score (1-10)': profile.get('chaos_score', '?'),
                'Chaos Raw': round(profile.get('chaos_raw', 0), 3),
            })
        if _prev_rows:
            st.markdown("**Last Evaluation Results:**")
            st.dataframe(pd.DataFrame(_prev_rows), hide_index=True)

        if st.button("💾 Save Profiles", key="tendency_save_btn"):
            try:
                from src.tendency_evaluator import save_profiles
                save_profiles(_prev_results)
                st.session_state.team_profiles = {p["team_name"]: p for p in _prev_results}
                st.session_state.tendencies_enabled = True
                st.success("✅ Profiles saved and activated across all tabs.")
            except Exception as _save_err:
                st.error(f"❌ Error saving profiles: {_save_err}")

    st.divider()

    # --- Section 3: Save Current Draft ---
    st.subheader("💾 Save Current Draft to History")
    _has_drafted = (
        (engine.bat_df['Status'].isin(['Drafted', 'Keeper'])).any()
        or (engine.pitch_df['Status'].isin(['Drafted', 'Keeper'])).any()
    )
    if _has_drafted:
        _save_year = st.number_input("Year for this draft", min_value=2000, max_value=2099, value=2025, key="tendency_save_year")
        if st.button("💾 Save Draft to History", key="tendency_save_draft_btn"):
            try:
                from src.history_manager import save_draft_results, build_draft_results_from_engine
                _draft_results_df = build_draft_results_from_engine(engine, st.session_state.get('draft_csv', ''))
                save_draft_results(
                    year=int(_save_year),
                    draft_results=_draft_results_df,
                    draft_order_csv=st.session_state.get('draft_csv'),
                    keeper_config=engine.export_keeper_config(),
                )
                st.success(f"✅ Current draft saved to history for {_save_year}.")
            except Exception as _save_draft_err:
                st.error(f"❌ Error saving draft: {_save_draft_err}")
    else:
        st.info("No draft in progress. Draft or assign keepers first to save results.")

    st.divider()

    # --- Section 4: Toggle & View Profiles ---
    st.subheader("📂 Tendency Profiles")
    _has_profiles = bool(st.session_state.get('team_profiles'))
    if _has_profiles:
        _toggle_val = st.toggle(
            "Enable tendency profiles",
            value=st.session_state.get('tendencies_enabled', False),
            key="tendencies_toggle",
            help="When enabled, loaded tendency profiles are used across the Draft Room, Draft Simulator, and Snapshot Projections.",
        )
        st.session_state.tendencies_enabled = _toggle_val
        if _toggle_val:
            st.success(f"✅ Tendency profiles **enabled** — {len(st.session_state.team_profiles)} teams loaded.")
        else:
            st.info("ℹ️ Tendency profiles **disabled** — using default tendencies.")
    else:
        st.info("No profiles available. Run the evaluator and save profiles, or place a `tendencies.json` file in the `profiles/` folder.")

    if _has_profiles:
        st.markdown("**Loaded Team Profiles:**")
        _profile_rows = []
        for team, profile in st.session_state.team_profiles.items():
            _profile_rows.append({
                'Team': team,
                'Tendency': round(profile.get('tendency', 0), 3),
                'Tendency Label': profile.get('tendency_label', 'balanced'),
                'Chaos Score': profile.get('chaos_score', '?'),
            })
        st.dataframe(pd.DataFrame(_profile_rows), hide_index=True)
        st.caption("Toggle the switch above to enable or disable these profiles across all tabs — the ⚾ Draft Room, the 🎲 Draft Simulator, and Snapshot Projections.")