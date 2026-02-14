import pandas as pd
from .models import Team, Player

class DraftEngine:
    def __init__(self, bat_df, pitch_df, team_names=None):
        self.bat_df = bat_df
        self.pitch_df = pitch_df
        
        # Initialize Status Columns
        self.bat_df['Status'] = 'Available'
        self.bat_df['DraftedBy'] = None
        self.pitch_df['Status'] = 'Available'
        self.pitch_df['DraftedBy'] = None
        
        # Initialize Teams (Use provided names or defaults)
        if team_names is None:
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
        df = None
        
        # Check pitchers
        if player_id in self.pitch_df['PlayerId'].values:
            mask = self.pitch_df['PlayerId'] == player_id
            row = self.pitch_df.loc[mask].iloc[0]
            
            # Only undo if status is 'Drafted' (not 'Keeper')
            if row['Status'] == 'Drafted':
                df = self.pitch_df
            else:
                return False  # Cannot undo keepers or available players
        
        # Check batters
        elif player_id in self.bat_df['PlayerId'].values:
            mask = self.bat_df['PlayerId'] == player_id
            row = self.bat_df.loc[mask].iloc[0]
            
            # Only undo if status is 'Drafted' (not 'Keeper')
            if row['Status'] == 'Drafted':
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
        for team_name, team in self.teams.items():
            if team.remove_player(player_id):
                return True
        
        return False

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

    def set_team_names(self, new_names: list):
        """Reconfigure teams with new names, preserving existing rosters where possible.
        
        Args:
            new_names: List of new team names
            
        Behavior:
        - Preserves rosters for teams whose names still exist
        - Creates new Team objects for new names
        - Reverts players from removed teams to Available status
        """
        old_teams = self.teams
        new_teams = {}
        
        # Create new team dict, preserving existing teams where names match
        for name in new_names:
            if name in old_teams:
                # Preserve existing team
                new_teams[name] = old_teams[name]
            else:
                # Create new team
                new_teams[name] = Team(name)
        
        # For teams that were removed, revert their players to Available
        removed_teams = set(old_teams.keys()) - set(new_names)
        for removed_name in removed_teams:
            removed_team = old_teams[removed_name]
            for player in removed_team.roster:
                # Find player in appropriate DataFrame and reset status
                if player.is_pitcher:
                    mask = self.pitch_df['PlayerId'] == player.player_id
                    self.pitch_df.loc[mask, 'Status'] = 'Available'
                    self.pitch_df.loc[mask, 'DraftedBy'] = None
                else:
                    mask = self.bat_df['PlayerId'] == player.player_id
                    self.bat_df.loc[mask, 'Status'] = 'Available'
                    self.bat_df.loc[mask, 'DraftedBy'] = None
        
        self.teams = new_teams

    def remove_keeper(self, player_id: str) -> bool:
        """Remove a keeper assignment and return the player to Available status.
        
        Args:
            player_id: The unique identifier of the keeper to remove
            
        Returns:
            True if the keeper was successfully removed, False otherwise
        """
        # Find the player and check if they're a keeper
        df = None
        
        # Check pitchers
        if player_id in self.pitch_df['PlayerId'].values:
            mask = self.pitch_df['PlayerId'] == player_id
            row = self.pitch_df.loc[mask].iloc[0]
            
            # Only remove if status is 'Keeper'
            if row['Status'] == 'Keeper':
                df = self.pitch_df
            else:
                return False  # Not a keeper
        
        # Check batters
        elif player_id in self.bat_df['PlayerId'].values:
            mask = self.bat_df['PlayerId'] == player_id
            row = self.bat_df.loc[mask].iloc[0]
            
            # Only remove if status is 'Keeper'
            if row['Status'] == 'Keeper':
                df = self.bat_df
            else:
                return False  # Not a keeper
        else:
            return False  # Player not found
        
        # Reset DataFrame status
        mask = df['PlayerId'] == player_id
        df.loc[mask, 'Status'] = 'Available'
        df.loc[mask, 'DraftedBy'] = None
        
        # Find which team has this player and remove from roster
        for team_name, team in self.teams.items():
            if team.remove_player(player_id):
                return True
        
        return False

    def export_keeper_config(self) -> dict:
        """Export current keeper configuration for persistence.
        
        Returns:
            Dictionary with keys:
            - team_names: List of team names
            - keepers: Dict mapping team names to lists of keeper dicts
                      Each keeper dict has 'player_id' and 'cost' keys
        """
        keepers = {}
        
        for team_name, team in self.teams.items():
            team_keepers = []
            for player in team.roster:
                # Check if player is a keeper by looking at their status in DataFrame
                if player.is_pitcher:
                    mask = self.pitch_df['PlayerId'] == player.player_id
                    if not self.pitch_df.loc[mask].empty:
                        status = self.pitch_df.loc[mask, 'Status'].iloc[0]
                        if status == 'Keeper':
                            team_keepers.append({
                                "player_id": player.player_id,
                                "cost": player.dollars
                            })
                else:
                    mask = self.bat_df['PlayerId'] == player.player_id
                    if not self.bat_df.loc[mask].empty:
                        status = self.bat_df.loc[mask, 'Status'].iloc[0]
                        if status == 'Keeper':
                            team_keepers.append({
                                "player_id": player.player_id,
                                "cost": player.dollars
                            })
            
            if team_keepers:
                keepers[team_name] = team_keepers
        
        return {
            "team_names": list(self.teams.keys()),
            "keepers": keepers
        }

    def import_keeper_config(self, config: dict) -> bool:
        """Import keeper configuration from a dict.
        
        Args:
            config: Dictionary with keys:
                   - team_names: List of team names
                   - keepers: Dict mapping team names to lists of keeper dicts
                   
        Returns:
            True if import was successful, False otherwise
        """
        try:
            # First, set team names
            team_names = config.get("team_names", [])
            if not team_names:
                return False
            
            self.set_team_names(team_names)
            
            # Then, process keepers
            keepers = config.get("keepers", {})
            for team_name, keeper_list in keepers.items():
                if team_name not in self.teams:
                    continue  # Skip if team doesn't exist
                
                for keeper_data in keeper_list:
                    player_id = keeper_data.get("player_id")
                    cost = keeper_data.get("cost", 0.0)
                    
                    if player_id:
                        self.process_keeper(player_id, team_name, cost)
            
            return True
            
        except Exception:
            return False