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

# YT-DLP configuration
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # Bind to ipv4
}

# Set the absolute path to ffmpeg - this is critical for music playback
FFMPEG_PATH = '/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin/ffmpeg'

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
        """Creates an FFmpeg audio source for streaming."""
        logger.debug(f"Starting stream_audio for song: {song.title}")
        
        # Create a copy of ytdl options for customization
        custom_ytdl_options = ytdl_format_options.copy() 
        custom_ytdl_options['socket_timeout'] = 15  # Shorter timeout for better responsiveness
        custom_ytdl_options['quiet'] = True  # Reduce console spam
        
        ytdl = yt_dlp.YoutubeDL(custom_ytdl_options)
        
        # Get FFmpeg path from setup utility
        try:
            # Try to import dynamically to avoid circular imports
            import setup_ffmpeg
            try:
                # Try to get path from a function if available
                ffmpeg_path = setup_ffmpeg.get_ffmpeg_path()
            except AttributeError:
                # Otherwise use the module's path variable if defined
                ffmpeg_path = getattr(setup_ffmpeg, 'FFMPEG_PATH', 
                    '/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin/ffmpeg')
        except ImportError:
            # Fallback to known Replit path
            ffmpeg_path = '/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin/ffmpeg'
        
        # Verify ffmpeg exists
        if not os.path.exists(ffmpeg_path):
            logger.error(f"FFmpeg not found at {ffmpeg_path}")
            # Try to find in system path as last resort
            import shutil
            system_ffmpeg = shutil.which('ffmpeg')
            if system_ffmpeg:
                ffmpeg_path = system_ffmpeg
                logger.debug(f"Using ffmpeg from system path: {ffmpeg_path}")
            else:
                raise Exception("FFmpeg not found. Please check the installation.")
                
        logger.debug(f"Using FFmpeg at: {ffmpeg_path}")
        
        # Define improved ffmpeg options for reliable streaming
        before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin'
        options = '-vn -hide_banner -loglevel error -bufsize 1M'
        
        # Track our success to fallback to alternative methods if needed
        stream_success = False
        last_error = None
        
        # ATTEMPT 1: Try direct streaming from song.url if it's an audio file
        audio_extensions = ['.mp3', '.m4a', '.ogg', '.wav', '.opus', '.aac', '.flac']
        if song.url and any(song.url.endswith(ext) for ext in audio_extensions):
            try:
                logger.debug(f"Direct audio URL detected: {song.url}")
                audio_source = discord.FFmpegPCMAudio(
                    source=song.url,
                    executable=ffmpeg_path,
                    before_options=before_options,
                    options=options
                )
                stream_success = True
                return audio_source
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to play direct audio URL, will try extraction: {e}")
        
        # ATTEMPT 2: Extract and stream from song.url or webpage_url
        if not stream_success:
            try:
                url_to_extract = song.webpage_url if song.webpage_url else song.url
                
                if not url_to_extract:
                    raise Exception("No URL available to extract audio from")
                    
                logger.debug(f"Extracting audio from: {url_to_extract}")
                
                # Extract info in a separate thread to avoid blocking
                try:
                    data = await asyncio.to_thread(lambda: ytdl.extract_info(url_to_extract, download=False))
                except Exception as extract_error:
                    logger.error(f"YT-DLP extraction error: {extract_error}")
                    # Try once more with increased timeout
                    try:
                        logger.debug("Retrying extraction with increased timeout...")
                        custom_ytdl_options['socket_timeout'] = 30
                        ytdl = yt_dlp.YoutubeDL(custom_ytdl_options)
                        data = await asyncio.to_thread(lambda: ytdl.extract_info(url_to_extract, download=False))
                    except Exception as retry_error:
                        last_error = retry_error
                        raise Exception(f"Failed to extract audio data: {retry_error}")
                
                # Handle playlists
                if 'entries' in data:
                    if not data['entries']:
                        raise Exception("Playlist is empty")
                    logger.debug("Playlist detected, using first entry")
                    data = data['entries'][0]
                
                # Update song metadata with retrieved info
                if not song.url:
                    song.url = data.get('url')
                if not song.duration:
                    song.duration = data.get('duration')
                if not song.thumbnail:
                    song.thumbnail = data.get('thumbnail')
                if not song.webpage_url and data.get('webpage_url'):
                    song.webpage_url = data.get('webpage_url')
                
                # Try to get the best audio-only format if available
                formats = data.get('formats', [])
                audio_formats = [f for f in formats if 
                                f.get('acodec') != 'none' and 
                                (f.get('vcodec') == 'none' or f.get('resolution') == 'audio only')]
                
                # Select the best audio format for streaming
                stream_url = None
                if audio_formats:
                    # Sort by quality (bitrate, sample rate, etc.)
                    audio_formats.sort(key=lambda x: (
                        x.get('abr', 0) if x.get('abr') is not None else 0,  # Audio bitrate
                        x.get('asr', 0) if x.get('asr') is not None else 0,  # Audio sample rate
                        x.get('filesize', 0) if x.get('filesize') is not None else 0  # File size
                    ), reverse=True)
                    
                    # Prefer non-webm formats for better compatibility
                    for fmt in audio_formats:
                        if fmt.get('ext', '') != 'webm' and 'url' in fmt:
                            stream_url = fmt['url']
                            logger.debug(f"Selected audio format: {fmt.get('ext')} ({fmt.get('abr', 'unknown')}kbps)")
                            break
                    
                    # If no non-webm format is found, use the best available
                    if not stream_url and audio_formats and 'url' in audio_formats[0]:
                        stream_url = audio_formats[0]['url']
                        logger.debug(f"Using best available audio format: {audio_formats[0].get('ext')}")
                
                # Fallback to the default URL if no specific audio formats were found
                if not stream_url and 'url' in data:
                    stream_url = data['url']
                    logger.debug("Using default media URL")
                
                if not stream_url and song.url:
                    stream_url = song.url
                    logger.debug("Using song.url as fallback")
                
                if not stream_url:
                    raise Exception("Could not find a valid audio stream URL")
                
                # Create the audio source using the chosen URL
                try:
                    logger.debug(f"Creating FFmpegPCMAudio with URL: {stream_url[:50]}...")
                    return discord.FFmpegPCMAudio(
                        source=stream_url,
                        executable=ffmpeg_path,
                        before_options=before_options,
                        options=options
                    )
                except Exception as audio_error:
                    last_error = audio_error
                    error_details = str(audio_error)
                    
                    if "ffmpeg was not found" in error_details or "No such file" in error_details:
                        raise Exception(f"FFmpeg not found at: {ffmpeg_path}")
                    else:
                        raise Exception(f"Audio playback error: {error_details}")
                
            except Exception as extraction_error:
                last_error = extraction_error
                logger.error(f"Error in extraction: {extraction_error}")
        
        # If we reach here, all attempts failed
        error_msg = str(last_error) if last_error else "Unknown error"
        logger.error(f"All stream attempts failed: {error_msg}")
        raise Exception(f"Could not play audio: {error_msg}")

