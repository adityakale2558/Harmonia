import discord
from discord.ext import commands
import asyncio
import logging
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import aiohttp
import re
import os
from typing import Dict, List, Optional
from config import Config
from utils.music_utils import get_lyrics, create_queue_embed, format_duration

logger = logging.getLogger("discord_bot.music")

# Set up YT-DLP options for extracting audio
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

# FFMPEG options for playing audio in voice channel
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# Create regex patterns for url matching
YOUTUBE_REGEX = re.compile(r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})')
SPOTIFY_TRACK_REGEX = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')
SPOTIFY_PLAYLIST_REGEX = re.compile(r'https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)')

class MusicPlayer:
    """Class to manage music playback for a specific guild."""
    
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = []
        self.current_index = 0
        self.current_track = None
        self.volume = Config.DEFAULT_VOLUME / 100.0  # Convert to 0-1 range for discord.py
        self.is_playing = False
        self.is_paused = False
        self.voice_client = None
        self.loop = False
        self.text_channel = None
    
    async def join_voice_channel(self, voice_channel, text_channel):
        """Join a voice channel."""
        self.text_channel = text_channel
        
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.move_to(voice_channel)
        else:
            self.voice_client = await voice_channel.connect()
    
    async def leave_voice_channel(self):
        """Leave the voice channel and clean up resources."""
        if self.voice_client and self.voice_client.is_connected():
            self.is_playing = False
            self.is_paused = False
            self.queue = []
            self.current_index = 0
            self.current_track = None
            await self.voice_client.disconnect()
            self.voice_client = None
    
    async def add_to_queue(self, track):
        """Add a track to the queue."""
        self.queue.append(track)
        
        # Start playing if not already playing
        if not self.is_playing and not self.is_paused:
            await self.play()
    
    async def play(self):
        """Start or resume playback."""
        if not self.voice_client:
            await self.text_channel.send("I'm not connected to a voice channel!")
            return
        
        if self.is_paused:
            self.is_paused = False
            self.voice_client.resume()
            await self.text_channel.send("▶️ Resumed playback.")
            return
        
        if not self.queue:
            await self.text_channel.send("The queue is empty!")
            return
        
        if self.current_index >= len(self.queue):
            self.current_index = 0
            if not self.queue:
                self.is_playing = False
                await self.text_channel.send("Finished playing all tracks.")
                return
        
        self.is_playing = True
        self.current_track = self.queue[self.current_index]
        
        # Get the audio URL from YouTube
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        try:
            info = await asyncio.to_thread(ytdl.extract_info, self.current_track['url'], download=False)
            audio_url = info['url']
            
            # Create audio source with volume control
            audio_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS),
                volume=self.volume
            )
            
            # Play the audio
            self.voice_client.play(
                audio_source,
                after=lambda e: asyncio.run_coroutine_threadsafe(self._play_next(e), self.bot.loop)
            )
            
            # Send now playing message
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{self.current_track['title']}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Duration", value=format_duration(self.current_track['duration']), inline=True)
            embed.add_field(name="Requested by", value=self.current_track['requester'].mention, inline=True)
            embed.set_footer(text=f"Track {self.current_index + 1}/{len(self.queue)}")
            
            await self.text_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error playing track: {e}")
            await self.text_channel.send(f"Error playing track: {str(e)}")
            await self._play_next(e)
    
    async def _play_next(self, error=None):
        """Play the next track in the queue."""
        if error:
            logger.error(f"Error during playback: {error}")
            await self.text_channel.send(f"An error occurred during playback: {error}")
        
        if self.loop:
            # Stay on the same track if looping
            pass
        else:
            # Move to the next track
            self.current_index += 1
        
        # Check if we've reached the end of the queue
        if self.current_index >= len(self.queue):
            if self.loop:
                self.current_index = 0
            else:
                self.is_playing = False
                return
        
        # Play the next track
        await self.play()
    
    async def skip(self):
        """Skip the current track."""
        if not self.voice_client or not self.is_playing:
            return False
        
        self.voice_client.stop()
        return True
    
    async def pause(self):
        """Pause playback."""
        if not self.voice_client or not self.is_playing or self.is_paused:
            return False
        
        self.is_paused = True
        self.voice_client.pause()
        return True
    
    async def set_volume(self, volume):
        """Set the playback volume (0-100)."""
        # Validate volume range
        volume = max(0, min(100, volume))
        self.volume = volume / 100.0
        
        # Update current audio source volume if playing
        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = self.volume
        
        return volume
    
    async def clear_queue(self):
        """Clear the queue."""
        if self.is_playing:
            # Keep the current track
            current = self.queue[self.current_index]
            self.queue = [current]
            self.current_index = 0
        else:
            self.queue = []
            self.current_index = 0
    
    async def shuffle_queue(self):
        """Shuffle the queue."""
        if not self.queue:
            return False
        
        if self.is_playing:
            # Keep the current track at its position
            current = self.queue[self.current_index]
            remaining = self.queue[self.current_index + 1:]
            previous = self.queue[:self.current_index]
            
            import random
            random.shuffle(previous)
            random.shuffle(remaining)
            
            self.queue = previous + [current] + remaining
            self.current_index = len(previous)
        else:
            import random
            random.shuffle(self.queue)
        
        return True

