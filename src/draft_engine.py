import pandas as pd
from .models import Team, Player

class DraftEngine:
    def __init__(self, bat_df, pitch_df):
        self.bat_df = bat_df
        self.pitch_df = pitch_df
        
        # Initialize Status Columns
        self.bat_df['Status'] = 'Available'
        self.bat_df['DraftedBy'] = None
        self.pitch_df['Status'] = 'Available'
        self.pitch_df['DraftedBy'] = None
        
        # Initialize Teams (You can customize these names)
        team_names = ["My Team", "Team 2", "Team 3", "Team 4", "Team 5", 
                      "Team 6", "Team 7", "Team 8", "Team 9", "Team 10", "Team 11", "Team 12"]
        self.teams = {name: Team(name) for name in team_names}

    def process_keeper(self, player_id, team_name, cost=0.0):
        """Forces a player onto a team as a keeper."""
        # Find if player is Batter or Pitcher
        is_pitcher = False
        row = None
        
        # Check Pitchers
        if player_id in self.pitch_df['PlayerId'].values:
            is_pitcher = True
            mask = self.pitch_df['PlayerId'] == player_id
            self.pitch_df.loc[mask, 'Status'] = 'Keeper' # Mark as Keeper
            self.pitch_df.loc[mask, 'DraftedBy'] = team_name
            row = self.pitch_df.loc[mask].iloc[0]
            
        # Check Batters
        elif player_id in self.bat_df['PlayerId'].values:
            mask = self.bat_df['PlayerId'] == player_id
            self.bat_df.loc[mask, 'Status'] = 'Keeper'
            self.bat_df.loc[mask, 'DraftedBy'] = team_name
            row = self.bat_df.loc[mask].iloc[0]
            
        else:
            return False # Player not found

        # Create Player Object
        stats = row.to_dict()
        new_player = Player(
            player_id=str(row['PlayerId']),
            name=row['Name'],
            position=row['POS'],
            team_mlb=row['Team'],
            dollars=row.get('Dollars', 0),  # Keeper Cost
            stats=stats,
            is_pitcher=is_pitcher
        )
        
        # Add to Team (Mark as keeper)
        self.teams[team_name].add_player(new_player, is_keeper=True)
        return True
    
    def process_pick(self, player_id, team_name, is_pitcher):
        """Updates the dataframe and adds player to the specific Team object."""
        
        # 1. Update the DataFrame (Source of Truth for Plots)
        if is_pitcher:
            mask = self.pitch_df['PlayerId'] == player_id
            self.pitch_df.loc[mask, 'Status'] = 'Drafted'
            self.pitch_df.loc[mask, 'DraftedBy'] = team_name
            row = self.pitch_df.loc[mask].iloc[0]
        else:
            mask = self.bat_df['PlayerId'] == player_id
            self.bat_df.loc[mask, 'Status'] = 'Drafted'
            self.bat_df.loc[mask, 'DraftedBy'] = team_name
            row = self.bat_df.loc[mask].iloc[0]

        # 2. Add to Team Object (Source of Truth for Standings)
        # Convert row to dictionary for the Player class
        stats = row.to_dict()
        
        new_player = Player(
            player_id=str(row['PlayerId']),
            name=row['Name'],
            position=row['POS'],
            team_mlb=row['Team'],
            dollars=row.get('Dollars', 0),  # <--- Pass the dollar value here
            stats=stats,
            is_pitcher=is_pitcher
        )
        
        self.teams[team_name].add_player(new_player)

    def undo_pick(self, player_id: str) -> bool:
        """Undoes a draft pick by reverting the player to Available status.
        
        Args:
            player_id: The unique identifier of the player to undo
            
        Returns:
            True if the pick was successfully undone, False otherwise
        """
        # Determine if player is a batter or pitcher and check if they're drafted
        is_pitcher = None
        df = None
        
        # Check pitchers
        if player_id in self.pitch_df['PlayerId'].values:
            mask = self.pitch_df['PlayerId'] == player_id
            row = self.pitch_df.loc[mask].iloc[0]
            
            # Only undo if status is 'Drafted' (not 'Keeper')
            if row['Status'] == 'Drafted':
                is_pitcher = True
                df = self.pitch_df
            else:
                return False  # Cannot undo keepers or available players
        
        # Check batters
        elif player_id in self.bat_df['PlayerId'].values:
            mask = self.bat_df['PlayerId'] == player_id
            row = self.bat_df.loc[mask].iloc[0]
            
            # Only undo if status is 'Drafted' (not 'Keeper')
            if row['Status'] == 'Drafted':
                is_pitcher = False
                df = self.bat_df
            else:
                return False  # Cannot undo keepers or available players
        else:
            return False  # Player not found
        
        # Reset DataFrame status
        mask = df['PlayerId'] == player_id
        df.loc[mask, 'Status'] = 'Available'
        df.loc[mask, 'DraftedBy'] = None
        
        # Find which team has this player and remove from roster
        player_removed = False
        for team_name, team in self.teams.items():
            if team.remove_player(player_id):
                player_removed = True
                break
        
        return player_removed

    def get_standings(self):
        """Returns a DataFrame of the current 5x5 standings."""
        data = []
        for name, team in self.teams.items():
            totals = team.live_totals
            totals['Team'] = name
            data.append(totals)
        
        df = pd.DataFrame(data)
        # Reorder columns to put Team first
        cols = ['Team'] + [c for c in df.columns if c != 'Team']
        return df[cols]

    def get_team_roster_df(self, team_name):
        """Returns a pandas DataFrame of a team's current roster for display.
        
        Each row includes:
        - Name: player name
        - POS: position
        - MLB Team: MLB team abbreviation
        - Type: "Batter" or "Pitcher"
        - Dollars: auction dollar value
        
        The DataFrame is sorted by Type (Batters first), then POS, then Name.
        """
        team = self.teams.get(team_name)
        if not team:
            return pd.DataFrame()
        
        roster_data = []
        for player in team.roster:
            # Handle NaN/None values for display
            pos = player.position if not pd.isna(player.position) else 'Unknown'
            mlb_team = player.team_mlb if not pd.isna(player.team_mlb) else 'N/A'
            
            roster_data.append({
                'Name': player.name,
                'POS': pos,
                'MLB Team': mlb_team,
                'Type': 'Pitcher' if player.is_pitcher else 'Batter',
                'Dollars': player.dollars
            })
        
        df = pd.DataFrame(roster_data)
        if df.empty:
            return df
        
        # Sort by Type (Batters first), then POS, then Name
        df = df.sort_values(by=['Type', 'POS', 'Name'], ascending=[True, True, True])
        return df.reset_index(drop=True)

    def get_roster_summary(self, team_name):
        """Returns a dictionary summarizing filled vs. total slots for a team.
        
        For each slot in Team.SLOT_LIMITS, returns {'filled': <int>, 'limit': <int>}.
        """
        team = self.teams.get(team_name)
        if not team:
            return {}
        
        summary = {}
        for slot, limit in Team.SLOT_LIMITS.items():
            summary[slot] = {
                'filled': team.slots_filled.get(slot, 0),
                'limit': limit
            }
        
        return summary