import discord
from discord.ext import commands, tasks
import asyncio
import logging
import random
import time
import json
import os
from typing import Dict, List, Optional, Set

import config
from utils.game_manager import GameSession, Player

logger = logging.getLogger('discord_bot.actor_game')

class ActorGame(commands.Cog):
    """Cog that implements the 'Guess It' game functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.game_sessions: Dict[int, GameSession] = {}  # {guild_id: GameSession}
        self.actors = self._load_actors()
        self.check_inactive_games.start()
    
    def _load_actors(self) -> Dict[str, List[str]]:
        """Load actor data from the JSON file."""
        try:
            with open('data/actors.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("Actors database file not found. Creating a new one.")
            # Create a default actors dictionary
            default_actors = {
                "Hollywood": [
                    "Tom Hanks", "Leonardo DiCaprio", "Brad Pitt", "Meryl Streep", 
                    "Jennifer Lawrence", "Denzel Washington", "Robert Downey Jr.",
                    "Scarlett Johansson", "Tom Cruise", "Emma Stone"
                ],
                "Bollywood": [
                    "Shah Rukh Khan", "Amitabh Bachchan", "Deepika Padukone", 
                    "Aamir Khan", "Priyanka Chopra", "Salman Khan", "Alia Bhatt",
                    "Hrithik Roshan", "Katrina Kaif", "Ranbir Kapoor"
                ]
            }
            
            # Save the default actors to the file
            os.makedirs('data', exist_ok=True)
            with open('data/actors.json', 'w', encoding='utf-8') as f:
                json.dump(default_actors, f, indent=4)
            
            return default_actors
    
    def cog_unload(self):
        """Cleanup when the cog is unloaded."""
        self.check_inactive_games.cancel()
    
    @tasks.loop(minutes=1)
    async def check_inactive_games(self):
        """Check and remove inactive game sessions."""
        current_time = time.time()
        
        for guild_id, session in list(self.game_sessions.items()):
            if current_time - session.last_activity > config.GAME_TIMEOUT:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    await channel.send("⏲️ Game ended due to inactivity.")
                
                del self.game_sessions[guild_id]
                logger.info(f"Game session in guild {guild_id} ended due to inactivity")
    
    @check_inactive_games.before_loop
    async def before_check_inactive_games(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
    
    @commands.command(name="startgame")
    async def start_game(self, ctx, category=None):
        """
        Start a new 'Guess It' game.
        
        Usage: =startgame [category]
        Available categories: Hollywood, Bollywood, Apps, Food
        """
        guild_id = ctx.guild.id
        
        # Check if a game is already running in this guild
        if guild_id in self.game_sessions:
            await ctx.send("❌ A game is already running in this server. Use `=endgame` to end it first.")
            return
        
        # Validate category
        if category is None:
            # If no category is provided, list available categories
            categories_list = ", ".join(config.CATEGORIES)
            await ctx.send(f"Please specify a category: `=startgame <category>`\nAvailable categories: {categories_list}")
            return
        
        # Check if the provided category matches any of the allowed categories (case insensitive)
        for allowed_category in config.CATEGORIES:
            if category.lower() == allowed_category.lower():
                category = allowed_category
                break
        else:  # This else belongs to the for loop, executes if no break occurred
            categories_list = ", ".join(config.CATEGORIES)
            await ctx.send(f"❌ Invalid category. Available categories: {categories_list}")
            return
        
        # Create a new game session
        session = GameSession(
            host_id=ctx.author.id,
            channel_id=ctx.channel.id,
            category=category
        )
        
        # Add the host as the first player
        session.add_player(Player(
            id=ctx.author.id,
            name=ctx.author.display_name
        ))
        
        self.game_sessions[guild_id] = session
        
        # Send game start message
        embed = discord.Embed(
            title="🎭 Guess It Game",
            description=f"Game started with category: **{category}**\n\n"
                       f"Other players can join with `=join`\n"
                       f"When ready, the host can use `=assign` to assign items to players.",
            color=discord.Color.green()
        )
        embed.add_field(name="Players", value=ctx.author.mention, inline=False)
        embed.add_field(name="How to Play", value=(
            "1. Join the game with `=join`\n"
            "2. The host will assign items to everyone with `=assign`\n"
            "3. You'll see everyone's item except your own\n"
            "4. Ask questions to figure out your item using `=question <your question>`\n"
            "5. When you're ready to guess, use `=guess <item name>`"
        ), inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Game started in guild {guild_id} with category {category}")
    
    @commands.command(name="join")
    async def join_game(self, ctx):
        """Join an ongoing 'Guess It' game."""
        guild_id = ctx.guild.id
        
        # Check if a game is running in this guild
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running. Start one with `=startgame`.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Check if the game is already in progress (actors assigned)
        if session.is_in_progress:
            await ctx.send("❌ Can't join, the game is already in progress.")
            return
        
        # Check if the player is already in the game
        if session.get_player(ctx.author.id) is not None:
            await ctx.send("❌ You're already in the game!")
            return
        
        # Check if the maximum number of players has been reached
        if len(session.players) >= config.MAX_PLAYERS:
            await ctx.send(f"❌ Maximum number of players ({config.MAX_PLAYERS}) reached.")
            return
        
        # Add the player to the game
        session.add_player(Player(
            id=ctx.author.id,
            name=ctx.author.display_name
        ))
        
        session.last_activity = time.time()
        
        # Get all player mentions
        player_mentions = [f"<@{player.id}>" for player in session.players]
        
        # Send confirmation message
        await ctx.send(f"✅ {ctx.author.mention} joined the game!")
        
        # Update the players list in an embed
        embed = discord.Embed(
            title="🎭 Guess It Game",
            description=f"Category: **{session.category}**\n\n"
                       f"Current players ({len(session.players)}/{config.MAX_PLAYERS}):",
            color=discord.Color.blue()
        )
        embed.add_field(name="Players", value="\n".join(player_mentions), inline=False)
        embed.set_footer(text=f"Host: {ctx.guild.get_member(session.host_id).display_name} | Use =assign to start when ready")
        
        await ctx.send(embed=embed)
        logger.info(f"Player {ctx.author.id} joined game in guild {guild_id}")
    
    @commands.command(name="assign")
    async def assign_actors(self, ctx):
        """Assign actors to players and start the game (host only)."""
        guild_id = ctx.guild.id
        
        # Check if a game is running in this guild
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running. Start one with `=startgame`.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Check if the command was issued by the host
        if ctx.author.id != session.host_id:
            await ctx.send("❌ Only the game host can assign actors.")
            return
        
        # Check if the game is already in progress
        if session.is_in_progress:
            await ctx.send("❌ Actors have already been assigned for this game.")
            return
        
        # Check if there are enough players
        if len(session.players) < config.MIN_PLAYERS:
            await ctx.send(f"❌ Need at least {config.MIN_PLAYERS} players to start. Currently: {len(session.players)}.")
            return
        
        # Get actors for the selected category (case-insensitive)
        category_key = None
        for key in self.actors.keys():
            if key.lower() == session.category.lower():
                category_key = key
                break
        
        if category_key:
            category_actors = self.actors[category_key]
        else:
            category_actors = []
        
        if not category_actors:
            await ctx.send(f"❌ No actors found for category '{session.category}'.")
            return
        
        # Randomly select actors for each player
        selected_actors = random.sample(category_actors, len(session.players))
        
        # Assign actors to players
        for i, player in enumerate(session.players):
            player.actor = selected_actors[i]
        
        session.is_in_progress = True
        session.last_activity = time.time()
        
        # Notify players of actor assignments via DM
        for i, player in enumerate(session.players):
            member = ctx.guild.get_member(player.id)
            if member:
                # Create a list of other players and their actors
                others_actors = []
                for other_player in session.players:
                    if other_player.id != player.id:
                        others_actors.append(f"{other_player.name}: **{other_player.actor}**")
                
                try:
                    # Send DM to player
                    embed = discord.Embed(
                        title="🎭 Your Actor Assignment",
                        description=(
                            f"Game in server: **{ctx.guild.name}**\n"
                            f"Category: **{session.category}**\n\n"
                            f"You need to guess your actor by asking questions!\n"
                            f"Use `=question <your question>` in the game channel to ask questions.\n"
                            f"When ready to guess, use `=guess <actor name>`."
                        ),
                        color=discord.Color.gold()
                    )
                    
                    embed.add_field(
                        name="Other Players' Actors",
                        value="\n".join(others_actors) or "No other players",
                        inline=False
                    )
                    
                    await member.send(embed=embed)
                except discord.Forbidden:
                    # If we can't DM the user
                    await ctx.send(f"⚠️ Couldn't send a DM to {member.mention}. Please enable DMs from server members.")
        
        # Send confirmation in the game channel
        embed = discord.Embed(
            title="🎭 Game Started!",
            description=(
                f"Actors have been assigned to all players via DM!\n\n"
                f"**How to play:**\n"
                f"- You know everyone's actor except your own\n"
                f"- Ask questions with `=question <your question>`\n"
                f"- Others will answer to help you guess\n"
                f"- When ready, guess with `=guess <actor name>`\n"
                f"- You have {config.GUESS_LIMIT} guess attempts"
            ),
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        logger.info(f"Actors assigned in game for guild {guild_id}")
    
    @commands.command(name="question")
    async def ask_question(self, ctx, *, question=None):
        """
        Ask a question to help guess your actor.
        
        Usage: =question Is my actor male?
        """
        guild_id = ctx.guild.id
        
        # Check if a game is running
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Check if the game is in progress
        if not session.is_in_progress:
            await ctx.send("❌ The game hasn't started yet. Wait for the host to assign actors.")
            return
        
        # Check if the user is in the game
        player = session.get_player(ctx.author.id)
        if player is None:
            await ctx.send("❌ You're not in this game.")
            return
        
        # Check if a question was provided
        if not question:
            await ctx.send("❌ You need to ask a question. Use `=question <your question>`")
            return
        
        # Check if the player has already guessed correctly
        if player.has_guessed_correctly:
            await ctx.send("❌ You've already guessed your actor correctly!")
            return
        
        session.last_activity = time.time()
        
        # Send the public question to the channel without the actor name
        public_embed = discord.Embed(
            title="❓ Question",
            description=f"**{ctx.author.display_name}** asks: {question}",
            color=discord.Color.blue()
        )
        
        public_embed.set_footer(text="Others can respond to help them guess!")
        
        await ctx.send(embed=public_embed)
        
        # Send an ephemeral message (only visible to the asker) with the actor name
        ephemeral_embed = discord.Embed(
            title="❓ Your Question",
            description=f"You asked: {question}",
            color=discord.Color.blue()
        )
        
        # Add the player's actor as a field for others to see
        ephemeral_embed.add_field(
            name="Help them guess this actor:",
            value=f"**{player.actor}**",
            inline=False
        )
        
        ephemeral_embed.set_footer(text="Only you can see this message. Others will see your question without the actor name.")
        
        # Send ephemeral message that only the command author can see
        try:
            # For newer versions of discord.py that support ephemeral messages
            await ctx.send(embed=ephemeral_embed, ephemeral=True)
        except TypeError:
            # For older versions where ephemeral is not supported directly in ctx.send
            # Use a private DM instead
            try:
                await ctx.author.send(embed=ephemeral_embed)
            except discord.Forbidden:
                # If DMs are disabled
                await ctx.send("⚠️ I couldn't send you a DM with your actor information. Please enable DMs from server members.")
        
        logger.info(f"Player {ctx.author.id} asked a question in game in guild {guild_id}")
    
    @commands.command(name="guess")
    async def guess_actor(self, ctx, *, actor_name=None):
        """
        Make a guess for your assigned actor.
        
        Usage: =guess Tom Hanks
        """
        guild_id = ctx.guild.id
        
        # Check if a game is running
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Check if the game is in progress
        if not session.is_in_progress:
            await ctx.send("❌ The game hasn't started yet. Wait for the host to assign actors.")
            return
        
        # Check if the user is in the game
        player = session.get_player(ctx.author.id)
        if player is None:
            await ctx.send("❌ You're not in this game.")
            return
        
        # Check if the player has already guessed correctly
        if player.has_guessed_correctly:
            await ctx.send("✅ You've already guessed your actor correctly!")
            return
        
        # Check if a guess was provided
        if not actor_name:
            await ctx.send("❌ You need to provide a guess. Use `=guess <actor name>`")
            return
        
        # Check if the player has used all their guesses
        if player.guess_count >= config.GUESS_LIMIT and not player.has_guessed_correctly:
            await ctx.send(f"❌ You've used all your {config.GUESS_LIMIT} guess attempts! Your actor was **{player.actor}**.")
            return
        
        session.last_activity = time.time()
        player.guess_count += 1
        
        # Check if the guess is correct (case-insensitive)
        if actor_name.lower() == player.actor.lower():
            player.has_guessed_correctly = True
            
            embed = discord.Embed(
                title="🎉 Correct Guess!",
                description=f"**{ctx.author.display_name}** correctly guessed their actor as **{player.actor}**!",
                color=discord.Color.green()
            )
            
            # Check if all players have guessed their actors
            all_guessed = all(p.has_guessed_correctly for p in session.players)
            if all_guessed:
                embed.add_field(
                    name="Game Complete!",
                    value="All players have correctly guessed their actors. The game is now over!",
                    inline=False
                )
                # End the game
                del self.game_sessions[guild_id]
            else:
                remaining = sum(1 for p in session.players if not p.has_guessed_correctly)
                embed.add_field(
                    name="Status",
                    value=f"{remaining} players still need to guess their actor.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            logger.info(f"Player {ctx.author.id} correctly guessed their actor in guild {guild_id}")
            
        else:
            # Incorrect guess
            guesses_left = config.GUESS_LIMIT - player.guess_count
            
            embed = discord.Embed(
                title="❌ Incorrect Guess",
                description=f"**{ctx.author.display_name}**, that's not your actor!",
                color=discord.Color.red()
            )
            
            if guesses_left > 0:
                embed.add_field(
                    name="Attempts Remaining",
                    value=f"You have {guesses_left} guess(es) left.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Out of Guesses",
                    value=f"You're out of guesses! Your actor was **{player.actor}**.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            logger.info(f"Player {ctx.author.id} made an incorrect guess in guild {guild_id}")
    
    @commands.command(name="endgame")
    async def end_game(self, ctx):
        """End the current 'Guess It' game (host only or admin)."""
        guild_id = ctx.guild.id
        
        # Check if a game is running
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Check if the command was issued by the host or by someone with admin permissions
        if ctx.author.id != session.host_id and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only the game host or an administrator can end the game.")
            return
        
        # Build a summary of the game
        embed = discord.Embed(
            title="🎭 Game Ended",
            description=f"The 'Guess It' game has been ended by {ctx.author.mention}.",
            color=discord.Color.orange()
        )
        
        # List all players and their actors
        players_summary = []
        for player in session.players:
            member = ctx.guild.get_member(player.id)
            if member:
                status = "✅ Guessed correctly" if player.has_guessed_correctly else "❌ Didn't guess"
                players_summary.append(f"{member.mention}: **{player.actor}** - {status}")
        
        if players_summary:
            embed.add_field(
                name="Players & Actors",
                value="\n".join(players_summary),
                inline=False
            )
        
        # End the game and remove from sessions
        del self.game_sessions[guild_id]
        
        await ctx.send(embed=embed)
        logger.info(f"Game ended in guild {guild_id} by user {ctx.author.id}")
    
    @commands.command(name="gamestatus")
    async def game_status(self, ctx):
        """Show the status of the current game."""
        guild_id = ctx.guild.id
        
        # Check if a game is running
        if guild_id not in self.game_sessions:
            await ctx.send("❌ No game is currently running.")
            return
        
        session = self.game_sessions[guild_id]
        
        # Create an embed with game status
        embed = discord.Embed(
            title="🎭 Game Status",
            description=f"Category: **{session.category}**",
            color=discord.Color.blue()
        )
        
        # Add host information
        host = ctx.guild.get_member(session.host_id)
        embed.add_field(
            name="Host",
            value=host.mention if host else "Unknown",
            inline=True
        )
        
        # Add game phase
        phase = "Assigning Actors" if not session.is_in_progress else "Guessing Phase"
        embed.add_field(name="Phase", value=phase, inline=True)
        
        # List players and their status
        if session.is_in_progress:
            player_list = []
            for player in session.players:
                member = ctx.guild.get_member(player.id)
                if member:
                    status = "✅ Guessed correctly" if player.has_guessed_correctly else f"❓ ({config.GUESS_LIMIT - player.guess_count} guesses left)"
                    player_list.append(f"{member.mention}: {status}")
            
            embed.add_field(
                name="Players Status",
                value="\n".join(player_list) or "No players",
                inline=False
            )
        else:
            # If game hasn't started, just list the players
            player_mentions = [f"<@{player.id}>" for player in session.players]
            embed.add_field(
                name=f"Players ({len(session.players)})",
                value="\n".join(player_mentions) or "No players",
                inline=False
            )
        
        await ctx.send(embed=embed)

async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(ActorGame(bot))
