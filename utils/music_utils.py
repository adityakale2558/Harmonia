from typing import List, Optional
import time

class Song:
    """Class representing a song in the music queue."""
    
    def __init__(self, title: str, url: Optional[str], duration: Optional[int] = None,
                 webpage_url: Optional[str] = None, thumbnail: Optional[str] = None,
                 uploader: str = "Unknown", is_spotify: bool = False, search_query: Optional[str] = None):
        self.title = title  # Song title
        self.url = url  # Direct audio URL for playback
        self.duration = duration  # Duration in seconds
        self.webpage_url = webpage_url  # URL of the webpage (e.g., YouTube video)
        self.thumbnail = thumbnail  # URL to the song thumbnail
        self.uploader = uploader  # Name of the uploader (e.g., YouTube channel)
        self.is_spotify = is_spotify  # Whether this song is from Spotify
        self.search_query = search_query  # Search query for Spotify songs to find on YouTube
        self.added_at = time.time()  # Time when the song was added to the queue
    
    def __str__(self):
        return f"Song({self.title}, duration={self.duration}s, is_spotify={self.is_spotify})"

class MusicQueue:
    """Class for managing the music queue."""
    
    def __init__(self):
        self.songs: List[Song] = []  # List of songs in the queue
        self.current_index = 0  # Index of the current song
        self.volume = 0.5  # Volume level (0.0 to 1.0)
        self.loop_mode = False  # Whether to loop the queue
    
    def add(self, song: Song) -> None:
        """Add a song to the queue."""
        self.songs.append(song)
    
    def clear(self) -> None:
        """Clear the queue."""
        self.songs = []
        self.current_index = 0
    
    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self.songs) == 0
    
    @property
    def current_song(self) -> Optional[Song]:
        """Get the current song."""
        if 0 <= self.current_index < len(self.songs):
            return self.songs[self.current_index]
        return None
    
    def get_next_song(self) -> Optional[Song]:
        """Get the next song in the queue."""
        if self.is_empty():
            return None
        
        # Return the current song and increment the index
        song = self.current_song
        
        # Increment the index for the next song
        if self.loop_mode and self.current_index == len(self.songs) - 1:
            # If looping and at the end, go back to the beginning
            self.current_index = 0
        else:
            # Otherwise, move to the next song
            self.current_index = min(self.current_index + 1, len(self.songs) - 1)
        
        return song
    
    def remove(self, index: int) -> Optional[Song]:
        """Remove a song from the queue by index."""
        if 0 <= index < len(self.songs):
            song = self.songs.pop(index)
            
            # Adjust current_index if necessary
            if index < self.current_index:
                self.current_index -= 1
            
            return song
        return None
    
    def shuffle(self) -> None:
        """Shuffle the queue (except the current song)."""
        import random
        
        # Don't shuffle if queue is empty or has only one song
        if len(self.songs) <= 1:
            return
        
        # Keep the current song, shuffle the rest
        current = self.current_song
        
        # Remove current song
        if current:
            self.songs.pop(self.current_index)
        
        # Shuffle remaining songs
        random.shuffle(self.songs)
        
        # Put current song back at the beginning
        if current:
            self.songs.insert(0, current)
            self.current_index = 0
    
    def next_song(self) -> Optional[Song]:
        """Skip to the next song in the queue."""
        if self.is_empty() or self.current_index >= len(self.songs) - 1:
            if self.loop_mode and not self.is_empty():
                # If looping, go back to the beginning
                self.current_index = 0
                return self.current_song
            return None
        
        # Move to the next song
        self.current_index += 1
        return self.current_song
    
    def previous_song(self) -> Optional[Song]:
        """Go back to the previous song in the queue."""
        if self.is_empty() or self.current_index <= 0:
            return None
        
        # Move to the previous song
        self.current_index -= 1
        return self.current_song
    
    def __len__(self) -> int:
        """Get the number of songs in the queue."""
        return len(self.songs)
