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