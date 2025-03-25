import aiohttp
import logging
import re
import html
import asyncio
from typing import Dict, Optional, Any, List, Tuple
import json
import time

logger = logging.getLogger('discord_bot.lyrics_fetcher')

class LyricsCache:
    """Simple in-memory cache for lyrics to avoid repeated API calls."""
    def __init__(self, max_size=100, expiry_time=3600):  # Cache entries expire after 1 hour
        self.cache = {}
        self.max_size = max_size
        self.expiry_time = expiry_time
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get item from cache if it exists and is not expired."""
        if key in self.cache:
            timestamp, data = self.cache[key]
            if time.time() - timestamp < self.expiry_time:
                return data
            # Remove expired entry
            del self.cache[key]
        return None
    
    def set(self, key: str, value: Dict[str, Any]) -> None:
        """Add item to cache with current timestamp."""
        # If cache is full, remove oldest entry
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        self.cache[key] = (time.time(), value)

# Initialize global cache
lyrics_cache = LyricsCache()

async def fetch_lyrics(query: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch lyrics for a song using the Genius API.
    
    Args:
        query: Song name to search for
        api_key: Optional Genius API key
    
    Returns:
        Dictionary containing lyrics, title, and artist information
    """
    # Check cache first
    cache_key = f"{query}:{api_key is not None}"
    cached_result = lyrics_cache.get(cache_key)
    if cached_result:
        logger.info(f"Lyrics cache hit for: {query}")
        return cached_result
    
    # Clean the query
    cleaned_query = clean_query(query)
    
    # Try to use Genius API if a key is provided
    if api_key:
        try:
            result = await fetch_from_genius(cleaned_query, api_key)
            # Cache successful result
            lyrics_cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Error using Genius API: {e}")
            # Fall back to alternative method if Genius fails
    
    # Fallback method: Simple web scraping or other free services
    try:
        fallback_result = await fetch_from_alternative_source(cleaned_query)
        # Only cache successful results
        if fallback_result.get("lyrics") and not fallback_result["lyrics"].startswith("Lyrics for"):
            lyrics_cache.set(cache_key, fallback_result)
        return fallback_result
    except Exception as e:
        logger.error(f"Error using alternative lyrics source: {e}")
        error_result = {
            "lyrics": "", 
            "title": query, 
            "artist": "Unknown", 
            "error": str(e),
            "source": "Error"
        }
        return error_result

def clean_query(query: str) -> str:
    """Clean up the search query for better results."""
    # Remove common keywords that might interfere with lyrics search
    query = re.sub(r'(?i)(official\s*video|lyrics\s*video|audio|official|extended|remix|ft\..*|feat\..*)', '', query)
    
    # Remove anything in parentheses or brackets
    query = re.sub(r'[\(\[\{].*?[\)\]\}]', '', query)
    
    # Remove any special characters and extra whitespace
    query = re.sub(r'[^\w\s\-]', '', query)
    query = re.sub(r'\s+', ' ', query).strip()
    
    return query

async def fetch_from_genius(query: str, api_key: str) -> Dict[str, Any]:
    """Fetch lyrics using the Genius API."""
    # First, search for the song
    search_url = f"https://api.genius.com/search?q={query}"
    
    async with aiohttp.ClientSession() as session:
        # Add timeout to prevent hanging
        try:
            async with session.get(
                search_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            ) as resp:
                if resp.status != 200:
                    error_msg = await resp.text()
                    logger.warning(f"Genius API search failed: {resp.status} - {error_msg}")
                    raise Exception(f"Failed to search for lyrics: Status {resp.status}")
                
                data = await resp.json()
                
                # Check if we got any hits
                hits = data.get('response', {}).get('hits', [])
                if not hits:
                    return {
                        "lyrics": f"No lyrics found for '{query}'", 
                        "title": query, 
                        "artist": "Unknown",
                        "source": "Genius (No Results)"
                    }
                
                # Get the top result
                top_hit = hits[0]['result']
                
                song_id = top_hit['id']
                song_title = top_hit['title']
                artist_name = top_hit['primary_artist']['name']
                song_url = top_hit['url']
                
                thumbnail = None
                if 'song_art_image_thumbnail_url' in top_hit:
                    thumbnail = top_hit['song_art_image_thumbnail_url']
                
                # Now fetch the lyrics from the song page
                lyrics = await scrape_lyrics_from_genius(song_url, session)
                
                # Get a list of alternative matches for better user experience
                alternatives = []
                for i, hit in enumerate(hits[1:4]):  # Get next 3 hits as alternatives
                    result = hit['result']
                    alternatives.append({
                        "title": result['title'],
                        "artist": result['primary_artist']['name'],
                        "url": result['url']
                    })
                
                return {
                    "lyrics": lyrics,
                    "title": song_title,
                    "artist": artist_name,
                    "source": "Genius",
                    "url": song_url,
                    "thumbnail": thumbnail,
                    "alternatives": alternatives
                }
        except asyncio.TimeoutError:
            raise Exception("Request to Genius API timed out. Please try again later.")

async def scrape_lyrics_from_genius(url: str, session: aiohttp.ClientSession) -> str:
    """Scrape lyrics from Genius song page."""
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return "Lyrics not found (error accessing page)"
            
            html_content = await resp.text()
            
            # Improved pattern matching to extract lyrics
            # Try multiple patterns to be more robust to HTML structure changes
            lyrics_patterns = [
                r'<div data-lyrics-container="true".*?>(.*?)</div>',
                r'<div class="lyrics">(.*?)</div>',
                r'<div class="Lyrics__Container-.*?>(.*?)</div>'
            ]
            
            lyrics_text = None
            for pattern in lyrics_patterns:
                matches = re.findall(pattern, html_content, re.DOTALL)
                if matches:
                    # Join all matching containers (some lyrics are split into multiple containers)
                    lyrics_html = "".join(matches)
                    
                    # Process the HTML
                    lyrics_text = process_lyrics_html(lyrics_html)
                    break
            
            if lyrics_text:
                return lyrics_text
            
            return "Lyrics not found (could not extract from page)"
    except asyncio.TimeoutError:
        return "Lyrics not found (request timed out)"
    except Exception as e:
        logger.error(f"Error scraping lyrics: {e}")
        return f"Lyrics not found (error: {str(e)})"

def process_lyrics_html(lyrics_html: str) -> str:
    """Process lyrics HTML to get clean text."""
    # Replace <br> tags with newlines
    lyrics = re.sub(r'<br\s*/?>', '\n', lyrics_html)
    
    # Remove all other HTML tags
    lyrics = re.sub(r'<[^>]+>', '', lyrics)
    
    # Decode HTML entities
    lyrics = html.unescape(lyrics)
    
    # Fix newlines and clean up
    lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)
    lyrics = lyrics.strip()
    
    return lyrics

async def fetch_from_alternative_source(query: str) -> Dict[str, Any]:
    """
    Fetch lyrics from an alternative source when Genius API is not available.
    This method is simplified and provides a clear error message rather than
    attempting to scrape from unauthorized sources.
    """
    # Return a message explaining that the Genius API is needed
    return {
        "lyrics": f"Lyrics for '{query}' could not be found.\n\nThe bot requires a valid Genius API key to fetch lyrics from authorized sources.",
        "title": query,
        "artist": "Unknown",
        "source": "No API Key",
        "error": "Genius API key required"
    }