class Music(commands.Cog):
    """Music player commands for playing audio from YouTube and Spotify."""
    
    def __init__(self, bot):
        self.bot = bot
        self.players = {}  # Dictionary to store music players for each guild
        
        # Setup Spotify client if credentials are provided
        if Config.SPOTIFY_CLIENT_ID and Config.SPOTIFY_CLIENT_SECRET:
            self.spotify = spotipy.Spotify(
                client_credentials_manager=SpotifyClientCredentials(
                    client_id=Config.SPOTIFY_CLIENT_ID,
                    client_secret=Config.SPOTIFY_CLIENT_SECRET
                )
            )
        else:
            self.spotify = None
            logger.warning("Spotify credentials not provided. Spotify integration will be disabled.")
    
    def get_player(self, guild_id):
        """Get or create a music player for a guild."""
        if guild_id not in self.players:
            self.players[guild_id] = MusicPlayer(self.bot, guild_id)
        return self.players[guild_id]
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Event fired when the cog is loaded."""
        logger.info("Music cog is ready")
    
    @commands.command(name="join")
    async def join(self, ctx):
        """Join the user's voice channel."""
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel to use this command.")
            return
        
        voice_channel = ctx.author.voice.channel
        player = self.get_player(ctx.guild.id)
        
        await player.join_voice_channel(voice_channel, ctx.channel)
        await ctx.send(f"Joined {voice_channel.name}")
    
    @commands.command(name="leave", aliases=["disconnect", "dc"])
    async def leave(self, ctx):
        """Leave the voice channel."""
        player = self.get_player(ctx.guild.id)
        
        if not player.voice_client:
            await ctx.send("I'm not in a voice channel!")
            return
        
        await player.leave_voice_channel()
        await ctx.send("Left the voice channel.")
    
    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, query: str = None):
        """Play a song from YouTube or Spotify."""
        if not query:
            # If no query provided, try to resume playback
            player = self.get_player(ctx.guild.id)
            if player.is_paused:
                await player.play()
                return
            else:
                await ctx.send(f"Please provide a song to play. Example: `{Config.PREFIX}play despacito`")
                return
        
        # Join voice channel if not already in one
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel to use this command.")
            return
        
        voice_channel = ctx.author.voice.channel
        player = self.get_player(ctx.guild.id)
        
        if not player.voice_client or not player.voice_client.is_connected():
            await player.join_voice_channel(voice_channel, ctx.channel)
        
        # Check if the queue is full
        if len(player.queue) >= Config.MAX_QUEUE_SIZE:
            await ctx.send(f"The queue is full ({Config.MAX_QUEUE_SIZE} tracks maximum).")
            return
        
        # Detect if query is a Spotify URL
        spotify_track_match = SPOTIFY_TRACK_REGEX.match(query)
        spotify_playlist_match = SPOTIFY_PLAYLIST_REGEX.match(query)
        
        if spotify_track_match and self.spotify:
            # Handle Spotify track
            track_id = spotify_track_match.group(1)
            await self._handle_spotify_track(ctx, track_id, player)
        
        elif spotify_playlist_match and self.spotify:
            # Handle Spotify playlist
            playlist_id = spotify_playlist_match.group(1)
            await self._handle_spotify_playlist(ctx, playlist_id, player)
        
        else:
            # Handle YouTube or search query
            await self._handle_youtube_query(ctx, query, player)
    
    async def _handle_spotify_track(self, ctx, track_id, player):
        """Handle playing a Spotify track."""
        await ctx.send("🔍 Fetching track from Spotify...")
        
        try:
            track = self.spotify.track(track_id)
            
            # Get artist and track name for YouTube search
            artist = track['artists'][0]['name']
            title = track['name']
            search_query = f"{artist} - {title}"
            
            # Create track object
            track_obj = {
                'title': f"{title} - {artist}",
                'url': f"ytsearch:{search_query}",
                'duration': track['duration_ms'] // 1000,  # Convert ms to seconds
                'requester': ctx.author,
                'source': 'spotify'
            }
            
            await player.add_to_queue(track_obj)
            await ctx.send(f"Added to queue: **{track_obj['title']}**")
            
        except Exception as e:
            logger.error(f"Error fetching Spotify track: {e}")
            await ctx.send(f"Error fetching track from Spotify: {str(e)}")
    
    async def _handle_spotify_playlist(self, ctx, playlist_id, player):
        """Handle playing a Spotify playlist."""
        await ctx.send("🔍 Fetching playlist from Spotify...")
        
        try:
            results = self.spotify.playlist_items(playlist_id)
            tracks = results['items']
            
            # Get additional tracks if playlist has more than 100 tracks
            while results['next']:
                results = self.spotify.next(results)
                tracks.extend(results['items'])
            
            if not tracks:
                await ctx.send("This playlist is empty!")
                return
            
            # Limit the number of tracks to add
            max_tracks = min(len(tracks), Config.MAX_QUEUE_SIZE - len(player.queue))
            if max_tracks <= 0:
                await ctx.send("The queue is full. Cannot add more tracks.")
                return
            
            await ctx.send(f"Adding {max_tracks} tracks from playlist to queue...")
            
            for i, item in enumerate(tracks[:max_tracks]):
                track = item['track']
                artist = track['artists'][0]['name']
                title = track['name']
                search_query = f"{artist} - {title}"
                
                track_obj = {
                    'title': f"{title} - {artist}",
                    'url': f"ytsearch:{search_query}",
                    'duration': track['duration_ms'] // 1000,
                    'requester': ctx.author,
                    'source': 'spotify'
                }
                
                await player.add_to_queue(track_obj)
                
                # Send update for every 5 tracks added
                if (i + 1) % 5 == 0 or i + 1 == max_tracks:
                    await ctx.send(f"Added {i + 1}/{max_tracks} tracks to queue")
            
        except Exception as e:
            logger.error(f"Error fetching Spotify playlist: {e}")
            await ctx.send(f"Error fetching playlist from Spotify: {str(e)}")
    
    async def _handle_youtube_query(self, ctx, query, player):
        """Handle playing a YouTube URL or search query."""
        # Check if the query is a YouTube URL
        youtube_match = YOUTUBE_REGEX.match(query)
        
        if youtube_match:
            url = query
        else:
            # If not a URL, treat as a search query
            url = f"ytsearch:{query}"
        
        await ctx.send("🔍 Searching...")
        
        # Extract info from YouTube
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        
        try:
            info = await asyncio.to_thread(ytdl.extract_info, url, download=False)
            
            # Handle search results
            if 'entries' in info:
                if not info['entries']:
                    await ctx.send("No search results found.")
                    return
                
                info = info['entries'][0]
            
            # Create track object
            track = {
                'title': info['title'],
                'url': info['webpage_url'],
                'duration': info.get('duration', 0),
                'requester': ctx.author,
                'source': 'youtube'
            }
            
            await player.add_to_queue(track)
            await ctx.send(f"Added to queue: **{track['title']}**")
            
        except Exception as e:
            logger.error(f"Error extracting info from YouTube: {e}")
            await ctx.send(f"Error: {str(e)}")
    
    @commands.command(name="pause")
    async def pause(self, ctx):
        """Pause the current song."""
        player = self.get_player(ctx.guild.id)
        
        if await player.pause():
            await ctx.send("⏸️ Paused playback.")
        else:
            await ctx.send("Nothing is playing or already paused.")
    
    @commands.command(name="resume", aliases=["unpause"])
    async def resume(self, ctx):
        """Resume the paused song."""
        player = self.get_player(ctx.guild.id)
        
        if player.is_paused:
            await player.play()
        else:
            await ctx.send("Playback is not paused.")
    
    @commands.command(name="skip", aliases=["next"])
    async def skip(self, ctx):
        """Skip the current song."""
        player = self.get_player(ctx.guild.id)
        
        if await player.skip():
            await ctx.send("⏭️ Skipped to the next track.")
        else:
            await ctx.send("Nothing is playing.")
    
    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx):
        """Display the current music queue."""
        player = self.get_player(ctx.guild.id)
        
        if not player.queue:
            await ctx.send("The queue is empty.")
            return
        
        queue_embed = create_queue_embed(player.queue, player.current_index, player.loop)
        await ctx.send(embed=queue_embed)
    
    @commands.command(name="clear")
    async def clear(self, ctx):
        """Clear the music queue."""
        player = self.get_player(ctx.guild.id)
        
        await player.clear_queue()
        await ctx.send("🧹 Queue cleared.")
    
    @commands.command(name="shuffle")
    async def shuffle(self, ctx):
        """Shuffle the music queue."""
        player = self.get_player(ctx.guild.id)
        
        if await player.shuffle_queue():
            await ctx.send("🔀 Queue shuffled!")
        else:
            await ctx.send("The queue is empty.")
    
    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx, volume: int = None):
        """Set the volume (0-100)."""
        player = self.get_player(ctx.guild.id)
        
        if volume is None:
            # Display current volume
            current_vol = int(player.volume * 100)
            await ctx.send(f"🔊 Current volume: {current_vol}%")
            return
        
        new_vol = await player.set_volume(volume)
        await ctx.send(f"🔊 Volume set to {new_vol}%")
    
    @commands.command(name="loop")
    async def loop(self, ctx):
        """Toggle loop mode."""
        player = self.get_player(ctx.guild.id)
        
        player.loop = not player.loop
        status = "enabled" if player.loop else "disabled"
        await ctx.send(f"🔁 Loop mode {status}.")
    
    @commands.command(name="nowplaying", aliases=["np"])
    async def now_playing(self, ctx):
        """Show information about the currently playing song."""
        player = self.get_player(ctx.guild.id)
        
        if not player.is_playing or not player.current_track:
            await ctx.send("Nothing is playing right now.")
            return
        
        track = player.current_track
        
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{track['title']}**",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Duration", value=format_duration(track['duration']), inline=True)
        embed.add_field(name="Requested by", value=track['requester'].mention, inline=True)
        
        if player.is_paused:
            embed.add_field(name="Status", value="⏸️ Paused", inline=True)
        else:
            embed.add_field(name="Status", value="▶️ Playing", inline=True)
        
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        embed.add_field(name="Loop", value="Enabled" if player.loop else "Disabled", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name="lyrics")
    async def lyrics(self, ctx, *, song_name: str = None):
        """Get lyrics for the currently playing song or a specified song."""
        player = self.get_player(ctx.guild.id)
        
        if not song_name and player.current_track:
            song_name = player.current_track['title']
        elif not song_name:
            await ctx.send("Please provide a song name or play a song first.")
            return
        
        await ctx.send(f"🔍 Searching for lyrics: **{song_name}**")
        
        try:
            lyrics = await get_lyrics(song_name)
            
            if not lyrics:
                await ctx.send(f"Lyrics for **{song_name}** not found.")
                return
            
            # Split lyrics into chunks if too long
            max_chars = 4000  # Discord embed description limit is 4096
            chunks = []
            
            for i in range(0, len(lyrics), max_chars):
                chunks.append(lyrics[i:i + max_chars])
            
            # Send the first chunk with song info
            embed = discord.Embed(
                title=f"Lyrics for {song_name}",
                description=chunks[0],
                color=discord.Color.blue()
            )
            
            messages = [await ctx.send(embed=embed)]
            
            # Send additional chunks if needed
            for i, chunk in enumerate(chunks[1:], 1):
                embed = discord.Embed(
                    title=f"Lyrics for {song_name} (continued {i}/{len(chunks)-1})",
                    description=chunk,
                    color=discord.Color.blue()
                )
                messages.append(await ctx.send(embed=embed))
            
        except Exception as e:
            logger.error(f"Error fetching lyrics: {e}")
            await ctx.send(f"Error fetching lyrics: {str(e)}")

async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(Music(bot))
