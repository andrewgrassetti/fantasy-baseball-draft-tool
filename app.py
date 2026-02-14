import streamlit as st
import plotly.express as px
from src.data_loader import load_and_merge_data
from src.draft_engine import DraftEngine
from src.persistence import save_keeper_config, load_keeper_config, list_saved_configs, delete_keeper_config

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

# --- TABS ---
tab0, tab1, tab2, tab3 = st.tabs(["⚙️ Pre-Draft Setup", "⚾ Draft Room", "📊 Market Analysis", "👥 Team Rosters"])

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
                if engine.process_keeper(pid, keeper_team, cost=keeper_cost):
                    st.success(f"Added {selected_keeper_label} to {keeper_team}")
                    st.rerun()
                else:
                    st.error("Failed to add keeper")
        else:
            st.info("All players have been assigned. No available players remaining.")
    
    with col2:
        st.markdown("**Current Keepers**")
        
        # Get all keepers from all teams
        all_keepers = []
        for team_name, team in engine.teams.items():
            for player in team.roster:
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
                    for keeper in team_keepers:
                        col_a, col_b = st.columns([3, 1])
                        with col_a:
                            st.text(f"{keeper['Player']} ({keeper['Position']}) - ${keeper['Cost']:.0f}")
                        with col_b:
                            player_type = "P" if keeper['is_pitcher'] else "B"
                            if st.button("Remove", key=f"remove_{keeper['ID']}_{player_type}_{keeper['Team']}"):
                                if engine.remove_keeper(keeper['ID']):
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
                display_name = f"{cfg['name']} ({created_date})"
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
    # Top Row: Input and Standings
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.header("Make a Pick")
        
        # 1. Select Team making the pick
        drafting_team = st.selectbox("Drafting Team", list(engine.teams.keys()))
        
        # 2. Search Player
        # Combine Batters and Pitchers for search
        # Filter only Available players for the dropdown to reduce clutter
        avail_bat = engine.bat_df[engine.bat_df['Status'] == 'Available']
        avail_pitch = engine.pitch_df[engine.pitch_df['Status'] == 'Available']
        
        # Create a display string: "Name (POS) - Team"
        search_options = {} # Map "Display Name" -> (ID, IsPitcher)
        
        for _, row in avail_bat.iterrows():
            label = f"{row['Name']} ({row['POS']})"
            search_options[label] = (row['PlayerId'], False)
            
        for _, row in avail_pitch.iterrows():
            label = f"{row['Name']} (P) - {row['Team']}"
            search_options[label] = (row['PlayerId'], True)
            
        selected_label = st.selectbox("Select Player", options=list(search_options.keys()))
        
        if st.button("Confirm Pick", type="primary"):
            pid, is_pitcher = search_options[selected_label]
            engine.process_pick(pid, drafting_team, is_pitcher)
            st.success(f"Drafted {selected_label} to {drafting_team}")
            st.rerun()
        
        # --- UNDO PICK SECTION ---
        st.divider()
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
        
        if undo_options:
            selected_undo_label = st.selectbox("Select Drafted Player to Undo", options=list(undo_options.keys()))
            
            if st.button("⚠️ Undo Pick", type="secondary"):
                undo_pid = undo_options[selected_undo_label]
                if engine.undo_pick(undo_pid):
                    st.success(f"Undone: {selected_undo_label}")
                    st.rerun()
                else:
                    st.error("Failed to undo pick. Player may be a keeper or not found.")
        else:
            st.info("No drafted players to undo.")

    with col2:
        st.header("Live Standings (5x5)")
        standings = engine.get_standings()
        st.dataframe(standings, hide_index=True, use_container_width=True)

    # Bottom Row: Available Players List
    st.divider()
    st.subheader("Top Available Players")
    
    view_option = st.radio("View", ["Batters", "Pitchers"], horizontal=True)
    
    if view_option == "Batters":
        df_show = engine.bat_df[engine.bat_df['Status'] == 'Available'].copy()
        cols = ['Name', 'POS', 'Team', 'R', 'HR', 'RBI', 'SB', 'OBP', 'wOBA', 'WAR', 'wRC+', 'maxEV', 'Barrel_prc', 'ADP', 'Dollars']
        # Filter to only columns that exist in the DataFrame
        cols = [col for col in cols if col in df_show.columns]
    else:
        df_show = engine.pitch_df[engine.pitch_df['Status'] == 'Available'].copy()
        cols = ['Name', 'POS', 'Team', 'IP', 'SO', 'ERA', 'WHIP', 'SV', 'K/9', 'WAR', 'ADP', 'Dollars']
        # Filter to only columns that exist in the DataFrame
        cols = [col for col in cols if col in df_show.columns]
    
    # Sort by Dollars (auction value) descending
    df_show = df_show.sort_values(by='Dollars', ascending=False)
    
    # Pagination: 50 players per page
    players_per_page = 50
    total_players = len(df_show)
    total_pages = (total_players + players_per_page - 1) // players_per_page  # Ceiling division
    
    if total_pages > 0:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
        start_idx = (page - 1) * players_per_page
        end_idx = min(start_idx + players_per_page, total_players)
        
        st.caption(f"Showing {start_idx + 1}–{end_idx} of {total_players} players")
        st.dataframe(df_show[cols].iloc[start_idx:end_idx], hide_index=True)
    else:
        st.info("No available players found.")


