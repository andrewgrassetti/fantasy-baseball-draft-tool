"""
Draft Simulator Module

Provides probabilistic draft simulation functionality that:
- Accepts CSV-based draft order with team tendencies
- Pauses for user picks
- Auto-picks for AI teams using weighted random selection based on:
  1. Dollar value ranking (DOMINANT weight)
  2. Positional need (SECONDARY weight - distant second to value)
  3. Category need (LOW weight)
  4. Player tendency (LOW weight)
"""

import pandas as pd
import numpy as np
import copy
from typing import Dict, List, Tuple, Optional
from .models import Team, Player
from .draft_engine import DraftEngine


class DraftSimulator:
    """Simulates a fantasy baseball draft with probabilistic AI picks."""
    
    # Scoring weights for pick selection
    WEIGHT_MARKET_VALUE = 5.0          # DOMINANT weight - dollar value is king
    WEIGHT_POSITIONAL_NEED = 0.5       # SECONDARY weight - distant second
    WEIGHT_CATEGORY_NEED = 0.1         # LOW weight
    WEIGHT_TENDENCY = 0.1              # LOW weight
    
    # Small epsilon to ensure every player has nonzero selection probability
    EPSILON = 0.01
    
    # Maximum number of top players (by Dollar value) to consider per pick
    TOP_N_PLAYERS = 500
    
    def __init__(self, engine: DraftEngine, draft_order_csv: str, user_team_name: str, random_seed: Optional[int] = None):
        """Initialize the draft simulator.
        
        Args:
            engine: The DraftEngine instance (will be deep copied)
            draft_order_csv: Path to CSV or CSV content as string
            user_team_name: Name of the user's team (must match CSV)
            random_seed: Optional random seed for reproducibility
        """
        # Deep copy the engine to avoid mutating the main draft state
        self.engine = self._deep_copy_engine(engine)
        
        # Parse draft order
        self.draft_order = self._parse_draft_order(draft_order_csv)
        self.user_team_name = user_team_name
        
        # Validate user team name exists in draft order
        team_names_in_order = self.draft_order['player_name'].unique()
        if user_team_name not in team_names_in_order:
            raise ValueError(f"User team '{user_team_name}' not found in draft order. Available teams: {list(team_names_in_order)}")
        
        # Initialize simulation state
        self.current_pick_index = 0
        self.pick_log = []  # List of dicts with pick details
        self.is_paused = False
        self.simulation_complete = False
        
        # Set random seed if provided
        if random_seed is not None:
            np.random.seed(random_seed)
    
    def _deep_copy_engine(self, engine: DraftEngine) -> DraftEngine:
        """Create a deep copy of the engine to work with.
        
        Args:
            engine: Original DraftEngine instance
            
        Returns:
            Deep copied DraftEngine instance
        """
        # Deep copy DataFrames
        bat_df_copy = engine.bat_df.copy()
        pitch_df_copy = engine.pitch_df.copy()
        
        # Save keeper status before DraftEngine.__init__ resets all to 'Available'
        bat_status = bat_df_copy['Status'].copy()
        bat_drafted_by = bat_df_copy['DraftedBy'].copy()
        pitch_status = pitch_df_copy['Status'].copy()
        pitch_drafted_by = pitch_df_copy['DraftedBy'].copy()
        
        # Create new engine with copied data
        team_names = list(engine.teams.keys())
        new_engine = DraftEngine(bat_df_copy, pitch_df_copy, team_names=team_names)
        
        # Restore keeper status in DataFrames
        bat_keeper_mask = bat_status == 'Keeper'
        new_engine.bat_df.loc[bat_keeper_mask, 'Status'] = 'Keeper'
        new_engine.bat_df.loc[bat_keeper_mask, 'DraftedBy'] = bat_drafted_by[bat_keeper_mask]
        
        pitch_keeper_mask = pitch_status == 'Keeper'
        new_engine.pitch_df.loc[pitch_keeper_mask, 'Status'] = 'Keeper'
        new_engine.pitch_df.loc[pitch_keeper_mask, 'DraftedBy'] = pitch_drafted_by[pitch_keeper_mask]
        
        # Copy team rosters (keepers)
        for team_name, team in engine.teams.items():
            new_team = new_engine.teams[team_name]
            for player in team.roster:
                # Create a copy of the player
                player_copy = Player(
                    player_id=player.player_id,
                    name=player.name,
                    position=player.position,
                    team_mlb=player.team_mlb,
                    dollars=player.dollars,
                    stats=player.stats.copy(),
                    is_pitcher=player.is_pitcher
                )
                new_team.add_player(player_copy)
        
        return new_engine
    
    def _parse_draft_order(self, csv_content: str) -> pd.DataFrame:
        """Parse and validate the draft order CSV.
        
        Args:
            csv_content: CSV file path or CSV string content
            
        Returns:
            DataFrame with columns: player_name, pick_number, tendency
            
        Raises:
            ValueError: If CSV format is invalid
        """
        # Try to read as file first, then as string
        try:
            if '\n' in csv_content or ',' in csv_content:
                # Treat as CSV string content
                from io import StringIO
                df = pd.read_csv(StringIO(csv_content))
            else:
                # Treat as file path
                df = pd.read_csv(csv_content)
        except Exception as e:
            raise ValueError(f"Failed to parse CSV: {str(e)}")
        
        # Validate columns
        required_cols = ['player_name', 'pick_number', 'tendency']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV must have columns: {required_cols}. Found: {list(df.columns)}")
        
        # Validate pick numbers
        if not df['pick_number'].is_monotonic_increasing:
            raise ValueError("Pick numbers must be in increasing order")
        
        if df['pick_number'].iloc[0] != 1:
            raise ValueError("Pick numbers must start at 1")
        
        if df['pick_number'].duplicated().any():
            raise ValueError("Pick numbers must be unique")
        
        # Validate tendencies
        valid_tendencies = ['hitting', 'pitching']
        invalid_tendencies = df[~df['tendency'].isin(valid_tendencies)]
        if not invalid_tendencies.empty:
            raise ValueError(f"Invalid tendencies found. Must be 'hitting' or 'pitching'. Invalid values: {invalid_tendencies['tendency'].unique()}")
        
        # Sort by pick number
        df = df.sort_values('pick_number').reset_index(drop=True)
        
        return df
    
    def get_current_pick_info(self) -> Optional[Dict]:
        """Get information about the current pick.
        
        Returns:
            Dict with pick details or None if simulation complete
        """
        if self.current_pick_index >= len(self.draft_order):
            return None
        
        row = self.draft_order.iloc[self.current_pick_index]
        return {
            'pick_number': int(row['pick_number']),
            'team_name': row['player_name'],
            'tendency': row['tendency'],
            'is_user_pick': row['player_name'] == self.user_team_name
        }
    
    def is_user_turn(self) -> bool:
        """Check if it's currently the user's turn to pick.
        
        Returns:
            True if current pick belongs to user
        """
        pick_info = self.get_current_pick_info()
        return pick_info is not None and pick_info['is_user_pick']
    
    def make_user_pick(self, player_id: str, is_pitcher: bool) -> bool:
        """Process a user's manual pick.
        
        Args:
            player_id: ID of player to draft
            is_pitcher: Whether the player is a pitcher
            
        Returns:
            True if pick was successful
        """
        if not self.is_user_turn():
            return False
        
        pick_info = self.get_current_pick_info()
        team_name = pick_info['team_name']
        
        # Process the pick
        self.engine.process_pick(player_id, team_name, is_pitcher)
        
        # Get player info for log
        if is_pitcher:
            player_row = self.engine.pitch_df[self.engine.pitch_df['PlayerId'] == player_id].iloc[0]
        else:
            player_row = self.engine.bat_df[self.engine.bat_df['PlayerId'] == player_id].iloc[0]
        
        # Log the pick
        self.pick_log.append({
            'pick_number': pick_info['pick_number'],
            'team_name': team_name,
            'player_name': player_row['Name'],
            'position': player_row['POS'],
            'is_pitcher': is_pitcher,
            'rationale': '👤 User Selection',
            'dollars': player_row.get('Dollars', 0)
        })
        
        # Move to next pick
        self.current_pick_index += 1
        self.is_paused = False
        
        # Check if simulation is complete
        if self.current_pick_index >= len(self.draft_order):
            self.simulation_complete = True
        
        return True
    
    def simulate_next_pick(self) -> Optional[Dict]:
        """Simulate the next AI pick using probabilistic selection.
        
        Returns:
            Dict with pick details or None if it's user's turn or simulation complete
        """
        if self.current_pick_index >= len(self.draft_order):
            self.simulation_complete = True
            return None
        
        pick_info = self.get_current_pick_info()
        
        # If it's user's turn, pause
        if pick_info['is_user_pick']:
            self.is_paused = True
            return None
        
        # Make AI pick
        team_name = pick_info['team_name']
        tendency = pick_info['tendency']
        
        # Get available players, filtered to top N by Dollar value for performance
        available_batters = self.engine.bat_df[self.engine.bat_df['Status'] == 'Available']
        available_pitchers = self.engine.pitch_df[self.engine.pitch_df['Status'] == 'Available']
        
        # Filter out players with missing names to avoid NaN picks
        available_batters = available_batters[available_batters['Name'].notna()]
        available_pitchers = available_pitchers[available_pitchers['Name'].notna()]
        
        available_batters = available_batters.nlargest(self.TOP_N_PLAYERS, 'Dollars')
        available_pitchers = available_pitchers.nlargest(self.TOP_N_PLAYERS, 'Dollars')
        
        # Cache standings and category rankings once before scoring loop
        cached_standings = self.engine.get_standings()
        cached_rankings = self._compute_category_rankings(cached_standings, team_name)
        
        # Calculate scores for top available players
        player_scores = []
        
        for _, row in available_batters.iterrows():
            score = self._calculate_player_score(
                row, 
                team_name, 
                tendency, 
                is_pitcher=False,
                cached_standings=cached_standings,
                cached_rankings=cached_rankings
            )
            player_scores.append({
                'player_id': row['PlayerId'],
                'is_pitcher': False,
                'score': score,
                'name': row['Name'],
                'position': row['POS'],
                'dollars': row.get('Dollars', 0)
            })
        
        for _, row in available_pitchers.iterrows():
            score = self._calculate_player_score(
                row, 
                team_name, 
                tendency, 
                is_pitcher=True,
                cached_standings=cached_standings,
                cached_rankings=cached_rankings
            )
            player_scores.append({
                'player_id': row['PlayerId'],
                'is_pitcher': True,
                'score': score,
                'name': row['Name'],
                'position': row['POS'],
                'dollars': row.get('Dollars', 0)
            })
        
        # Convert scores to probabilities
        scores_array = np.array([p['score'] for p in player_scores])
        # Add epsilon to ensure no zero probabilities
        scores_array = scores_array + self.EPSILON
        probabilities = scores_array / scores_array.sum()
        
        # Select player using weighted random choice
        selected_idx = np.random.choice(len(player_scores), p=probabilities)
        selected_player = player_scores[selected_idx]
        
        # Process the pick
        self.engine.process_pick(
            selected_player['player_id'], 
            team_name, 
            selected_player['is_pitcher']
        )
        
        # Generate rationale
        rationale = self._generate_pick_rationale(selected_player, team_name, tendency)
        
        # Log the pick
        pick_log_entry = {
            'pick_number': pick_info['pick_number'],
            'team_name': team_name,
            'player_name': selected_player['name'],
            'position': selected_player['position'],
            'is_pitcher': selected_player['is_pitcher'],
            'rationale': rationale,
            'dollars': selected_player['dollars']
        }
        self.pick_log.append(pick_log_entry)
        
        # Move to next pick
        self.current_pick_index += 1
        
        # Check if simulation is complete
        if self.current_pick_index >= len(self.draft_order):
            self.simulation_complete = True
        
        return pick_log_entry
    
    def _calculate_player_score(self, player_row: pd.Series, team_name: str, tendency: str, is_pitcher: bool, cached_standings: pd.DataFrame = None, cached_rankings: Dict = None) -> float:
        """Calculate composite score for a player.
        
        Args:
            player_row: DataFrame row with player stats
            team_name: Name of the drafting team
            tendency: Team's drafting tendency ('hitting' or 'pitching')
            is_pitcher: Whether the player is a pitcher
            cached_standings: Pre-computed standings to avoid repeated recalculation
            cached_rankings: Pre-computed category rankings to avoid repeated recalculation
            
        Returns:
            Composite score (higher = more likely to be picked)
        """
        score = 0.0
        
        # Factor 1: Positional Need (HIGH weight)
        positional_score = self._calculate_positional_need(player_row, team_name, is_pitcher)
        score += positional_score * self.WEIGHT_POSITIONAL_NEED
        
        # Factor 2: Weakest Category Improvement (HIGH weight)
        category_score = self._calculate_category_need(player_row, team_name, is_pitcher, cached_standings, cached_rankings)
        score += category_score * self.WEIGHT_CATEGORY_NEED
        
        # Factor 3: Player Tendency (MEDIUM weight)
        tendency_score = self._calculate_tendency_score(tendency, is_pitcher)
        score += tendency_score * self.WEIGHT_TENDENCY
        
        # Factor 4: Market Value Baseline
        market_score = player_row.get('Dollars', 0)
        score += market_score * self.WEIGHT_MARKET_VALUE
        
        return max(score, 0.0)  # Ensure non-negative
    
    def _calculate_positional_need(self, player_row: pd.Series, team_name: str, is_pitcher: bool) -> float:
        """Calculate positional need score.
        
        Args:
            player_row: DataFrame row with player stats
            team_name: Name of the drafting team
            is_pitcher: Whether the player is a pitcher
            
        Returns:
            Positional need score (0-100)
        """
        team = self.engine.teams[team_name]
        position = str(player_row['POS'])
        
        # Handle NaN positions
        if pd.isna(position) or position == 'nan':
            return 10.0  # Low baseline for unknown positions
        
        # Get all eligible positions for this player
        eligible_positions = position.split('/')
        
        max_need_score = 0.0
        
        for pos in eligible_positions:
            pos = pos.strip()
            
            if is_pitcher:
                # Check pitcher slots (SP, RP, P)
                if pos in ['SP', 'RP', 'P']:
                    if pos in team.SLOT_LIMITS:
                        filled = team.slots_filled.get(pos, 0)
                        limit = team.SLOT_LIMITS[pos]
                        if filled < limit:
                            # Empty or partially filled slot = high need
                            need = 100.0 * (1.0 - filled / limit)
                            max_need_score = max(max_need_score, need)
                
                # Generic pitcher - check P slot
                if max_need_score == 0:
                    filled = team.slots_filled.get('P', 0)
                    limit = team.SLOT_LIMITS['P']
                    if filled < limit:
                        need = 100.0 * (1.0 - filled / limit)
                        max_need_score = max(max_need_score, need)
            else:
                # Check batter slots (C, 1B, 2B, 3B, SS, OF, Util)
                if pos in ['C', '1B', '2B', '3B', 'SS', 'OF']:
                    filled = team.slots_filled.get(pos, 0)
                    limit = team.SLOT_LIMITS[pos]
                    if filled < limit:
                        need = 100.0 * (1.0 - filled / limit)
                        max_need_score = max(max_need_score, need)
                
                # Check Util slot
                if max_need_score < 50:  # Only if no strong positional need
                    filled = team.slots_filled.get('Util', 0)
                    limit = team.SLOT_LIMITS['Util']
                    if filled < limit:
                        need = 50.0 * (1.0 - filled / limit)
                        max_need_score = max(max_need_score, need)
        
        # Bench slots have low need value
        if max_need_score == 0:
            filled = team.slots_filled.get('BN', 0)
            limit = team.SLOT_LIMITS['BN']
            if filled < limit:
                max_need_score = 10.0
        
        return max_need_score
    
    def _compute_category_rankings(self, standings: pd.DataFrame, team_name: str) -> Dict:
        """Pre-compute category rankings for a team from standings.
        
        Args:
            standings: Current standings DataFrame
            team_name: Name of the team to compute rankings for
            
        Returns:
            Dict mapping category name to need score (0-100)
        """
        category_rankings = {}
        num_teams = len(standings)
        
        for col in standings.columns:
            if col == 'Team':
                continue
            
            if col in ['ERA', 'WHIP']:
                ranks = standings[col].rank(ascending=True, method='min')
            else:
                ranks = standings[col].rank(ascending=False, method='min')
            
            team_rank = ranks[standings['Team'] == team_name].iloc[0]
            category_rankings[col] = (team_rank / num_teams) * 100
        
        return category_rankings
    
    def _calculate_category_need(self, player_row: pd.Series, team_name: str, is_pitcher: bool, cached_standings: pd.DataFrame = None, cached_rankings: Dict = None) -> float:
        """Calculate category need score based on team's weakest categories.
        
        Args:
            player_row: DataFrame row with player stats
            team_name: Name of the drafting team
            is_pitcher: Whether the player is a pitcher
            cached_standings: Pre-computed standings to avoid repeated recalculation
            cached_rankings: Pre-computed category rankings to avoid repeated recalculation
            
        Returns:
            Category need score (0-100)
        """
        # Use cached rankings if provided, otherwise compute them
        if cached_rankings is not None:
            category_rankings = cached_rankings
        else:
            if cached_standings is not None:
                standings = cached_standings
            else:
                standings = self.engine.get_standings()
            category_rankings = self._compute_category_rankings(standings, team_name)
        
        # Calculate how much this player helps with weak categories
        category_score = 0.0
        
        if is_pitcher:
            # Pitching categories: K, SV, WAR, ERA, WHIP
            categories = {
                'K': player_row.get('SO', 0),
                'SV': player_row.get('SV', 0),
                'WAR': player_row.get('WAR', 0),
                'ERA': player_row.get('ERA', 5.0),  # Lower is better
                'WHIP': player_row.get('WHIP', 1.5)  # Lower is better
            }
            
            for cat, value in categories.items():
                if cat in category_rankings:
                    need = category_rankings[cat]
                    
                    # Weight the contribution by both need and player's value
                    if cat == 'ERA':
                        # Lower ERA is better, so invert the value contribution
                        contribution = max(0, (5.0 - value) / 5.0) * 10
                    elif cat == 'WHIP':
                        # Lower WHIP is better
                        contribution = max(0, (1.5 - value) / 1.5) * 10
                    else:
                        # Higher is better - normalize contribution
                        contribution = min(value / 10.0, 10.0)
                    
                    category_score += need * contribution / 100.0
        else:
            # Batting categories: R, HR, RBI, SB, OBP
            categories = {
                'R': player_row.get('R', 0),
                'HR': player_row.get('HR', 0),
                'RBI': player_row.get('RBI', 0),
                'SB': player_row.get('SB', 0),
                'OBP': player_row.get('OBP', 0.300)
            }
            
            for cat, value in categories.items():
                if cat in category_rankings:
                    need = category_rankings[cat]
                    
                    # Weight the contribution by both need and player's value
                    if cat == 'OBP':
                        contribution = value * 100  # Scale OBP appropriately
                    else:
                        contribution = min(value / 10.0, 10.0)
                    
                    category_score += need * contribution / 100.0
        
        return category_score
    
    def _calculate_tendency_score(self, tendency: str, is_pitcher: bool) -> float:
        """Calculate tendency score.
        
        Args:
            tendency: Team's drafting tendency ('hitting' or 'pitching')
            is_pitcher: Whether the player is a pitcher
            
        Returns:
            Tendency score (0-100)
        """
        if tendency == 'pitching' and is_pitcher:
            return 50.0
        elif tendency == 'hitting' and not is_pitcher:
            return 50.0
        else:
            return 0.0
    
    def _generate_pick_rationale(self, selected_player: Dict, team_name: str, tendency: str) -> str:
        """Generate a brief rationale for the pick.
        
        Args:
            selected_player: Dict with player info
            team_name: Name of drafting team
            tendency: Team's drafting tendency
            
        Returns:
            Brief rationale string
        """
        team = self.engine.teams[team_name]
        position = selected_player['position']
        is_pitcher = selected_player['is_pitcher']
        
        # Check positional need
        has_positional_need = False
        if is_pitcher:
            for pos in ['SP', 'RP', 'P']:
                if pos in position:
                    filled = team.slots_filled.get(pos, 0)
                    limit = team.SLOT_LIMITS.get(pos, 0)
                    if filled < limit:
                        has_positional_need = True
                        break
        else:
            positions = position.split('/')
            for pos in positions:
                pos = pos.strip()
                if pos in ['C', '1B', '2B', '3B', 'SS', 'OF']:
                    filled = team.slots_filled.get(pos, 0)
                    limit = team.SLOT_LIMITS.get(pos, 0)
                    if filled < limit:
                        has_positional_need = True
                        break
        
        # Build rationale
        reasons = []
        
        if has_positional_need:
            reasons.append("fills positional need")
        
        # Check if matches tendency
        if (tendency == 'pitching' and is_pitcher) or (tendency == 'hitting' and not is_pitcher):
            reasons.append(f"matches {tendency} preference")
        
        # Always mention value
        dollars = selected_player.get('dollars', 0)
        if dollars > 20:
            reasons.append(f"high value (${dollars:.0f})")
        
        if not reasons:
            reasons.append("best available")
        
        return "🤖 AI: " + ", ".join(reasons)
    
    def simulate_until_user_or_complete(self) -> List[Dict]:
        """Simulate picks until user's turn or draft completion.
        
        Returns:
            List of pick log entries for simulated picks
        """
        simulated_picks = []
        
        while not self.is_paused and not self.simulation_complete:
            pick_result = self.simulate_next_pick()
            if pick_result:
                simulated_picks.append(pick_result)
        
        return simulated_picks
    
    def get_standings(self) -> pd.DataFrame:
        """Get current standings.
        
        Returns:
            DataFrame with current standings
        """
        return self.engine.get_standings()
    
    def get_team_roster(self, team_name: str) -> pd.DataFrame:
        """Get roster for a specific team.
        
        Args:
            team_name: Name of the team
            
        Returns:
            DataFrame with team roster
        """
        return self.engine.get_team_roster_df(team_name)
