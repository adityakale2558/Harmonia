import discord
from discord.ext import commands
import asyncio
import logging
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

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
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
        ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
        
        # Check if it's already a direct audio URL
        if song.url and (song.url.endswith('.mp3') or song.url.endswith('.m4a')):
            try:
                return discord.FFmpegPCMAudio(song.url, **ffmpeg_options)
            except discord.errors.ClientException as e:
                if "ffmpeg was not found" in str(e):
                    logger.error("FFmpeg was not found. Make sure ffmpeg is installed on the system.")
                    raise Exception("Failed to stream audio: ffmpeg was not found. Bot admin needs to install ffmpeg.")
                else:
                    logger.error(f"Error creating FFmpeg audio: {e}")
                    raise Exception(f"Failed to stream audio: {e}")
        
        # If it's not a direct URL, extract the audio URL
        try:
            data = await asyncio.to_thread(lambda: ytdl.extract_info(song.webpage_url, download=False))
            if 'entries' in data:
                data = data['entries'][0]
            
            # Update song info if needed
            song.url = data.get('url')
            if not song.duration:
                song.duration = data.get('duration')
            if not song.thumbnail:
                song.thumbnail = data.get('thumbnail')
            
            try:
                return discord.FFmpegPCMAudio(song.url, **ffmpeg_options)
            except discord.errors.ClientException as e:
                if "ffmpeg was not found" in str(e):
                    logger.error("FFmpeg was not found. Make sure ffmpeg is installed on the system.")
                    raise Exception("Failed to stream audio: ffmpeg was not found. Bot admin needs to install ffmpeg.")
                else:
                    logger.error(f"Error creating FFmpeg audio: {e}")
                    raise Exception(f"Failed to stream audio: {e}")
        except Exception as e:
            logger.error(f"Error streaming audio: {e}")
            raise Exception(f"Failed to stream audio: {e}")

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
            except Exception as e:
                logger.error(f"Failed to initialize Spotify client: {e}")
                self.spotify = None
        else:
            logger.warning("Spotify credentials not found, Spotify functionality will be limited")
            self.spotify = None
    
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
        queue = self.get_queue(ctx.guild.id)
        
        if queue.is_empty():
            await ctx.send("🎵 Queue is empty. Use `=play` to add songs!")
            return
        
        # Get the next song from the queue
        song = queue.get_next_song()
        
        try:
            # Handle Spotify songs by searching YouTube
            if song.is_spotify:
                await ctx.send(f"🔍 Finding YouTube source for: {song.title}")
                search_query = song.search_query
                # Try to find the song on YouTube
                try:
                    youtube_song = await YTDLSource.create_source(search_query, loop=self.bot.loop)
                    # Update song with YouTube details
                    song.url = youtube_song.url
                    song.webpage_url = youtube_song.webpage_url
                except Exception as e:
                    logger.error(f"Failed to find YouTube source for Spotify song: {e}")
                    await ctx.send(f"❌ Failed to find a YouTube source for: {song.title}")
                    # Try to play the next song
                    await self.play_next_song(ctx)
                    return
            
            # Create the audio source
            audio_source = await YTDLSource.stream_audio(song)
            
            # Set the volume
            volume_transformer = discord.PCMVolumeTransformer(audio_source, volume=queue.volume)
            
            # Play the song
            ctx.voice_client.play(
                volume_transformer,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.song_finished(ctx, e), self.bot.loop
                )
            )
            
            # Send now playing message
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
            
            queue_length = len(queue.songs)
            embed.set_footer(text=f"Songs in queue: {queue_length}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error playing next song: {e}")
            await ctx.send(f"❌ Error playing the song: {str(e)}")
            # Try to play the next song
            await self.play_next_song(ctx)
    
    async def song_finished(self, ctx, error):
        """Called when a song finishes playing."""
        if error:
            logger.error(f"Player error: {error}")
            await ctx.send(f"❌ Player error: {error}")
        
        queue = self.get_queue(ctx.guild.id)
        
        # If there are more songs in the queue, play the next one
        if not queue.is_empty():
            await self.play_next_song(ctx)
    
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
            if queue.current_song is None:
                await ctx.send("❌ No song is currently playing.")
                return
            
            # Remove any "(Official Video)" or similar text from the title
            title = queue.current_song.title
            title = re.sub(r'\([^)]*\)|ft\..*|feat\..*|-\s+[\w\s]+', '', title)
            query = title.strip()
        
        await ctx.send(f"🔍 Searching for lyrics: {query}")
        
        try:
            # Fetch lyrics
            lyrics_data = await fetch_lyrics(query, api_key=config.GENIUS_API_KEY)
            
            if not lyrics_data or not lyrics_data.get('lyrics'):
                await ctx.send(f"❌ Couldn't find lyrics for: {query}")
                return
            
            # Create embeds for the lyrics (Discord has a 2000 character limit per embed)
            title = lyrics_data.get('title', 'Unknown')
            artist = lyrics_data.get('artist', 'Unknown')
            lyrics = lyrics_data.get('lyrics', 'No lyrics found')
            
            # Split lyrics into chunks of 2000 characters or less
            chunks = [lyrics[i:i+2000] for i in range(0, len(lyrics), 2000)]
            
            # Send the first embed with title and artist
            first_embed = discord.Embed(
                title=f"📝 Lyrics: {title}",
                description=chunks[0],
                color=discord.Color.purple()
            )
            first_embed.set_author(name=f"Artist: {artist}")
            
            await ctx.send(embed=first_embed)
            
            # Send the rest of the lyrics in separate embeds
            for chunk in chunks[1:]:
                embed = discord.Embed(
                    description=chunk,
                    color=discord.Color.purple()
                )
                await ctx.send(embed=embed)
            
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
