import aiohttp
import logging
import re
from typing import Dict, Optional, Any
import json

logger = logging.getLogger('discord_bot.lyrics_fetcher')

async def fetch_lyrics(query: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch lyrics for a song using the Genius API.
    
    Args:
        query: Song name to search for
        api_key: Optional Genius API key
    
    Returns:
        Dictionary containing lyrics, title, and artist information
    """
    # Clean the query
    query = clean_query(query)
    
    # Try to use Genius API if a key is provided
    if api_key:
        try:
            return await fetch_from_genius(query, api_key)
        except Exception as e:
            logger.error(f"Error using Genius API: {e}")
            # Fall back to alternative method if Genius fails
    
    # Fallback method: Simple web scraping or other free services
    try:
        return await fetch_from_alternative_source(query)
    except Exception as e:
        logger.error(f"Error using alternative lyrics source: {e}")
        return {"lyrics": "", "title": query, "artist": "Unknown"}

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
        async with session.get(
            search_url,
            headers={"Authorization": f"Bearer {api_key}"}
        ) as resp:
            if resp.status != 200:
                logger.warning(f"Genius API search failed: {resp.status}")
                raise Exception("Failed to search for lyrics")
            
            data = await resp.json()
            
            # Check if we got any hits
            hits = data.get('response', {}).get('hits', [])
            if not hits:
                return {"lyrics": "", "title": query, "artist": "Unknown"}
            
            # Get the top result
            top_hit = hits[0]['result']
            
            song_id = top_hit['id']
            song_title = top_hit['title']
            artist_name = top_hit['primary_artist']['name']
            song_url = top_hit['url']
            
            # Now fetch the lyrics from the song page
            lyrics = await scrape_lyrics_from_genius(song_url, session)
            
            return {
                "lyrics": lyrics,
                "title": song_title,
                "artist": artist_name,
                "source": "Genius",
                "url": song_url
            }

async def scrape_lyrics_from_genius(url: str, session: aiohttp.ClientSession) -> str:
    """Scrape lyrics from Genius song page."""
    async with session.get(url) as resp:
        if resp.status != 200:
            return "Lyrics not found"
        
        html = await resp.text()
        
        # Simple pattern matching to extract lyrics
        # This is a very basic implementation and might break if Genius changes their HTML structure
        lyrics_pattern = r'<div data-lyrics-container="true".*?>(.*?)</div>'
        lyrics_match = re.search(lyrics_pattern, html, re.DOTALL)
        
        if not lyrics_match:
            # Try alternative pattern
            lyrics_pattern = r'<div class="lyrics">(.*?)</div>'
            lyrics_match = re.search(lyrics_pattern, html, re.DOTALL)
        
        if lyrics_match:
            lyrics_html = lyrics_match.group(1)
            
            # Remove HTML tags
            lyrics = re.sub(r'<[^>]+>', '\n', lyrics_html)
            
            # Fix newlines and clean up
            lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)
            lyrics = lyrics.strip()
            
            return lyrics
        
        return "Lyrics not found"

async def fetch_from_alternative_source(query: str) -> Dict[str, Any]:
    """
    Fetch lyrics from an alternative source when Genius API is not available.
    This is a simplified implementation.
    """
    # For now, return a simple message
    # In a real implementation, you might use another lyrics API or web scraping
    return {
        "lyrics": f"Lyrics for '{query}' not found. Please try with a Genius API key for better results.",
        "title": query,
        "artist": "Unknown",
        "source": "Alternative"
    }
