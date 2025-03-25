import time
from typing import Dict, List, Optional, Set

class Player:
    """Class representing a player in the 'Guess It' game."""
    
    def __init__(self, id: int, name: str):
        self.id = id  # Discord user ID
        self.name = name  # Discord display name
        self.actor = None  # The actor assigned to this player
        self.has_guessed_correctly = False  # Whether the player has guessed their actor
        self.guess_count = 0  # Number of guess attempts used
    
    def __str__(self):
        return f"Player({self.name}, actor={self.actor})"

class GameSession:
    """Class representing a game session for the 'Guess It' game."""
    
    def __init__(self, host_id: int, channel_id: int, category: str):
        self.host_id = host_id  # ID of the user who started the game
        self.channel_id = channel_id  # ID of the channel where the game is played
        self.category = category  # Actor category (e.g., "Hollywood", "Bollywood")
        self.players: List[Player] = []  # List of players in the game
        self.is_in_progress = False  # Whether actors have been assigned
        self.last_activity = time.time()  # Time of last activity in the game
    
    def add_player(self, player: Player) -> None:
        """Add a player to the game."""
        self.players.append(player)
        self.last_activity = time.time()
    
    def get_player(self, player_id: int) -> Optional[Player]:
        """Get a player by their Discord ID."""
        for player in self.players:
            if player.id == player_id:
                return player
        return None
    
    def remove_player(self, player_id: int) -> bool:
        """Remove a player from the game."""
        player = self.get_player(player_id)
        if player:
            self.players.remove(player)
            self.last_activity = time.time()
            return True
        return False
    
    def assign_actors(self, actors: List[str]) -> None:
        """Assign actors to players."""
        if len(actors) < len(self.players):
            raise ValueError("Not enough actors for all players")
        
        for i, player in enumerate(self.players):
            player.actor = actors[i]
        
        self.is_in_progress = True
        self.last_activity = time.time()
    
    def all_guessed_correctly(self) -> bool:
        """Check if all players have guessed their actors correctly."""
        return all(player.has_guessed_correctly for player in self.players)
    
    def __str__(self):
        return f"GameSession(host={self.host_id}, players={len(self.players)}, in_progress={self.is_in_progress})"
