import discord
from discord.ext import commands
import asyncio
import logging
import sys

# Configure more detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
import os
import re
import aiohttp
import json
from typing import Dict, List, Optional, Tuple
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

import config
from utils.music_utils import MusicQueue, Song
from utils.lyrics_fetcher import fetch_lyrics

logger = logging.getLogger('discord_bot.music_player')

# YT-DLP configuration - simplified for memory-constrained environments but with more compatible format
ytdl_format_options = {
    'format': 'bestaudio[filesize<3M]/bestaudio/worst', # Try small audio files first, then fallback
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False # Needed for proper format selection
}

# Set the absolute path to ffmpeg - this is critical for music playback
FFMPEG_PATH = '/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin/ffmpeg'

# Function to get memory-efficient ffmpeg options
def get_ffmpeg_options():
    return {
        'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1',
        'options': '-vn -bufsize 1024k -ar 44100 -ac 1' # Mono audio, lower quality, smaller buffer
    }

# Set ffmpeg in environment path to help discord.py find it automatically
os.environ['PATH'] = f"/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin:{os.environ.get('PATH', '')}"

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    # Removed executable from here as it's passed directly to FFmpegPCMAudio
}

class YTDLSource(discord.PCMVolumeTransformer):
    """Audio source for YouTube and other supported platforms."""
    
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')
        self.uploader = data.get('uploader')
    
    @classmethod
    async def create_source(cls, search: str, *, loop=None):
        """Create a source from a search query or URL."""
        loop = loop or asyncio.get_event_loop()
        
        ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
        
        # Process the search or URL
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        except Exception as e:
            logger.error(f"Error extracting info: {e}")
            raise Exception(f"Could not extract information from {search}: {e}")
        
        # Handle playlist entries
        if 'entries' in data:
            # Take the first item from a playlist
            data = data['entries'][0]
        
        # Create a Song object with the extracted data
        song = Song(
            title=data.get('title', 'Unknown'),
            url=data.get('url'),
            duration=data.get('duration'),
            webpage_url=data.get('webpage_url', search),
            thumbnail=data.get('thumbnail'),
            uploader=data.get('uploader', 'Unknown'),
            is_spotify=False
        )
        
        return song
    
    @staticmethod
    async def stream_audio(song: Song):
        """Creates a lightweight FFmpeg audio source optimized for memory-constrained environments."""
        logger.debug(f"Starting ultra-lightweight stream for: {song.title}")
        
        # Super lightweight options - absolute minimum memory usage but compatibility focused
        lightweight_ytdl_options = {
            'format': 'bestaudio[filesize<2M]/bestaudio[acodec=opus]/bestaudio',  # Small files first, then good compatibility
            'noplaylist': True,
            'nocheckcertificate': True,
            'quiet': True,
            'extract_flat': False,   # Need full extraction for format selection
            'skip_download': True,   # Make sure we're not downloading
            'youtube_include_dash_manifest': False  # Skip DASH manifest parsing
        }
        
        ytdl = yt_dlp.YoutubeDL(lightweight_ytdl_options)
        
        # Keep ffmpeg path detection simple
        ffmpeg_path = FFMPEG_PATH
        logger.debug(f"Using ffmpeg at: {ffmpeg_path}")
        
        # Get our ultra-efficient ffmpeg options 
        ffmpeg_opts = get_ffmpeg_options()
        
        # Simple URL determination logic - use any available URL or search
        url_to_extract = None
        if song.url:
            url_to_extract = song.url
        elif song.webpage_url:
            url_to_extract = song.webpage_url
        else:
            url_to_extract = f"ytsearch:{song.title}"
            
        logger.debug(f"Lightweight extraction from: {url_to_extract}")
            
        try:
            # Simplified extraction
            loop = asyncio.get_event_loop()
            
            # Simplified extraction function - more reliability focused
            async def get_direct_url():
                try:
                    # First, check for direct audio URLs
                    if song.url and any(song.url.endswith(ext) for ext in ['.mp3', '.m4a', '.ogg', '.wav']):
                        logger.debug(f"Using direct audio URL: {song.url}")
                        return song.url, None
                    
                    # For search queries, just do a simple YouTube search
                    if 'ytsearch:' in url_to_extract:
                        logger.debug("Performing YouTube search with simple approach")
                        # Simple extraction with default format
                        info = await loop.run_in_executor(None, 
                                lambda: ytdl.extract_info(url_to_extract, download=False))
                        
                        if info and info.get('entries') and len(info['entries']) > 0:
                            entry = info['entries'][0]
                            # Make sure we have a URL
                            if entry.get('url'):
                                return entry.get('url'), entry
                    
                    # For all other URLs, direct extraction
                    logger.debug("Using direct extraction with best audio format")
                    info = await loop.run_in_executor(None, 
                            lambda: ytdl.extract_info(url_to_extract, download=False))
                    
                    # Handle playlist results
                    if info and info.get('entries') and len(info['entries']) > 0:
                        info = info['entries'][0]
                    
                    # Return the URL and metadata
                    if info and info.get('url'):
                        return info.get('url'), info
                    else:
                        logger.error("No URL found in extracted info")
                        return None, None
                        
                except Exception as e:
                    logger.error(f"Error in URL extraction: {e}")
                    # Try with simpler format for compatibility
                    try:
                        lightweight_ytdl_options['format'] = 'worstaudio/worst'
                        ytdl = yt_dlp.YoutubeDL(lightweight_ytdl_options)
                        
                        info = await loop.run_in_executor(None, 
                                lambda: ytdl.extract_info(url_to_extract, download=False))
                                
                        if info and info.get('entries') and len(info['entries']) > 0:
                            info = info['entries'][0]
                            
                        if info and info.get('url'):
                            return info.get('url'), info
                    except Exception as fallback_error:
                        logger.error(f"Fallback extraction also failed: {fallback_error}")
                    
                    return None, None
            
            # Get URL and info
            stream_url, info = await get_direct_url()
            
            if not stream_url:
                raise Exception("Could not find a playable audio stream")
                
            # Update metadata if we have it
            if info:
                if not song.duration and info.get('duration'):
                    song.duration = info.get('duration')
                if not song.thumbnail and info.get('thumbnail'):
                    song.thumbnail = info.get('thumbnail')
                if not song.webpage_url and info.get('webpage_url'):
                    song.webpage_url = info.get('webpage_url')
            
            # Create the most efficient audio source possible
            audio_source = discord.FFmpegPCMAudio(
                source=stream_url,
                executable=ffmpeg_path,
                before_options=ffmpeg_opts['before_options'],
                options=ffmpeg_opts['options']
            )
            
            return audio_source
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Audio extraction failed: {error_msg}")
            
            # Make a more user-friendly error message
            if "HTTP Error 429" in error_msg:
                raise Exception("YouTube rate limited us. Please try again later.")
            elif "Video unavailable" in error_msg:
                raise Exception("This video is unavailable or restricted.")
            elif "Requested format is not available" in error_msg:
                raise Exception("Could not find a compatible audio format. Try another song.")
            elif "exceeded" in error_msg.lower() and "memory" in error_msg.lower():
                raise Exception("Memory limit exceeded. Try a shorter or less complex song.")
            elif "ffmpeg" in error_msg.lower():
                raise Exception("Error processing audio. Try another song or format.")
            else:
                # Log the full error but give a simple message to the user
                logger.error(f"Detailed error: {error_msg}")
                raise Exception("Could not play this audio. Try another song.")

