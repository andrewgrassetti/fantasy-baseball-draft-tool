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

    def add_player(self, player: Player, is_keeper=False):
        """Adds a player and assigns them to the best available slot."""
        self.roster.append(player)
        
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

    @property
    def live_totals(self) -> Dict[str, float]:
        """Calculates the 5x5 category totals."""
        # ... (This method remains the same as previous step) ...
        # Copy the previous `live_totals` logic here!
        totals = {
            'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'OBP': 0.000,
            'K': 0, 'SV': 0, 'WAR': 0, 'ERA': 0.00, 'WHIP': 0.00
        }
        
        total_ab = 0; total_on_base = 0
        total_ip = 0.0; total_er = 0.0; total_wh = 0.0

        for p in self.roster:
            s = p.stats
            if not p.is_pitcher:
                totals['R'] += s.get('R', 0); totals['HR'] += s.get('HR', 0)
                totals['RBI'] += s.get('RBI', 0); totals['SB'] += s.get('SB', 0)
                ab = s.get('AB', 0); obp = s.get('OBP', 0)
                if ab > 0: total_ab += ab; total_on_base += (obp * ab)
            else:
                totals['K'] += s.get('SO', 0); totals['SV'] += s.get('SV', 0)
                totals['WAR'] += s.get('WAR', 0)
                ip = s.get('IP', 0); era = s.get('ERA', 0); whip = s.get('WHIP', 0)
                if ip > 0: total_ip += ip; total_er += (era * ip) / 9; total_wh += (whip * ip)

        if total_ab > 0: totals['OBP'] = round(total_on_base / total_ab, 3)
        if total_ip > 0:
            totals['ERA'] = round((total_er * 9) / total_ip, 2)
            totals['WHIP'] = round(total_wh / total_ip, 2)

        return totals