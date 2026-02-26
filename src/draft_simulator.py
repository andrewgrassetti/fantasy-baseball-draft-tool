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
  5. Position redundancy penalty (multiplicative — see below)

While flex slots (Util, P, BN) remain open, the AI considers ALL
available players regardless of position so that high-value players
are never ignored simply because their primary position slot is filled
(e.g. drafting two elite 1B before a low-value C).  A soft positional
need score still gives a bonus to players who fill empty specific
slots, providing a natural pull toward roster balance.

Once every flex slot is filled, a hard positional filter restricts
candidates to players eligible for the remaining unfilled specific
slots (C, 1B, 2B, 3B, SS, OF, SP, RP), ensuring a legal roster by
the end of the draft.

Positional priority multipliers reflect real-world positional scarcity and
are applied as a direct multiplier on the overall composite score so that
positions with low scarcity (e.g. catcher) are meaningfully de-prioritized
even when their dollar values are high:
  Offense (highest to lowest): 1B, OF, SS, 3B, 2B, C
  Pitching (highest to lowest): SP, RP

Position redundancy downweighting penalizes drafting surplus players at
the same position.  Catcher is the most aggressively penalized (rarely
should a team draft more than 1 C); OF and 1B carry the lightest
penalties because extra OF/1B often make good Util/bench players.

Dollar values are expanded via a power function (DOLLAR_EXPANSION_EXPONENT)
before weighting, increasing the gap between high- and low-value players.

After scoring, the candidate pool is shortlisted to the top
SHORTLIST_PER_TYPE players per position type (batters and pitchers
separately).  This ensures that within each type the highest-valued
players are always strongly preferred and prevents scenarios where
multiple lower-value players at a position are drafted while a
higher-value player at the same position remains on the board.

Within each type, no single fielding position may contribute more than
MAX_PER_POSITION_IN_SHORTLIST candidates to the shortlist.  This
prevents a position with inflated dollar values (e.g. catcher) from
monopolizing the shortlist and bypassing the positional weighting that
is designed to de-prioritize it.

