from dataclasses import dataclass, field
from typing import List, Dict, Optional
import pandas as pd

@dataclass
class Player:
    player_id: str
    name: str
    position: str       # e.g., "SS" or "OF" or "SP" or "C/1B"
    team_mlb: str
    dollars: float
    stats: Dict[str, float]
    is_pitcher: bool
    is_writein: bool = False

@dataclass
class Team:
    owner_name: str
    roster: List[Player] = field(default_factory=list)
 
    
    # Define the Roster Constraints
    # Based on your list: 10 Batters, 6 Pitchers, 6 Bench = 22 Active Slots (plus IL/NA)
    # (If your league actually has 23, just adjust one of these numbers)
    SLOT_LIMITS = {
        'C': 1, '1B': 1, '2B': 1, '3B': 1, 'SS': 1,
        'OF': 3, 'Util': 2,
        'SP': 3, 'RP': 2, 'P': 1,
        'BN': 6,
        'IL': 5, 'NA': 2
    }

    def __post_init__(self):
        # Track filled slots dynamically
        self.slots_filled = {k: 0 for k in self.SLOT_LIMITS}
        # Position count cache: maps position string -> count of rostered players
        # eligible at that position.  Updated incrementally in add_player/remove_player.
        self.position_counts: Dict[str, int] = {}
        # Incremental totals cache for live_totals (avoids re-iterating roster)
        self._incr = {'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'K': 0, 'SV': 0, 'QS': 0}
        self._total_ab = 0
        self._total_on_base = 0.0
        self._total_ip = 0.0
        self._total_er = 0.0
        self._total_wh = 0.0

    def add_player(self, player: Player, is_keeper=False):
        """Adds a player and assigns them to the best available slot."""
        self.roster.append(player)

        # Update position count cache
        if not (pd.isna(player.position) or player.position is None):
            for p in str(player.position).split('/'):
                p = p.strip()
                self.position_counts[p] = self.position_counts.get(p, 0) + 1

        # Update incremental totals
        s = player.stats
        if not player.is_pitcher:
            self._incr['R'] += s.get('R', 0)
            self._incr['HR'] += s.get('HR', 0)
            self._incr['RBI'] += s.get('RBI', 0)
            self._incr['SB'] += s.get('SB', 0)
            ab = s.get('AB', 0)
            obp = s.get('OBP', 0)
            if ab > 0:
                self._total_ab += ab
                self._total_on_base += obp * ab
        else:
            self._incr['K'] += s.get('SO', 0)
            self._incr['SV'] += s.get('SV', 0)
            self._incr['QS'] += s.get('QS', 0)
            ip = s.get('IP', 0)
            era = s.get('ERA', 0)
            whip = s.get('WHIP', 0)
            if ip > 0:
                self._total_ip += ip
                self._total_er += (era * ip) / 9
                self._total_wh += whip * ip

        # --- SLOT ASSIGNMENT LOGIC ---
        # 1. Try Primary Position
        # Handle NaN/None positions
        if pd.isna(player.position) or player.position is None:
            # Default to generic position based on player type
            if player.is_pitcher:
                possible_pos = ['P']
            else:
                possible_pos = ['Util']
        else:
            # Clean position string (e.g., "C/1B" -> tries "C", then "1B")
            possible_pos = str(player.position).split('/') 
        
        assigned = False
        
        # Batters
        if not player.is_pitcher:
            # Try specific positions (C, 1B, 2B, 3B, SS, OF)
            for p in possible_pos:
                p = p.strip()
                if p in self.SLOT_LIMITS and self.slots_filled[p] < self.SLOT_LIMITS[p]:
                    self.slots_filled[p] += 1
                    assigned = True
                    break
            
            # Try Util
            if not assigned and self.slots_filled['Util'] < self.SLOT_LIMITS['Util']:
                self.slots_filled['Util'] += 1
                assigned = True

        # Pitchers
        else:
            # SP
            if 'SP' in possible_pos and self.slots_filled['SP'] < self.SLOT_LIMITS['SP']:
                self.slots_filled['SP'] += 1
                assigned = True
            # RP
            elif 'RP' in possible_pos and self.slots_filled['RP'] < self.SLOT_LIMITS['RP']:
                self.slots_filled['RP'] += 1
                assigned = True
            # P (Any Pitcher)
            if not assigned and self.slots_filled['P'] < self.SLOT_LIMITS['P']:
                self.slots_filled['P'] += 1
                assigned = True

        # Bench (Overflow for everyone)
        if not assigned and self.slots_filled['BN'] < self.SLOT_LIMITS['BN']:
            self.slots_filled['BN'] += 1
            assigned = True

    def remove_player(self, player_id: str, is_pitcher: bool = None) -> bool:
        """Removes a player from the roster and rebuilds slots_filled.
        
        Args:
            player_id: The unique identifier of the player to remove
            is_pitcher: Optional flag to distinguish between pitcher/batter with same ID.
                       If None, removes the first player with matching player_id.
            
        Returns:
            True if player was found and removed, False otherwise
        """
        # Find the player in the roster
        player_to_remove = None
        for player in self.roster:
            if player.player_id == player_id:
                # If is_pitcher is specified, also check that it matches
                if is_pitcher is None or player.is_pitcher == is_pitcher:
                    player_to_remove = player
                    break
        
        if player_to_remove is None:
            return False
        
        # Remove the player from the roster
        self.roster.remove(player_to_remove)
        
        # Rebuild all caches from scratch to ensure accuracy
        self.slots_filled = {k: 0 for k in self.SLOT_LIMITS}
        self.position_counts = {}
        self._incr = {'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'K': 0, 'SV': 0, 'QS': 0}
        self._total_ab = 0
        self._total_on_base = 0.0
        self._total_ip = 0.0
        self._total_er = 0.0
        self._total_wh = 0.0
        
        # Re-add all remaining players to recalculate slot assignments
        remaining_players = self.roster.copy()
        self.roster = []
        
        for player in remaining_players:
            self.add_player(player)
        
        return True

    @property
    def live_totals(self) -> Dict[str, float]:
        """Returns the 5x5 category totals from incremental cache."""
        totals = {
            'R': self._incr['R'], 'HR': self._incr['HR'],
            'RBI': self._incr['RBI'], 'SB': self._incr['SB'], 'OBP': 0.000,
            'K': self._incr['K'], 'SV': self._incr['SV'],
            'QS': self._incr['QS'], 'ERA': 0.00, 'WHIP': 0.00
        }

        if self._total_ab > 0:
            totals['OBP'] = round(self._total_on_base / self._total_ab, 3)
        if self._total_ip > 0:
            totals['ERA'] = round((self._total_er * 9) / self._total_ip, 2)
            totals['WHIP'] = round(self._total_wh / self._total_ip, 2)

        return totals