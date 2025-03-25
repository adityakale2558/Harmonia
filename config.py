import os

class Config:
    """Configuration settings for the Discord bot."""
    
    # Bot command prefix
    PREFIX = os.environ.get("COMMAND_PREFIX", "!")
    
    # Default volume for music playback (0-100)
    DEFAULT_VOLUME = 50
    
    # Maximum number of songs in the queue
    MAX_QUEUE_SIZE = 100
    
    # Actor game settings
    GAME_TIMEOUT = 300  # 5 minutes in seconds
    MAX_PLAYERS = 10
    MIN_PLAYERS = 2
    
    # API endpoints and URLs
    LYRICS_API_URL = "https://api.lyrics.ovh/v1"
    
    # Spotify API credentials
    SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
