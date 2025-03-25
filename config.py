import os

# Bot configuration
PREFIX = os.getenv("COMMAND_PREFIX", "=")

# Game settings
MIN_PLAYERS = 2
MAX_PLAYERS = 10
GAME_TIMEOUT = 300  # 5 minutes of inactivity
GUESS_LIMIT = 3     # Number of guess attempts per player

# Actor game categories
CATEGORIES = ["Hollywood", "Bollywood", "Apps", "Food"]

# Music bot settings
DEFAULT_VOLUME = 0.5  # 50%
MAX_QUEUE_SIZE = 100
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY", "")