class MusicPlayer(commands.Cog):
    """Cog for music player functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.music_queues: Dict[int, MusicQueue] = {}  # {guild_id: MusicQueue}
        self.setup_spotify()
    
    def setup_spotify(self):
        """Set up Spotify client if credentials are available."""
        # We're disabling Spotify API integration to work without API keys
        logger.info("Spotify API integration disabled - running in API-free mode")
        self.spotify = None
        return False
    
    def get_queue(self, guild_id: int) -> MusicQueue:
        """Get or create a MusicQueue for a guild."""
        if guild_id not in self.music_queues:
            self.music_queues[guild_id] = MusicQueue()
        return self.music_queues[guild_id]
    
    @commands.command(name="joinvc", aliases=["connect"])
    async def joinvc(self, ctx):
        """Connect to the voice channel."""
        if ctx.author.voice is None:
            await ctx.send("❌ You need to be in a voice channel to use this command.")
            return
        
        voice_channel = ctx.author.voice.channel
        
        # Check if bot is already in a voice channel
        if ctx.voice_client is not None:
            # If already in the same channel, do nothing
            if ctx.voice_client.channel.id == voice_channel.id:
                await ctx.send(f"✅ Already connected to {voice_channel.name}!")
                return
            # Move to the new channel
            await ctx.voice_client.move_to(voice_channel)
            await ctx.send(f"🔄 Moved to {voice_channel.name}!")
        else:
            # Connect to the voice channel
            await voice_channel.connect()
            await ctx.send(f"🎵 Connected to {voice_channel.name}!")
        
        # Initialize the music queue for this guild
        self.get_queue(ctx.guild.id)
        logger.info(f"Bot joined voice channel {voice_channel.id} in guild {ctx.guild.id}")
    
    @commands.command(name="leave", aliases=["disconnect"])
    async def leave(self, ctx):
        """Disconnect from the voice channel."""
        if ctx.voice_client is None:
            await ctx.send("❌ I'm not connected to any voice channel.")
            return
        
        # Clear the queue and disconnect
        if ctx.guild.id in self.music_queues:
            self.music_queues[ctx.guild.id].clear()
        
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Disconnected from voice channel!")
        logger.info(f"Bot left voice channel in guild {ctx.guild.id}")
    
    async def process_spotify_url(self, url: str) -> List[Song]:
        """Process a Spotify URL and return a list of songs."""
        if not self.spotify:
            return []
        
        songs = []
        
        # Track pattern
        track_pattern = r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)'
        # Album pattern
        album_pattern = r'https://open\.spotify\.com/album/([a-zA-Z0-9]+)'
        # Playlist pattern
        playlist_pattern = r'https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)'
        
        # Check if it's a track
        track_match = re.match(track_pattern, url)
        if track_match:
            track_id = track_match.group(1)
            track = self.spotify.track(track_id)
            
            # Create a Song object
            song = Song(
                title=f"{track['name']} - {', '.join(artist['name'] for artist in track['artists'])}",
                url=None,  # Will be resolved when playing
                duration=track['duration_ms'] // 1000,  # Convert to seconds
                webpage_url=track['external_urls']['spotify'],
                thumbnail=track['album']['images'][0]['url'] if track['album']['images'] else None,
                uploader=track['artists'][0]['name'] if track['artists'] else 'Unknown',
                is_spotify=True,
                search_query=f"{track['name']} {track['artists'][0]['name']} audio"
            )
            songs.append(song)
            return songs
        
        # Check if it's an album
        album_match = re.match(album_pattern, url)
        if album_match:
            album_id = album_match.group(1)
            album = self.spotify.album(album_id)
            
            # Get tracks from the album
            for track in album['tracks']['items']:
                song = Song(
                    title=f"{track['name']} - {', '.join(artist['name'] for artist in track['artists'])}",
                    url=None,
                    duration=track['duration_ms'] // 1000,
                    webpage_url=track['external_urls']['spotify'],
                    thumbnail=album['images'][0]['url'] if album['images'] else None,
                    uploader=track['artists'][0]['name'] if track['artists'] else 'Unknown',
                    is_spotify=True,
                    search_query=f"{track['name']} {track['artists'][0]['name']} audio"
                )
                songs.append(song)
            return songs
        
        # Check if it's a playlist
        playlist_match = re.match(playlist_pattern, url)
        if playlist_match:
            playlist_id = playlist_match.group(1)
            playlist = self.spotify.playlist(playlist_id)
            
            # Get tracks from the playlist (limit to 20 tracks to prevent overloading)
            for i, item in enumerate(playlist['tracks']['items']):
                if i >= 20:  # Limit to 20 tracks
                    break
                
                track = item['track']
                if track:
                    song = Song(
                        title=f"{track['name']} - {', '.join(artist['name'] for artist in track['artists'])}",
                        url=None,
                        duration=track['duration_ms'] // 1000,
                        webpage_url=track['external_urls']['spotify'],
                        thumbnail=track['album']['images'][0]['url'] if track['album']['images'] else None,
                        uploader=track['artists'][0]['name'] if track['artists'] else 'Unknown',
                        is_spotify=True,
                        search_query=f"{track['name']} {track['artists'][0]['name']} audio"
                    )
                    songs.append(song)
            return songs
        
        return []
    
    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query: str = None):
        """
        Play a song from YouTube or Spotify.
        
        Usage:
        =play <YouTube URL or search query>
        =play <Spotify track/album/playlist URL>
        """
        if query is None:
            await ctx.send("❌ Please provide a song URL or search query.")
            return
        
        # Check if the user is in a voice channel
        if ctx.author.voice is None:
            await ctx.send("❌ You need to be in a voice channel to use this command.")
            return
        
        # Connect to the voice channel if not already connected
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
            await ctx.send(f"🎵 Connected to {ctx.author.voice.channel.name}!")
        
        # Get the queue for this guild
        queue = self.get_queue(ctx.guild.id)
        
        # Check if it's a Spotify URL (convert to YouTube search)
        if "open.spotify.com" in query:
            await ctx.send("🔍 Converting Spotify link to YouTube search...")
            
            # Extract the track/artist name from Spotify URL if possible
            try:
                # Simple regex to extract song name from URL or use as search
                track_name_match = re.search(r'track/[a-zA-Z0-9]+/([^?]+)', query)
                if track_name_match:
                    track_name = track_name_match.group(1).replace('-', ' ')
                    search_query = track_name + " audio"
                else:
                    # If we can't extract, just use the URL as a search term
                    search_query = query
                
                await ctx.send(f"🔍 Searching for: {search_query}")
                # Now search YouTube with this query
                song = await YTDLSource.create_source(search_query, loop=self.bot.loop)
                
                # Add the song to the queue
                queue.add(song)
                
                # Send confirmation message
                embed = discord.Embed(
                    title="➕ Added to Queue (from Spotify link)",
                    description=f"[{song.title}]({song.webpage_url})",
                    color=discord.Color.green()
                )
                
                if song.thumbnail:
                    embed.set_thumbnail(url=song.thumbnail)
                
                if song.duration:
                    minutes, seconds = divmod(song.duration, 60)
                    embed.add_field(name="Duration", value=f"{minutes}:{seconds:02d}", inline=True)
                
                embed.add_field(name="Uploader", value=song.uploader, inline=True)
                
                position = len(queue.songs)
                embed.set_footer(text=f"Position in queue: {position}")
                
                await ctx.send(embed=embed)
                
                # Start playing if not already playing
                if not ctx.voice_client.is_playing() and not queue.is_empty():
                    await self.play_next_song(ctx)
                
            except Exception as e:
                logger.error(f"Error processing Spotify URL: {e}")
                await ctx.send(f"❌ Could not process Spotify link. Trying as a general search query...")
                
                # Fall back to treating the whole URL as a search term
                try:
                    song = await YTDLSource.create_source(query, loop=self.bot.loop)
                    queue.add(song)
                    await ctx.send(f"✅ Added to queue: {song.title}")
                    
                    # Start playing if not already playing
                    if not ctx.voice_client.is_playing() and not queue.is_empty():
                        await self.play_next_song(ctx)
                except Exception as e2:
                    logger.error(f"Error in fallback search: {e2}")
                    await ctx.send(f"❌ An error occurred: {str(e2)}")
            
            return
        
        # Process YouTube URL or search query
        await ctx.send("🔍 Searching for song...")
        
        try:
            # Get the song information
            song = await YTDLSource.create_source(query, loop=self.bot.loop)
            
            # Add the song to the queue
            queue.add(song)
            
            # Send confirmation message
            embed = discord.Embed(
                title="➕ Added to Queue",
                description=f"[{song.title}]({song.webpage_url})",
                color=discord.Color.green()
            )
            
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            
            if song.duration:
                minutes, seconds = divmod(song.duration, 60)
                embed.add_field(name="Duration", value=f"{minutes}:{seconds:02d}", inline=True)
            
            embed.add_field(name="Uploader", value=song.uploader, inline=True)
            
            position = len(queue.songs)
            embed.set_footer(text=f"Position in queue: {position}")
            
            await ctx.send(embed=embed)
            
            # Start playing if not already playing
            if not ctx.voice_client.is_playing() and not queue.is_empty():
                await self.play_next_song(ctx)
            
        except Exception as e:
            logger.error(f"Error playing song: {e}")
            await ctx.send(f"❌ An error occurred: {str(e)}")
    
    async def play_next_song(self, ctx):
        """Play the next song in the queue."""
        logger.debug("Starting play_next_song method")
        
        # Make sure voice client is still connected
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            logger.warning("Voice client disconnected, cannot play next song")
            return
            
        queue = self.get_queue(ctx.guild.id)
        
        if queue.is_empty():
            logger.debug("Queue is empty")
            await ctx.send("🎵 Queue is empty. Use `=play` to add songs!")
            return
        
        # Get the next song from the queue
        song = queue.get_next_song()
        if not song:
            logger.warning("Failed to get next song from queue")
            await ctx.send("❌ Failed to get the next song from queue.")
            return
            
        logger.debug(f"Got next song: {song.title}")
        
        try:
            # Handle Spotify songs by searching YouTube
            if hasattr(song, 'is_spotify') and song.is_spotify:
                await ctx.send(f"🔍 Finding YouTube source for: {song.title}")
                
                if not hasattr(song, 'search_query') or not song.search_query:
                    search_query = f"{song.title} audio"
                    logger.debug(f"No search query available, using title: {search_query}")
                else:
                    search_query = song.search_query
                    logger.debug(f"Using search query: {search_query}")
                
                # Try to find the song on YouTube
                try:
                    youtube_song = await YTDLSource.create_source(search_query, loop=self.bot.loop)
                    # Update song with YouTube details
                    if youtube_song:
                        song.url = youtube_song.url
                        song.webpage_url = youtube_song.webpage_url
                        logger.debug(f"Found YouTube source: {song.url}")
                    else:
                        raise Exception("YouTube source returned None")
                except Exception as e:
                    logger.error(f"Failed to find YouTube source for Spotify song: {e}")
                    await ctx.send(f"❌ Failed to find a YouTube source for: {song.title}")
                    # Skip to the next song instead of recursively calling play_next_song
                    queue.next_song() 
                    await self.play_next_song(ctx)
                    return
            
            # Verify we have a URL to play
            if not hasattr(song, 'url') or not song.url:
                if hasattr(song, 'webpage_url') and song.webpage_url:
                    logger.debug(f"No direct URL, using webpage URL: {song.webpage_url}")
                else:
                    logger.error("Song has no URL to play")
                    await ctx.send(f"❌ No playable URL found for: {song.title}")
                    queue.next_song()
                    await self.play_next_song(ctx)
                    return
            
            # Create the audio source with detailed error handling
            try:
                logger.debug(f"Creating audio source for: {song.title}")
                # Make explicitly sure we catch all exceptions when creating audio
                try:
                    audio_source = await YTDLSource.stream_audio(song)
                    
                    if not audio_source:
                        raise Exception("Failed to create audio source - returned None")
                except Exception as audio_err:
                    logger.error(f"Stream audio error: {audio_err}")
                    # Add more detailed error info for debugging
                    raise Exception(f"Could not play audio: {str(audio_err)}")
                    
            except Exception as e:
                logger.error(f"Error creating audio source: {e}")
                await ctx.send(f"❌ Error playing {song.title}: {str(e)}")
                # Skip to next song
                queue.next_song()
                await self.play_next_song(ctx)
                return
            
            # Verify voice client is still connected before playing
            if not ctx.voice_client or not ctx.voice_client.is_connected():
                logger.warning("Voice client disconnected while preparing song")
                return
                
            # Set the volume
            try:
                volume = queue.volume if hasattr(queue, 'volume') else 0.5
                volume_transformer = discord.PCMVolumeTransformer(audio_source, volume=volume)
                
                # Play the song with robust error handling in the callback
                ctx.voice_client.play(
                    volume_transformer,
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.song_finished(ctx, e), self.bot.loop
                    ).result()  # Added .result() to ensure errors are caught
                )
                
                # Send now playing message
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"[{song.title}]({song.webpage_url if hasattr(song, 'webpage_url') else ''})",
                    color=discord.Color.blue()
                )
                
                if hasattr(song, 'thumbnail') and song.thumbnail:
                    embed.set_thumbnail(url=song.thumbnail)
                
                if hasattr(song, 'duration') and song.duration:
                    minutes, seconds = divmod(song.duration, 60)
                    embed.add_field(name="Duration", value=f"{minutes}:{seconds:02d}", inline=True)
                
                uploader = song.uploader if hasattr(song, 'uploader') else "Unknown"
                embed.add_field(name="Uploader", value=uploader, inline=True)
                
                queue_length = len(queue.songs) if hasattr(queue, 'songs') else 0
                embed.set_footer(text=f"Songs in queue: {queue_length}")
                
                await ctx.send(embed=embed)
                logger.info(f"Now playing: {song.title}")
                
            except Exception as e:
                logger.error(f"Error starting playback: {e}")
                await ctx.send(f"❌ Error starting playback: {str(e)}")
                # Try next song
                queue.next_song()
                await self.play_next_song(ctx)
                
        except Exception as e:
            logger.error(f"Unexpected error in play_next_song: {e}")
            await ctx.send(f"❌ An unexpected error occurred: {str(e)}")
            # Move to next song to avoid getting stuck
            queue.next_song()
            await self.play_next_song(ctx)
    
    async def song_finished(self, ctx, error):
        """Called when a song finishes playing."""
        try:
            if error:
                logger.error(f"Player error: {error}")
                await ctx.send(f"❌ Player error: {error}")
            
            # Make sure the guild still exists and we're still connected
            if not ctx.guild or not ctx.voice_client or not ctx.voice_client.is_connected():
                logger.warning("Cannot continue playback - disconnected from voice channel")
                return
                
            queue = self.get_queue(ctx.guild.id)
            
            # If there are more songs in the queue, play the next one
            if not queue.is_empty():
                await self.play_next_song(ctx)
            else:
                await ctx.send("🎵 Queue finished. Add more songs with `=play`!")
        except Exception as e:
            logger.error(f"Error in song_finished callback: {e}")
            try:
                await ctx.send(f"❌ Error handling song completion: {str(e)}")
            except:
                # If we can't send a message, the channel might be deleted or bot lacks permissions
                logger.error("Could not send error message to channel")
                pass
    
    @commands.command(name="pause")
    async def pause(self, ctx):
        """Pause the currently playing song."""
        if ctx.voice_client is None or not ctx.voice_client.is_playing():
            await ctx.send("❌ Nothing is playing right now.")
            return
        
        ctx.voice_client.pause()
        await ctx.send("⏸️ Paused the music.")
    
    @commands.command(name="resume")
    async def resume(self, ctx):
        """Resume the paused song."""
        if ctx.voice_client is None:
            await ctx.send("❌ I'm not connected to a voice channel.")
            return
        
        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Resumed the music.")
        else:
            await ctx.send("❌ The music is not paused.")
    
    @commands.command(name="skip", aliases=["next"])
    async def skip(self, ctx):
        """Skip the current song."""
        if ctx.voice_client is None:
            await ctx.send("❌ I'm not connected to a voice channel.")
            return
        
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await ctx.send("❌ Nothing is playing right now.")
            return
        
        # Stop the current song, which will trigger the after callback
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped the song.")
    
    @commands.command(name="queue", aliases=["q"])
    async def view_queue(self, ctx):
        """View the current music queue."""
        queue = self.get_queue(ctx.guild.id)
        
        if queue.is_empty():
            await ctx.send("📭 The queue is empty.")
            return
        
        # Create an embed to display the queue
        embed = discord.Embed(
            title="🎵 Music Queue",
            description=f"Total songs: {len(queue.songs)}",
            color=discord.Color.blue()
        )
        
        # Add currently playing song
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            current_song = queue.current_song
            if current_song:
                embed.add_field(
                    name="🎵 Now Playing",
                    value=f"[{current_song.title}]({current_song.webpage_url})",
                    inline=False
                )
        
        # Add upcoming songs (limited to 10)
        upcoming_songs = queue.songs[queue.current_index + 1:queue.current_index + 11]
        if upcoming_songs:
            upcoming_list = []
            for i, song in enumerate(upcoming_songs, 1):
                duration = f" ({song.duration // 60}:{song.duration % 60:02d})" if song.duration else ""
                upcoming_list.append(f"{i}. [{song.title}]({song.webpage_url}){duration}")
            
            embed.add_field(
                name="📑 Up Next",
                value="\n".join(upcoming_list),
                inline=False
            )
        
        # Display remaining songs count
        remaining = len(queue.songs) - queue.current_index - len(upcoming_songs) - 1
        if remaining > 0:
            embed.set_footer(text=f"And {remaining} more songs")
        
        await ctx.send(embed=embed)
    
    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: int = None):
        """
        Change the volume of the music player.
        
        Usage:
        =volume - Show current volume
        =volume <1-100> - Set volume level
        """
        queue = self.get_queue(ctx.guild.id)
        
        # If no volume is specified, show current volume
        if volume is None:
            current_volume = int(queue.volume * 100)
            await ctx.send(f"🔊 Current volume: {current_volume}%")
            return
        
        # Validate volume range
        if not (0 <= volume <= 100):
            await ctx.send("❌ Volume must be between 0 and 100.")
            return
        
        # Set the queue volume
        queue.volume = volume / 100.0
        
        # If something is playing, change its volume
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = queue.volume
        
        await ctx.send(f"🔊 Volume set to {volume}%")
    
    @commands.command(name="stop")
    async def stop(self, ctx):
        """Stop playing and clear the queue."""
        queue = self.get_queue(ctx.guild.id)
        
        # Stop playback and clear the queue
        if ctx.voice_client:
            ctx.voice_client.stop()
        
        queue.clear()
        await ctx.send("⏹️ Stopped playback and cleared the queue.")
    
    @commands.command(name="lyrics", aliases=["ly"])
    async def lyrics(self, ctx, *, query: str = None):
        """
        Display lyrics for the current song or a specified song.
        
        Usage:
        =lyrics - Get lyrics for the current song
        =lyrics <song name> - Get lyrics for a specific song
        """
        queue = self.get_queue(ctx.guild.id)
        
        # If no query is provided, use the current song
        if query is None:
            current_song = queue.current_song
            if current_song is None:
                await ctx.send("❌ No song is currently playing. Please provide a song name.")
                return
            
            # Remove any "(Official Video)" or similar text from the title
            title = current_song.title
            title = re.sub(r'\([^)]*\)|ft\..*|feat\..*|-\s+[\w\s]+', '', title)
            query = title.strip()
            
            # Add artist name to query if available for better results
            if hasattr(current_song, 'uploader') and current_song.uploader and current_song.uploader.lower() != "unknown":
                query += f" {current_song.uploader}"
        
        # Check if Genius API key is provided
        if not config.GENIUS_API_KEY:
            await ctx.send("⚠️ No Genius API key configured. Lyrics functionality will be limited.")
        
        # Show a typing indicator to indicate that the bot is processing
        async with ctx.typing():
            try:
                await ctx.send(f"🔍 Searching for lyrics: `{query}`")
                
                # Fetch lyrics
                lyrics_data = await fetch_lyrics(query, api_key=config.GENIUS_API_KEY)
                
                if not lyrics_data or not lyrics_data.get('lyrics'):
                    error_message = lyrics_data.get('error', 'Unknown error')
                    if "API key required" in error_message:
                        await ctx.send("⚠️ Genius API key is required for lyrics functionality. Please contact the bot administrator.")
                    else:
                        await ctx.send(f"❌ Couldn't find lyrics for: `{query}`\nReason: {lyrics_data.get('lyrics', 'No results found')}")
                    return
                
                # Create embeds for the lyrics (Discord has a 2000 character limit per embed)
                title = lyrics_data.get('title', 'Unknown')
                artist = lyrics_data.get('artist', 'Unknown')
                lyrics = lyrics_data.get('lyrics', 'No lyrics found')
                source = lyrics_data.get('source', 'Unknown')
                url = lyrics_data.get('url', None)
                thumbnail = lyrics_data.get('thumbnail', None)
                alternatives = lyrics_data.get('alternatives', [])
                
                # Split lyrics into chunks of 1800 characters or less (leaving room for formatting)
                # Try to split on double newlines to keep stanzas together
                chunks = []
                current_chunk = ""
                
                for line in lyrics.split('\n'):
                    if len(current_chunk) + len(line) + 1 > 1800:
                        chunks.append(current_chunk)
                        current_chunk = line
                    else:
                        if current_chunk:
                            current_chunk += '\n' + line
                        else:
                            current_chunk = line
                
                if current_chunk:
                    chunks.append(current_chunk)
                
                if not chunks:
                    chunks = ["No lyrics found"]
                
                # Send the first embed with title and artist
                first_embed = discord.Embed(
                    title=f"📝 Lyrics: {title}",
                    description=chunks[0],
                    color=discord.Color.purple(),
                    url=url
                )
                first_embed.set_author(name=f"Artist: {artist}")
                
                if thumbnail:
                    first_embed.set_thumbnail(url=thumbnail)
                
                if source:
                    first_embed.set_footer(text=f"Source: {source} | Page 1/{len(chunks)}")
                
                await ctx.send(embed=first_embed)
                
                # Send the rest of the lyrics in separate embeds
                for i, chunk in enumerate(chunks[1:], 2):
                    embed = discord.Embed(
                        description=chunk,
                        color=discord.Color.purple(),
                        url=url
                    )
                    embed.set_footer(text=f"Source: {source} | Page {i}/{len(chunks)}")
                    await ctx.send(embed=embed)
                
                # If there are alternative matches, send them as a suggestion
                if alternatives and len(alternatives) > 0:
                    alt_embed = discord.Embed(
                        title="💡 Did you mean one of these songs instead?",
                        color=discord.Color.gold()
                    )
                    
                    for i, alt in enumerate(alternatives, 1):
                        alt_title = alt.get('title', 'Unknown')
                        alt_artist = alt.get('artist', 'Unknown')
                        alt_url = alt.get('url', None)
                        
                        if alt_url:
                            alt_embed.add_field(
                                name=f"{i}. {alt_title}",
                                value=f"By {alt_artist}\n[View on Genius]({alt_url})",
                                inline=False
                            )
                        else:
                            alt_embed.add_field(
                                name=f"{i}. {alt_title}",
                                value=f"By {alt_artist}",
                                inline=False
                            )
                    
                    alt_embed.set_footer(text="Use =lyrics <song title> to get lyrics for a specific song")
                    await ctx.send(embed=alt_embed)
                
            except Exception as e:
                logger.error(f"Error fetching lyrics: {e}")
                await ctx.send(f"❌ Error fetching lyrics: {str(e)}")
    
    @commands.command(name="nowplaying", aliases=["np"])
    async def now_playing(self, ctx):
        """Show information about the currently playing song."""
        queue = self.get_queue(ctx.guild.id)
        
        if queue.current_song is None or not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            await ctx.send("❌ Nothing is playing right now.")
            return
        
        song = queue.current_song
        
        # Create an embed with information about the current song
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"[{song.title}]({song.webpage_url})",
            color=discord.Color.blue()
        )
        
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        
        if song.duration:
            minutes, seconds = divmod(song.duration, 60)
            embed.add_field(name="Duration", value=f"{minutes}:{seconds:02d}", inline=True)
        
        embed.add_field(name="Uploader", value=song.uploader, inline=True)
        
        # Show player status
        status = "⏸️ Paused" if ctx.voice_client.is_paused() else "▶️ Playing"
        embed.add_field(name="Status", value=status, inline=True)
        
        # Show current volume
        volume = int(queue.volume * 100)
        embed.add_field(name="Volume", value=f"{volume}%", inline=True)
        
        # Show queue position
        position = queue.current_index + 1
        total = len(queue.songs)
        embed.set_footer(text=f"Song {position} of {total} in queue")
        
        await ctx.send(embed=embed)
    
    @commands.command(name="clear")
    async def clear_queue(self, ctx):
        """Clear all songs from the queue except the currently playing one."""
        queue = self.get_queue(ctx.guild.id)
        
        if queue.is_empty():
            await ctx.send("📭 The queue is already empty.")
            return
        
        # Keep the current song, remove the rest
        current_song = None
        if queue.current_index < len(queue.songs):
            current_song = queue.songs[queue.current_index]
        
        queue.clear()
        
        # Add back the current song if it exists
        if current_song:
            queue.add(current_song)
            queue.current_index = 0
        
        await ctx.send("🧹 Queue has been cleared.")

async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(MusicPlayer(bot))
