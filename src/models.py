from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd

@dataclass
class Player:
    """Represents a single player and their stats."""
    player_id: str
    name: str
    position: str
    team_mlb: str
    dollars: float  # <--- Added this field
    stats: Dict[str, float]
    is_pitcher: bool

@dataclass
class Team:
    """Represents a fantasy team (yours or opponents)."""
    owner_name: str
    roster: List[Player] = field(default_factory=list)
    
    def add_player(self, player: Player):
        self.roster.append(player)

    @property
    def live_totals(self) -> Dict[str, float]:
        """
        Calculates the 5x5 category totals for the current roster.
        """
        # Initialize the 5x5 counters
        totals = {
            # Batting
            'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'OBP': 0.000,
            # Pitching
            'K': 0, 'SV': 0, 'QS': 0, 'ERA': 0.00, 'WHIP': 0.00
        }
        
        # Intermediate variables for Rate Stats
        # Batting OBP
        total_ab = 0
        total_on_base_events = 0 # Approx: OBP * AB 
        
        # Pitching ERA/WHIP
        total_ip = 0.0
        total_earned_runs = 0.0
        total_walks_hits = 0.0

        for p in self.roster:
            s = p.stats
            
            if not p.is_pitcher:
                # 1. Batting Counting Stats
                totals['R'] += s.get('R', 0)
                totals['HR'] += s.get('HR', 0)
                totals['RBI'] += s.get('RBI', 0)
                totals['SB'] += s.get('SB', 0)
                
                # 2. Batting Rate Stat (OBP)
                # We weight OBP by AB (At Bats) since PA isn't always in the CSV
                ab = s.get('AB', 0)
                obp = s.get('OBP', 0)
                if ab > 0:
                    total_ab += ab
                    total_on_base_events += (obp * ab)

            else:
                # 3. Pitching Counting Stats
                totals['K'] += s.get('SO', 0)  # 'SO' in CSV maps to 'K'
                totals['SV'] += s.get('SV', 0)
                totals['QS'] += s.get('QS', 0)
                
                # 4. Pitching Rate Stats (ERA/WHIP)
                # We must reverse-engineer the components to average them correctly
                ip = s.get('IP', 0)
                era = s.get('ERA', 0)
                whip = s.get('WHIP', 0)
                
                if ip > 0:
                    total_ip += ip
                    # ER = (ERA * IP) / 9
                    total_earned_runs += (era * ip) / 9
                    # Walks + Hits = WHIP * IP
                    total_walks_hits += (whip * ip)

        # Finalize Rate Stats Calculation
        if total_ab > 0:
            totals['OBP'] = round(total_on_base_events / total_ab, 3)
            
        if total_ip > 0:
            totals['ERA'] = round((total_earned_runs * 9) / total_ip, 2)
            totals['WHIP'] = round(total_walks_hits / total_ip, 2)

        return totals