class MusicPlayer(commands.Cog):
    """Cog for music player functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.music_queues: Dict[int, MusicQueue] = {}  # {guild_id: MusicQueue}
        self.setup_spotify()
    
    def setup_spotify(self):
        """Set up Spotify client if credentials are available."""
        client_id = config.SPOTIFY_CLIENT_ID
        client_secret = config.SPOTIFY_CLIENT_SECRET
        
        if client_id and client_secret:
            try:
                auth_manager = SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.spotify = spotipy.Spotify(auth_manager=auth_manager)
                logger.info("Spotify client initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize Spotify client: {e}")
                self.spotify = None
                return False
        else:
            logger.warning("Spotify credentials not found, Spotify functionality will be limited")
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
        
        # Check if it's a Spotify URL
        if "open.spotify.com" in query:
            await ctx.send("🔍 Processing Spotify link...")
            
            # If Spotify is not configured
            if self.spotify is None:
                await ctx.send("⚠️ Spotify integration is not configured. Please provide a YouTube URL or search query instead.")
                return
            
            songs = await self.process_spotify_url(query)
            
            if not songs:
                await ctx.send("❌ Failed to process Spotify URL. Make sure it's a valid track, album, or playlist URL.")
                return
            
            # Add the songs to the queue
            for song in songs:
                queue.add(song)
            
            await ctx.send(f"➕ Added {len(songs)} songs from Spotify to the queue!")
            
            # Start playing if not already playing
            if not ctx.voice_client.is_playing() and not queue.is_empty():
                await self.play_next_song(ctx)
            
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
                audio_source = await YTDLSource.stream_audio(song)
                
                if not audio_source:
                    raise Exception("Failed to create audio source")
                    
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