# ==========================================
# TAB 2: MARKET ANALYSIS (THE PLOTS)
# ==========================================
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
        numeric_cols = ['ADP', 'ERA', 'WHIP', 'SO', 'SV', 'K/9', 'WAR', 'IP', 'Dollars']
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
    
    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# TAB 3: TEAM ROSTERS
# ==========================================
with tab3:
    st.header("Team Rosters")
    
    # View Mode Selection
    view_mode = st.radio("View Mode", ["All Teams", "Single Team"], horizontal=True)
    
    # Get all teams sorted by name
    team_names = sorted(engine.teams.keys())
    
    # Single Team Mode: Show dropdown
    selected_team = None
    if view_mode == "Single Team":
        selected_team = st.selectbox("Select Team", team_names)
    
    # Display Teams
    for team_name in team_names:
        # Get roster data
        roster_df = engine.get_team_roster_df(team_name)
        player_count = len(roster_df)
        
        # Determine if expander should be expanded
        is_expanded = False
        if view_mode == "Single Team" and team_name == selected_team:
            is_expanded = True
        
        # Create expander with team name and player count
        with st.expander(f"**{team_name}** — {player_count} players", expanded=is_expanded):
            if roster_df.empty:
                st.info("No players drafted yet.")
            else:
                # Get roster summary
                summary = engine.get_roster_summary(team_name)
                
                # Display Roster Slot Summary in 3 columns
                st.subheader("Roster Slot Summary")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("**Batting Slots**")
                    for slot in ['C', '1B', '2B', '3B', 'SS', 'OF', 'Util']:
                        filled = summary[slot]['filled']
                        limit = summary[slot]['limit']
                        st.text(f"{slot}: {filled}/{limit}")
                
                with col2:
                    st.markdown("**Pitching Slots**")
                    for slot in ['SP', 'RP', 'P']:
                        filled = summary[slot]['filled']
                        limit = summary[slot]['limit']
                        st.text(f"{slot}: {filled}/{limit}")
                
                with col3:
                    st.markdown("**Bench / Reserve**")
                    for slot in ['BN', 'IL', 'NA']:
                        filled = summary[slot]['filled']
                        limit = summary[slot]['limit']
                        st.text(f"{slot}: {filled}/{limit}")
                
                st.divider()
                
                # Display Roster Table split by Batters/Pitchers
                st.subheader("Roster Table")
                col_left, col_right = st.columns(2)
                
                with col_left:
                    st.markdown("**Batters**")
                    batters = roster_df[roster_df['Type'] == 'Batter']
                    if batters.empty:
                        st.caption("None drafted.")
                    else:
                        # Display without the Type column
                        st.dataframe(
                            batters[['Name', 'POS', 'MLB Team', 'Dollars']], 
                            hide_index=True,
                            use_container_width=True
                        )
                
                with col_right:
                    st.markdown("**Pitchers**")
                    pitchers = roster_df[roster_df['Type'] == 'Pitcher']
                    if pitchers.empty:
                        st.caption("None drafted.")
                    else:
                        # Display without the Type column
                        st.dataframe(
                            pitchers[['Name', 'POS', 'MLB Team', 'Dollars']], 
                            hide_index=True,
                            use_container_width=True
                        )