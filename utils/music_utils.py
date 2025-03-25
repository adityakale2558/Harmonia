import discord
import aiohttp
import logging
import re
from typing import Dict, List, Tuple, Optional
from config import Config

logger = logging.getLogger("discord_bot.music_utils")

async def get_lyrics(song_name: str) -> Optional[str]:
    """
    Fetch lyrics for a song from the lyrics.ovh API.
    
    Args:
        song_name: The name of the song to find lyrics for
    
    Returns:
        The lyrics text if found, None otherwise
    """
    # Clean up the song name
    # Remove featuring artists, official video, etc.
    cleaned_name = re.sub(r'\(feat\..*?\)|\(ft\..*?\)|\(official.*?\)|\(lyrics.*?\)|\(audio.*?\)|HD|HQ|[0-9]{4}|official|video|audio|lyrics', '', song_name, flags=re.IGNORECASE)
    cleaned_name = cleaned_name.strip()
    
    # Try to split artist and title
    parts = cleaned_name.split(' - ', 1)
    if len(parts) == 2:
        artist, title = parts
    else:
        # Try to make a best guess at artist/title split
        words = cleaned_name.split()
        if len(words) <= 3:
            # If 3 or fewer words, use the whole thing as title
            artist = ""
            title = cleaned_name
        else:
            # Use first word as artist, rest as title (not ideal but a fallback)
            artist = words[0]
            title = ' '.join(words[1:])
    
    # Remove any remaining parentheses
    title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    
    logger.info(f"Searching for lyrics: Artist='{artist}', Title='{title}'")
    
    # Try with artist and title if we have both
    if artist and title:
        lyrics = await _fetch_lyrics(artist, title)
        if lyrics:
            return lyrics
    
    # Try with just the title
    if title:
        lyrics = await _fetch_lyrics("", title)
        if lyrics:
            return lyrics
    
    # Try with the original query as a last resort
    return await _fetch_lyrics("", cleaned_name)

async def _fetch_lyrics(artist: str, title: str) -> Optional[str]:
    """
    Make a request to the lyrics API.
    
    Args:
        artist: The artist name (can be empty)
        title: The song title
    
    Returns:
        The lyrics text if found, None otherwise
    """
    # If artist is empty, use the title as the full query
    if not artist:
        endpoint = f"{Config.LYRICS_API_URL}/{title}"
    else:
        endpoint = f"{Config.LYRICS_API_URL}/{artist}/{title}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('lyrics')
                else:
                    logger.warning(f"Failed to fetch lyrics: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching lyrics: {e}")
        return None

def create_queue_embed(queue: List[Dict], current_index: int, loop: bool) -> discord.Embed:
    """
    Create an embed to display the music queue.
    
    Args:
        queue: The list of tracks in the queue
        current_index: The index of the current track
        loop: Whether loop mode is enabled
    
    Returns:
        Discord embed with the queue information
    """
    embed = discord.Embed(
        title="🎵 Music Queue",
        color=discord.Color.blue()
    )
    
    # Add current track
    if current_index < len(queue):
        current = queue[current_index]
        embed.add_field(
            name="Now Playing",
            value=f"**{current['title']}** [{format_duration(current['duration'])}] - Requested by {current['requester'].mention}",
            inline=False
        )
    
    # Add upcoming tracks (maximum 10)
    if current_index + 1 < len(queue):
        upcoming = queue[current_index + 1:current_index + 11]
        upcoming_text = ""
        
        for i, track in enumerate(upcoming):
            upcoming_text += f"{i + 1}. **{track['title']}** [{format_duration(track['duration'])}] - {track['requester'].mention}\n"
        
        embed.add_field(
            name="Up Next",
            value=upcoming_text if upcoming_text else "No upcoming tracks",
            inline=False
        )
        
        # If there are more tracks than what's displayed
        remaining = len(queue) - current_index - len(upcoming) - 1
        if remaining > 0:
            embed.add_field(
                name="And More",
                value=f"{remaining} more tracks in queue",
                inline=False
            )
    
    # Add queue info
    total_duration = sum(track['duration'] for track in queue)
    embed.add_field(name="Total Tracks", value=len(queue), inline=True)
    embed.add_field(name="Total Duration", value=format_duration(total_duration), inline=True)
    embed.add_field(name="Loop Mode", value="Enabled" if loop else "Disabled", inline=True)
    
    return embed

def format_duration(seconds: int) -> str:
    """
    Format a duration in seconds to a string (MM:SS or HH:MM:SS).
    
    Args:
        seconds: The duration in seconds
    
    Returns:
        Formatted duration string
    """
    if not seconds or seconds <= 0:
        return "00:00"
    
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"