A power-law exponent is applied to composite scores before converting
to probabilities, concentrating selection probability on top-valued players.
"""

import logging
import pandas as pd
import numpy as np
import copy
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional
from .models import Team, Player
from .draft_engine import DraftEngine

logger = logging.getLogger(__name__)


class DraftSimulator:
    """Simulates a fantasy baseball draft with probabilistic AI picks."""
    
    # Scoring weights for pick selection
    WEIGHT_MARKET_VALUE = 35.0         # DOMINANT weight - dollar value is king
    WEIGHT_POSITIONAL_NEED = 0.5       # SECONDARY weight - distant second
    WEIGHT_CATEGORY_NEED = 0.1         # LOW weight
    WEIGHT_TENDENCY = 0.1              # LOW weight
    
    # Power-law exponent applied to scores before converting to probabilities.
    # Values > 1 concentrate selection probability on top-scored players.
    SCORE_EXPONENT = 4.0
    
    # Positional priority multipliers reflecting positional scarcity.
    # Applied to positional need scores so higher-priority positions are
    # drafted earlier when multiple slots are open.
    # Offense (high to low): 1B, OF, SS, 3B, 2B, C
    # Pitching (high to low): SP, RP
    POSITION_PRIORITY = {
        '1B': 1.30,
        'OF': 1.25,
        'SS': 1.25,
        '3B': 1.25,
        '2B': 1.15,
        'C':  1.00,
        'SP': 1.25,
        'RP': 1.10,
    }
    
    # Position redundancy multipliers applied to the composite score.
    # Each list is indexed by the number of rostered players at that position.
    # Index 0 = multiplier when 0 already rostered, index 1 = when 1 rostered, etc.
    # Catcher is most aggressively penalized; OF and 1B are least penalized
    # because they are more likely to provide Util/bench value.
    POSITION_REDUNDANCY = {
        'C':  [1.0, 0.08, 0.01],              # 1 C slot; 2nd C is rare, 3rd almost never
        'SS': [1.0, 0.35, 0.08],              # 1 SS slot
        '2B': [1.0, 0.35, 0.08],              # 1 2B slot
        '3B': [1.0, 0.35, 0.08],              # 1 3B slot
        '1B': [1.0, 0.55, 0.25],              # 1 1B slot; power bats fine as Util
        'OF': [1.0, 1.0, 1.0, 0.55, 0.25],    # 3 OF slots; extras are OK
        'SP': [1.0, 1.0, 1.0, 0.65, 0.35],    # 3 SP slots
        'RP': [1.0, 1.0, 0.45, 0.15],          # 2 RP slots
    }
    
    # Exponent applied to dollar values before scoring.  Values > 1 widen the
    # gap between high- and low-dollar players so that picks are more decisive.
    DOLLAR_EXPANSION_EXPONENT = 1.4
    
    # Small epsilon to ensure every player has nonzero selection probability
    EPSILON = 0.01
    
    # Maximum number of top players (by Dollar value) to consider per pick
    TOP_N_PLAYERS = 50
    
    # Maximum number of top-scored candidates to shortlist per position type
    # (batters and pitchers separately) before probabilistic selection.
    # This ensures that within each position type, value ordering is respected
    # and prevents lower-value players at a position from being drafted before
    # higher-value ones.
    SHORTLIST_PER_TYPE = 5
    
    # Maximum number of candidates from any single fielding position allowed
    # in the shortlist.  This prevents a single position (e.g. catcher) from
    # monopolizing the batter shortlist when its players happen to have the
    # highest raw dollar values, which would negate the positional weighting
    # designed to de-prioritize that position.
    MAX_PER_POSITION_IN_SHORTLIST = 2
    
    def __init__(self, engine: DraftEngine, draft_order_csv: str, user_team_name: str, random_seed: Optional[int] = None, snapshot_mode: bool = False, draft_order_df: Optional[pd.DataFrame] = None):
        """Initialize the draft simulator.
        
        Args:
            engine: The DraftEngine instance (will be deep copied)
            draft_order_csv: Path to CSV or CSV content as string
            user_team_name: Name of the user's team (must match CSV)
            random_seed: Optional random seed for reproducibility
            snapshot_mode: If True, skips user-team validation and never pauses
                           on user's turn (all picks are auto-simulated).
            draft_order_df: Optional pre-parsed draft order DataFrame.  When
                            provided, ``draft_order_csv`` parsing is skipped
                            (saves repeated CSV parsing in Monte Carlo loops).
        """
        # Deep copy the engine to avoid mutating the main draft state
        if snapshot_mode:
            self.engine = self._snapshot_copy_engine(engine)
        else:
            self.engine = self._deep_copy_engine(engine)
        self.snapshot_mode = snapshot_mode
        
        # Parse draft order (or reuse pre-parsed DataFrame)
        if draft_order_df is not None:
            self.draft_order = draft_order_df
        else:
            self.draft_order = self._parse_draft_order(draft_order_csv)
        self.user_team_name = user_team_name
        
        # Validate user team name exists in draft order (skipped in snapshot mode)
        if not snapshot_mode:
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
    
    def _snapshot_copy_engine(self, engine: DraftEngine) -> DraftEngine:
        """Create a lightweight engine copy for snapshot (Monte Carlo) simulation.

        Faster than ``_deep_copy_engine`` by skipping ``DraftEngine.__init__``
        overhead and using shallow copies of Player objects (they are
        effectively read-only during simulation — new players are only ever
        appended, never mutated).

        Args:
            engine: Original DraftEngine instance (treated as read-only).

        Returns:
            Lightweight DraftEngine copy suitable for a single simulation run.
        """
        new_engine = object.__new__(DraftEngine)
        # Copy DataFrames (Status/DraftedBy columns included — no reset needed)
        new_engine.bat_df = engine.bat_df.copy()
        new_engine.pitch_df = engine.pitch_df.copy()

        # Shallow-copy teams: roster lists and mutable dicts are copied so that
        # add_player() calls during simulation don't affect the original teams.
        new_engine.teams = {}
        for team_name, team in engine.teams.items():
            new_team = object.__new__(Team)
            new_team.owner_name = team.owner_name
            new_team.roster = list(team.roster)  # new list, same Player refs
            new_team.slots_filled = dict(team.slots_filled)
            new_team.position_counts = dict(getattr(team, 'position_counts', {}))
            # Copy incremental totals cache
            new_team._incr = dict(getattr(team, '_incr', {'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'K': 0, 'SV': 0, 'QS': 0}))
            new_team._total_ab = getattr(team, '_total_ab', 0)
            new_team._total_on_base = getattr(team, '_total_on_base', 0.0)
            new_team._total_ip = getattr(team, '_total_ip', 0.0)
            new_team._total_er = getattr(team, '_total_er', 0.0)
            new_team._total_wh = getattr(team, '_total_wh', 0.0)
            new_engine.teams[team_name] = new_team

        # Pre-build player-id → integer-row-position maps for O(1) lookup in
        # process_pick_fast (avoids O(n) DataFrame mask comparisons per pick).
        new_engine._bat_pid_to_idx = {pid: i for i, pid in enumerate(new_engine.bat_df['PlayerId'].values)}
        new_engine._pitch_pid_to_idx = {pid: i for i, pid in enumerate(new_engine.pitch_df['PlayerId'].values)}
        # Cache column positions for fast scalar writes via DataFrame.iat
        new_engine._bat_status_col = new_engine.bat_df.columns.get_loc('Status')
        new_engine._pitch_status_col = new_engine.pitch_df.columns.get_loc('Status')

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
        
        # If it's user's turn, pause (unless running in snapshot mode)
        if pick_info['is_user_pick'] and not self.snapshot_mode:
            self.is_paused = True
            return None
        
        # Make AI pick
        team_name = pick_info['team_name']
        tendency = pick_info['tendency']
        
        # Get available players, filtered to top N by Dollar value for performance
        if self.snapshot_mode:
            # Snapshot fast path: combine availability + NaN filters into one mask
            bat_df = self.engine.bat_df
            pitch_df = self.engine.pitch_df
            bat_mask = (bat_df['Status'].values == 'Available') & bat_df['Name'].notna().values
            pitch_mask = (pitch_df['Status'].values == 'Available') & pitch_df['Name'].notna().values
            if 'Team' in bat_df.columns:
                bat_mask &= bat_df['Team'].notna().values
            if 'Team' in pitch_df.columns:
                pitch_mask &= pitch_df['Team'].notna().values
            available_batters = bat_df[bat_mask]
            available_pitchers = pitch_df[pitch_mask]
        else:
            available_batters = self.engine.bat_df[self.engine.bat_df['Status'] == 'Available']
            available_pitchers = self.engine.pitch_df[self.engine.pitch_df['Status'] == 'Available']
            
            # Filter out players with missing names to avoid NaN picks
            available_batters = available_batters[available_batters['Name'].notna()]
            available_pitchers = available_pitchers[available_pitchers['Name'].notna()]
            
            # Filter out players with no team (free agents/retired/out-of-league)
            if 'Team' in available_batters.columns:
                available_batters = available_batters[available_batters['Team'].notna()]
            if 'Team' in available_pitchers.columns:
                available_pitchers = available_pitchers[available_pitchers['Team'].notna()]
        
        # Hard positional filter: only applied when flex slots (Util, P, BN)
        # are all full — at that point every remaining pick MUST go to an
        # unfilled specific position to ensure a legal roster.  While flex
        # slots remain, all players are considered so the AI can chase value
        # (e.g. drafting two elite 1B before a low-value C).
        if not self._has_flex_slots(team_name):
            needed_positions = self._get_needed_positions(team_name)
            if needed_positions:
                filtered_batters = available_batters[
                    available_batters['POS'].apply(
                        lambda pos: self._has_needed_position(pos, needed_positions)
                    )
                ]
                filtered_pitchers = available_pitchers[
                    available_pitchers['POS'].apply(
                        lambda pos: self._has_needed_position(pos, needed_positions)
                    )
                ]
                # Only apply filter if it leaves at least one candidate
                if not filtered_batters.empty or not filtered_pitchers.empty:
                    available_batters = filtered_batters
                    available_pitchers = filtered_pitchers
        
        if self.snapshot_mode:
            # In snapshot mode, use argpartition for large pools, skip for small
            if len(available_batters) > self.TOP_N_PLAYERS:
                vals = available_batters['Dollars'].values.astype(float)
                top_idx = np.argpartition(vals, -self.TOP_N_PLAYERS)[-self.TOP_N_PLAYERS:]
                available_batters = available_batters.iloc[top_idx]
            if len(available_pitchers) > self.TOP_N_PLAYERS:
                vals = available_pitchers['Dollars'].values.astype(float)
                top_idx = np.argpartition(vals, -self.TOP_N_PLAYERS)[-self.TOP_N_PLAYERS:]
                available_pitchers = available_pitchers.iloc[top_idx]
        else:
            available_batters = available_batters.nlargest(self.TOP_N_PLAYERS, 'Dollars')
            available_pitchers = available_pitchers.nlargest(self.TOP_N_PLAYERS, 'Dollars')
        
        # Cache standings and category rankings once before scoring loop
        if self.snapshot_mode:
            # Fast path: compute rankings directly from team totals, bypass DataFrame
            cached_standings = None
            cached_rankings = self._compute_category_rankings_fast(team_name)
        else:
            cached_standings = self.engine.get_standings()
            cached_rankings = self._compute_category_rankings(cached_standings, team_name)
        
        # Calculate scores for top available players
        if self.snapshot_mode:
            # Batch scoring: vectorized operations replace iterrows()
            player_scores = (
                self._score_candidates_batch(available_batters, team_name, tendency,
                                             False, cached_standings, cached_rankings)
                + self._score_candidates_batch(available_pitchers, team_name, tendency,
                                               True, cached_standings, cached_rankings)
            )
        else:
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
        
        # Shortlist: keep only the top SHORTLIST_PER_TYPE candidates from
        # each position type (batters / pitchers) so that within each type
        # the highest-valued players are always strongly preferred.  This
        # prevents a low-value SP from being drafted while a higher-value
        # SP sits on the board.
        #
        # Within each type, no single fielding position may contribute more
        # than MAX_PER_POSITION_IN_SHORTLIST candidates.  This ensures that
        # a position with inflated dollar values (e.g. catcher) cannot
        # monopolize the shortlist and bypass the positional weighting that
        # is designed to de-prioritize it.
        batter_candidates = [p for p in player_scores if not p['is_pitcher']]
        pitcher_candidates = [p for p in player_scores if p['is_pitcher']]
        batter_candidates.sort(key=lambda p: p['score'], reverse=True)
        pitcher_candidates.sort(key=lambda p: p['score'], reverse=True)
        shortlisted = (
            self._position_diverse_shortlist(batter_candidates)
            + self._position_diverse_shortlist(pitcher_candidates)
        )
        
        if not shortlisted:
            # No candidates available — skip this pick
            self.current_pick_index += 1
            if self.current_pick_index >= len(self.draft_order):
                self.simulation_complete = True
            return None
        
        # Convert scores to probabilities using power-law scaling
        scores_array = np.array([p['score'] for p in shortlisted])
        # Re-center scores so the lowest candidate starts near zero.
        # Dollar normalization shifts all values positive, compressing the
        # ratio between top and bottom candidates.  Subtracting the minimum
        # restores the dynamic range so the power-law exponent can properly
        # concentrate selection probability on top-valued players.
        scores_array = scores_array - scores_array.min()
        # Add epsilon to ensure no zero probabilities
        scores_array = scores_array + self.EPSILON
        # Apply power-law exponent to concentrate probability on top-scored players
        scores_array = np.power(scores_array, self.SCORE_EXPONENT)
        probabilities = scores_array / scores_array.sum()
        
        # Select player using weighted random choice
        selected_idx = np.random.choice(len(shortlisted), p=probabilities)
        selected_player = shortlisted[selected_idx]
        
        # Process the pick
        if self.snapshot_mode:
            self.engine.process_pick_fast(
                selected_player['player_id'],
                team_name,
                selected_player['is_pitcher']
            )
        else:
            self.engine.process_pick(
                selected_player['player_id'], 
                team_name, 
                selected_player['is_pitcher']
            )
        
        # Move to next pick
        self.current_pick_index += 1
        
        # Check if simulation is complete
        if self.current_pick_index >= len(self.draft_order):
            self.simulation_complete = True
        
        # In snapshot mode, skip rationale generation and pick log (not displayed)
        if self.snapshot_mode:
            return selected_player
        
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
        
        # Factor 4: Market Value Baseline (dollar expansion widens the gap
        # between high- and low-value players before weighting)
        raw_dollars = max(player_row.get('Dollars', 0), 0.0)
        market_score = raw_dollars ** self.DOLLAR_EXPANSION_EXPONENT
        score += market_score * self.WEIGHT_MARKET_VALUE
        
        # Factor 5: Position redundancy penalty — reduce score when the team
        # already has players at this position to prevent over-drafting
        redundancy_multiplier = self._get_position_redundancy_multiplier(player_row, team_name, is_pitcher)
        score *= redundancy_multiplier
        
        # Factor 6: Positional scarcity multiplier — applied to total score so
        # that positions with low real-world scarcity (e.g. catcher) are
        # meaningfully de-prioritized even when their dollar values are high.
        position = str(player_row['POS'])
        if not pd.isna(position) and position != 'nan':
            primary_pos = position.split('/')[0].strip()
            score *= self.POSITION_PRIORITY.get(primary_pos, 1.0)
        
        return max(score, 0.0)  # Ensure non-negative
    
    def _calculate_positional_need(self, player_row: pd.Series, team_name: str, is_pitcher: bool) -> float:
        """Calculate positional need score with positional priority weighting.
        
        Positional priority multipliers (from POSITION_PRIORITY) reflect
        real-world positional scarcity so that higher-demand positions are
        preferred when multiple slots are open.
        
        Args:
            player_row: DataFrame row with player stats
            team_name: Name of the drafting team
            is_pitcher: Whether the player is a pitcher
            
        Returns:
            Positional need score (base 0-100, scaled by priority multiplier)
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
                            # Apply positional priority multiplier
                            priority = self.POSITION_PRIORITY.get(pos, 1.0)
                            need *= priority
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
                        # Apply positional priority multiplier
                        priority = self.POSITION_PRIORITY.get(pos, 1.0)
                        need *= priority
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
    
    def _get_needed_positions(self, team_name: str) -> set:
        """Get specific position slots that still need filling.
        
        Returns only 'specific' positions (C, 1B, 2B, 3B, SS, OF for batters;
        SP, RP for pitchers).  Generic/flex slots (Util, P, BN, IL, NA) are
        excluded so that the AI is not restricted when only flex slots remain.
        
        Args:
            team_name: Name of the team
            
        Returns:
            Set of position strings that have unfilled specific slots
        """
        team = self.engine.teams[team_name]
        needed = set()
        specific_positions = ['C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP']
        for pos in specific_positions:
            if pos in team.SLOT_LIMITS:
                if team.slots_filled.get(pos, 0) < team.SLOT_LIMITS[pos]:
                    needed.add(pos)
        return needed
    
    def _has_flex_slots(self, team_name: str) -> bool:
        """Check whether the team still has generic/flex roster slots open.
        
        Flex slots are Util, P, and BN — they can absorb a player of any
        position.  While at least one is open, the hard positional filter
        is not applied so the AI can chase value regardless of position.
        
        Args:
            team_name: Name of the team
            
        Returns:
            True if at least one Util, P, or BN slot is unfilled
        """
        team = self.engine.teams[team_name]
        for slot in ('Util', 'P', 'BN'):
            if team.slots_filled.get(slot, 0) < team.SLOT_LIMITS.get(slot, 0):
                return True
        return False
    
    def _has_needed_position(self, position_str, needed_positions: set) -> bool:
        """Check if a position string contains any needed position.
        
        Args:
            position_str: Player position string (e.g. '2B', 'SS/2B', 'SP')
            needed_positions: Set of positions that need filling
            
        Returns:
            True if the player is eligible for at least one needed position
        """
        if pd.isna(position_str) or str(position_str) == 'nan':
            return False
        positions = [p.strip() for p in str(position_str).split('/')]
        return any(p in needed_positions for p in positions)
    
    def _position_diverse_shortlist(self, candidates: List[Dict]) -> List[Dict]:
        """Build a shortlist of up to SHORTLIST_PER_TYPE candidates while
        limiting any single fielding position to MAX_PER_POSITION_IN_SHORTLIST
        entries.

        Candidates must be pre-sorted by score (descending).  The method
        iterates through the sorted list, accepting each candidate unless its
        primary position has already reached the per-position cap.  This
        guarantees that a position with inflated dollar values cannot
        monopolize the shortlist.

        Args:
            candidates: Scored candidate dicts, sorted by score descending.
                        Each dict must have a 'position' key.

        Returns:
            List of up to SHORTLIST_PER_TYPE candidates with position diversity.
        """
        shortlist: List[Dict] = []
        position_counts: Dict[str, int] = {}
        for candidate in candidates:
            pos = candidate.get('position', '')
            primary = pos.split('/')[0].strip() if pos and not pd.isna(pos) else 'Unknown'
            count = position_counts.get(primary, 0)
            if count < self.MAX_PER_POSITION_IN_SHORTLIST:
                shortlist.append(candidate)
                position_counts[primary] = count + 1
                if len(shortlist) >= self.SHORTLIST_PER_TYPE:
                    break
        return shortlist
    
    def _score_candidates_batch(self, df: pd.DataFrame, team_name: str,
                                tendency: str, is_pitcher: bool,
                                cached_standings: pd.DataFrame,
                                cached_rankings: Dict) -> List[Dict]:
        """Score all candidates using batch operations (faster than iterrows).

        Pre-computes position-dependent multipliers once per unique position
        string and uses vectorized numpy operations for dollar-value scoring.

        Args:
            df: DataFrame of available players (already filtered to top N).
            team_name: Name of the drafting team.
            tendency: Team drafting tendency ('hitting' or 'pitching').
            is_pitcher: Whether these are pitcher candidates.
            cached_standings: Pre-computed standings DataFrame.
            cached_rankings: Pre-computed category rankings dict.

        Returns:
            List of candidate dicts with 'player_id', 'is_pitcher', 'score',
            'name', 'position', 'dollars', and 'stats' keys.
        """
        n = len(df)
        if n == 0:
            return []

        team = self.engine.teams[team_name]

        # --- Pre-compute position-dependent values per unique position string ---
        positions = df['POS'].values.astype(str)
        unique_positions = set(positions)

        pos_need_map: Dict[str, float] = {}
        redundancy_map: Dict[str, float] = {}
        priority_map: Dict[str, float] = {}

        for pos_str in unique_positions:
            # Positional need (mirrors _calculate_positional_need logic)
            pos_need_map[pos_str] = self._positional_need_for_pos(pos_str, team, is_pitcher)
            # Redundancy multiplier (mirrors _get_position_redundancy_multiplier)
            redundancy_map[pos_str] = self._redundancy_for_pos(pos_str, team)
            # Position priority (primary position only)
            if pos_str != 'nan':
                primary = pos_str.split('/')[0].strip()
                priority_map[pos_str] = self.POSITION_PRIORITY.get(primary, 1.0)
            else:
                priority_map[pos_str] = 1.0

        # --- Vectorized market-value scores ---
        dollars = np.nan_to_num(df['Dollars'].values.astype(float), nan=0.0)
        np.maximum(dollars, 0.0, out=dollars)
        scores = np.power(dollars, self.DOLLAR_EXPANSION_EXPONENT) * self.WEIGHT_MARKET_VALUE

        # --- Tendency score (constant for all candidates of same type) ---
        if (tendency == 'pitching' and is_pitcher) or (tendency == 'hitting' and not is_pitcher):
            scores += 50.0 * self.WEIGHT_TENDENCY

        # --- Vectorized category-need scores ---
        if cached_rankings is not None:
            cat_scores = np.zeros(n)
            if is_pitcher:
                so_v = df['SO'].values if 'SO' in df.columns else np.zeros(n)
                sv_v = df['SV'].values if 'SV' in df.columns else np.zeros(n)
                qs_v = df['QS'].values if 'QS' in df.columns else np.zeros(n)
                era_v = df['ERA'].values.astype(float) if 'ERA' in df.columns else np.full(n, 5.0)
                whip_v = df['WHIP'].values.astype(float) if 'WHIP' in df.columns else np.full(n, 1.5)
                for cat, need in cached_rankings.items():
                    if cat == 'K':
                        cat_scores += need * np.minimum(so_v / 10.0, 10.0) / 100.0
                    elif cat == 'SV':
                        cat_scores += need * np.minimum(sv_v / 10.0, 10.0) / 100.0
                    elif cat == 'QS':
                        cat_scores += need * np.minimum(qs_v / 10.0, 10.0) / 100.0
                    elif cat == 'ERA':
                        cat_scores += need * np.maximum(0, (5.0 - era_v) / 5.0) * 10 / 100.0
                    elif cat == 'WHIP':
                        cat_scores += need * np.maximum(0, (1.5 - whip_v) / 1.5) * 10 / 100.0
            else:
                r_v = df['R'].values if 'R' in df.columns else np.zeros(n)
                hr_v = df['HR'].values if 'HR' in df.columns else np.zeros(n)
                rbi_v = df['RBI'].values if 'RBI' in df.columns else np.zeros(n)
                sb_v = df['SB'].values if 'SB' in df.columns else np.zeros(n)
                obp_v = df['OBP'].values.astype(float) if 'OBP' in df.columns else np.full(n, 0.3)
                for cat, need in cached_rankings.items():
                    if cat == 'R':
                        cat_scores += need * np.minimum(r_v / 10.0, 10.0) / 100.0
                    elif cat == 'HR':
                        cat_scores += need * np.minimum(hr_v / 10.0, 10.0) / 100.0
                    elif cat == 'RBI':
                        cat_scores += need * np.minimum(rbi_v / 10.0, 10.0) / 100.0
                    elif cat == 'SB':
                        cat_scores += need * np.minimum(sb_v / 10.0, 10.0) / 100.0
                    elif cat == 'OBP':
                        cat_scores += need * (obp_v * 100) / 100.0
            scores += cat_scores * self.WEIGHT_CATEGORY_NEED

        # --- Apply position-dependent additive and multiplicative factors ---
        for i in range(n):
            pos = positions[i]
            scores[i] += pos_need_map[pos] * self.WEIGHT_POSITIONAL_NEED
            scores[i] *= redundancy_map[pos]
            scores[i] *= priority_map[pos]

        np.maximum(scores, 0.0, out=scores)

        # --- Build result dicts (include minimal stats for snapshot process_pick) ---
        player_ids = df['PlayerId'].values
        names_arr = df['Name'].values

        results = []
        for i in range(n):
            results.append({
                'player_id': player_ids[i],
                'is_pitcher': is_pitcher,
                'score': float(scores[i]),
                'name': names_arr[i],
                'position': positions[i],
                'dollars': float(dollars[i]),
            })
        return results

    def _positional_need_for_pos(self, pos_str: str, team, is_pitcher: bool) -> float:
        """Compute positional need score from a position string (no DataFrame row)."""
        if pos_str == 'nan':
            return 10.0

        eligible_positions = pos_str.split('/')
        max_need = 0.0

        for pos in eligible_positions:
            pos = pos.strip()
            if is_pitcher:
                if pos in ('SP', 'RP', 'P') and pos in team.SLOT_LIMITS:
                    filled = team.slots_filled.get(pos, 0)
                    limit = team.SLOT_LIMITS[pos]
                    if filled < limit:
                        need = 100.0 * (1.0 - filled / limit)
                        need *= self.POSITION_PRIORITY.get(pos, 1.0)
                        max_need = max(max_need, need)
                if max_need == 0:
                    filled = team.slots_filled.get('P', 0)
                    limit = team.SLOT_LIMITS['P']
                    if filled < limit:
                        max_need = max(max_need, 100.0 * (1.0 - filled / limit))
            else:
                if pos in ('C', '1B', '2B', '3B', 'SS', 'OF'):
                    filled = team.slots_filled.get(pos, 0)
                    limit = team.SLOT_LIMITS[pos]
                    if filled < limit:
                        need = 100.0 * (1.0 - filled / limit)
                        need *= self.POSITION_PRIORITY.get(pos, 1.0)
                        max_need = max(max_need, need)
                if max_need < 50:
                    filled = team.slots_filled.get('Util', 0)
                    limit = team.SLOT_LIMITS['Util']
                    if filled < limit:
                        max_need = max(max_need, 50.0 * (1.0 - filled / limit))

        if max_need == 0:
            filled = team.slots_filled.get('BN', 0)
            limit = team.SLOT_LIMITS['BN']
            if filled < limit:
                max_need = 10.0

        return max_need

    def _redundancy_for_pos(self, pos_str: str, team) -> float:
        """Compute redundancy multiplier from a position string (no DataFrame row)."""
        if pos_str == 'nan':
            return 1.0

        eligible = [p.strip() for p in pos_str.split('/')]
        best = None
        for pos in eligible:
            table = self.POSITION_REDUNDANCY.get(pos)
            if table is None:
                best = 1.0
                continue
            count = team.position_counts.get(pos, 0)
            idx = min(count, len(table) - 1)
            mult = table[idx]
            if best is None or mult > best:
                best = mult
        return best if best is not None else 1.0
    
    def _get_position_redundancy_multiplier(self, player_row: pd.Series, team_name: str, is_pitcher: bool) -> float:
        """Return a score multiplier (0-1) that penalizes drafting surplus players
        at the same position.

        The multiplier is looked up from POSITION_REDUNDANCY using the number of
        players already on the roster who share at least one eligible position
        with the incoming player.  For multi-position players (e.g. "C/1B") the
        *best* (highest) multiplier across eligible positions is used so that a
        player is not penalized for their secondary position when their primary
        position is already stocked.

        Args:
            player_row: DataFrame row with player stats
            team_name: Name of the drafting team
            is_pitcher: Whether the player is a pitcher

        Returns:
            Multiplier in (0, 1] to apply to the composite score
        """
        team = self.engine.teams[team_name]
        position = str(player_row['POS'])

        if pd.isna(position) or position == 'nan':
            return 1.0

        eligible_positions = [p.strip() for p in position.split('/')]

        best_multiplier = None

        for pos in eligible_positions:
            redundancy_table = self.POSITION_REDUNDANCY.get(pos)
            if redundancy_table is None:
                # Unknown position — no penalty
                best_multiplier = 1.0
                continue

            # Count rostered players who list this position (cache lookup)
            count = team.position_counts.get(pos, 0)

            idx = min(count, len(redundancy_table) - 1)
            multiplier = redundancy_table[idx]
            if best_multiplier is None or multiplier > best_multiplier:
                best_multiplier = multiplier

        return best_multiplier if best_multiplier is not None else 1.0
    
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
    
    _LOWER_IS_BETTER = frozenset(('ERA', 'WHIP'))
    _CATEGORIES = ('R', 'HR', 'RBI', 'SB', 'OBP', 'K', 'SV', 'QS', 'ERA', 'WHIP')

    def _compute_category_rankings_fast(self, team_name: str) -> Dict:
        """Compute category rankings directly from team totals (no DataFrame).

        Equivalent to ``_compute_category_rankings`` but avoids creating a
        standings DataFrame and calling ``pandas.Series.rank()``.  For 12 teams
        with 10 categories this is roughly 30-50× faster.
        """
        teams = self.engine.teams
        team_names = list(teams.keys())
        num_teams = len(team_names)
        all_totals = [teams[n].live_totals for n in team_names]
        my_totals = teams[team_name].live_totals

        category_rankings: Dict[str, float] = {}
        for cat in self._CATEGORIES:
            my_val = my_totals[cat]
            if cat in self._LOWER_IS_BETTER:
                rank = sum(1 for t in all_totals if t[cat] < my_val) + 1
            else:
                rank = sum(1 for t in all_totals if t[cat] > my_val) + 1
            category_rankings[cat] = (rank / num_teams) * 100

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
            # Pitching categories: K, SV, QS, ERA, WHIP
            categories = {
                'K': player_row.get('SO', 0),
                'SV': player_row.get('SV', 0),
                'QS': player_row.get('QS', 0),
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


def _reconcile_snapshot_pick_index(
    engine: DraftEngine,
    draft_order_df: pd.DataFrame,
) -> int:
    """Infer the best starting pick index from the actual draft state.

    Counts all non-keeper drafted players to determine how many picks have
    been made, then clamps to the draft order length so the index is always
    valid.  This avoids relying on a manually-entered pick number that may
    be inconsistent with the real draft state.
    """
    total_picks = engine.get_total_picks_made()
    return min(total_picks, len(draft_order_df))


def run_monte_carlo_snapshot(
    engine: DraftEngine,
    draft_order_csv: str,
    current_pick_index: int = None,
    n_simulations: int = 200,
    progress_callback=None,
    max_workers: int = None,
) -> dict:
    """Run N Monte Carlo simulations from the current draft state.

    The live DraftEngine is never mutated — each simulation operates on its
    own lightweight copy.  Already-completed picks are fast-forwarded by
    setting ``current_pick_index`` and marking drafted players as unavailable
    in the simulation copy.

    If the number of players per team is inconsistent with expectations given
    the draft order, the simulator will reconcile the differences automatically
    (clamping the pick index, skipping unresolvable picks, etc.) so that
    simulations always complete without errors.

    Args:
        engine: The live DraftEngine (read-only; copied per simulation).
        draft_order_csv: CSV string for the draft order.
        current_pick_index: Pick index to start each simulation from.  When
            ``None`` (recommended), the index is automatically inferred from
            the number of drafted players in the engine so that the snapshot
            is always consistent with the live draft state.
        n_simulations: Number of simulations to run (default 200).
        progress_callback: Optional ``callable(float)`` called after each
            simulation with the fraction completed ``[0, 1]``.
        max_workers: Number of parallel worker threads.  Defaults to
            ``min(4, n_simulations)``.  Pass 1 to run sequentially (useful
            for reproducible results with fixed random seeds).

    Returns:
        Dict with keys:
        - ``mean_standings``: DataFrame (teams × 10 categories), mean values.
        - ``std_standings``: DataFrame (teams × 10 categories), std values.
        - ``n_simulations``: int
        - ``current_pick_index``: int
    """
    if max_workers is None:
        max_workers = min(4, n_simulations)

    # Pre-compute boolean masks for drafted players from the *original* engine
    # so we can re-apply them to each simulation copy (snapshot copy preserves
    # all statuses, but drafted masks are re-applied for clarity/consistency).
    bat_drafted_mask = (engine.bat_df['Status'] == 'Drafted').values
    pitch_drafted_mask = (engine.pitch_df['Status'] == 'Drafted').values

    # Parse draft order CSV once and reuse across all simulations
    _tmp = DraftSimulator.__new__(DraftSimulator)
    draft_order_df = _tmp._parse_draft_order(draft_order_csv)

    # Auto-infer or clamp current_pick_index to avoid index-out-of-bounds
    if current_pick_index is None:
        current_pick_index = _reconcile_snapshot_pick_index(engine, draft_order_df)
    else:
        current_pick_index = max(0, min(int(current_pick_index), len(draft_order_df)))

    def _run_single_sim(i: int) -> pd.DataFrame:
        try:
            sim = DraftSimulator(
                engine=engine,
                draft_order_csv=draft_order_csv,
                user_team_name="__SNAPSHOT__",  # sentinel — matches no real team
                random_seed=i,
                snapshot_mode=True,
                draft_order_df=draft_order_df,
            )

            # Fast-forward past already-completed picks
            sim.current_pick_index = current_pick_index

            # Keep already-drafted players off the board so they are not re-picked
            sim.engine.bat_df.loc[bat_drafted_mask, 'Status'] = 'Drafted'
            sim.engine.pitch_df.loc[pitch_drafted_mask, 'Status'] = 'Drafted'

            sim.simulate_until_user_or_complete()

            return sim.get_standings().set_index('Team')
        except Exception as exc:
            # If a single simulation fails, log the error and return the
            # current standings from a fresh snapshot copy so the
            # aggregation still has the right shape.
            logger.warning("Snapshot simulation %d failed: %s", i, exc)
            fallback = DraftSimulator(
                engine=engine,
                draft_order_csv=draft_order_csv,
                user_team_name="__SNAPSHOT__",
                random_seed=i,
                snapshot_mode=True,
                draft_order_df=draft_order_df,
            )
            return fallback.get_standings().set_index('Team')

    all_standings = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_single_sim, i) for i in range(n_simulations)]
        for i, future in enumerate(futures, 1):
            all_standings.append(future.result())
            if progress_callback is not None:
                progress_callback(i / n_simulations)

    # Aggregate across simulations
    values = np.stack([df.values.astype(float) for df in all_standings])
    mean_vals = values.mean(axis=0)
    std_vals = values.std(axis=0)

    ref = all_standings[0]
    mean_standings = pd.DataFrame(mean_vals, index=ref.index, columns=ref.columns)
    std_standings = pd.DataFrame(std_vals, index=ref.index, columns=ref.columns)

    return {
        'mean_standings': mean_standings,
        'std_standings': std_standings,
        'n_simulations': n_simulations,
        'current_pick_index': current_pick_index,
    }
