import json
import os
from datetime import datetime
from typing import Dict, List, Optional
import re


def _sanitize_filename(name: str) -> str:
    """Sanitize a configuration name to create a valid filename.
    
    Args:
        name: The configuration name to sanitize
        
    Returns:
        A sanitized filename safe for use in filesystems
    """
    # Replace spaces with underscores, remove special characters
    sanitized = re.sub(r'[^\w\s-]', '', name)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized


def save_keeper_config(name: str, team_names: List[str], keepers: Dict[str, List[Dict]], 
                       saves_dir: str = "saves") -> str:
    """Save a keeper configuration to a JSON file.
    
    Args:
        name: Name of the configuration (e.g., "Keepers 2026")
        team_names: List of team names
        keepers: Dictionary mapping team names to lists of keeper dicts
                 Each keeper dict should have 'player_id' and 'cost' keys
        saves_dir: Directory to save configurations to (default: "saves")
        
    Returns:
        The full file path where the configuration was saved
    """
    # Create saves directory if it doesn't exist
    os.makedirs(saves_dir, exist_ok=True)
    
    # Create configuration dictionary
    config = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "team_names": team_names,
        "keepers": keepers
    }
    
    # Create filename
    sanitized_name = _sanitize_filename(name)
    filename = f"{sanitized_name}.json"
    filepath = os.path.join(saves_dir, filename)
    
    # Save to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    return filepath


def load_keeper_config(filepath: str) -> Dict:
    """Load a keeper configuration from a JSON file.
    
    Args:
        filepath: Path to the configuration file
        
    Returns:
        Dictionary containing the configuration with keys:
        - name: Configuration name
        - created_at: ISO timestamp of creation
        - team_names: List of team names
        - keepers: Dictionary of keeper assignments
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    return config


def list_saved_configs(saves_dir: str = "saves") -> List[Dict]:
    """List all saved keeper configurations.
    
    Args:
        saves_dir: Directory containing saved configurations
        
    Returns:
        List of dictionaries, each containing:
        - name: Configuration name
        - filename: The actual filename (e.g., "Keepers_2026.json")
        - filepath: Full path to the configuration file
        - created_at: ISO timestamp of creation
        
        Returns empty list if no configurations exist or directory doesn't exist.
    """
    if not os.path.exists(saves_dir):
        return []
    
    configs = []
    
    # Find all JSON files in the saves directory
    for filename in os.listdir(saves_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(saves_dir, filename)
            
            try:
                # Load the config to get metadata
                config = load_keeper_config(filepath)
                configs.append({
                    "name": config.get("name", filename),
                    "filename": filename,
                    "filepath": filepath,
                    "created_at": config.get("created_at", "Unknown")
                })
            except (json.JSONDecodeError, KeyError, FileNotFoundError):
                # Skip invalid files
                continue
    
    # Sort by created_at timestamp, most recent first
    configs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return configs


def delete_keeper_config(filepath: str) -> bool:
    """Delete a saved keeper configuration.
    
    Args:
        filepath: Path to the configuration file to delete
        
    Returns:
        True if the file was successfully deleted, False otherwise
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False
    except (OSError, PermissionError):
        return False
