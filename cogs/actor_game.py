import discord
from discord.ext import commands
import asyncio
import random
import json
import logging
import os
from typing import Dict, List, Optional, Set
from config import Config
from utils.actor_database import ActorDatabase

logger = logging.getLogger("discord_bot.actor_game")

class ActorGame(commands.Cog):
    """
    A Discord game where players need to guess the actor assigned to them
    by asking questions to other players.
    """
    
    def __init__(self, bot):
        self.bot = bot
        self.actor_db = ActorDatabase()
        self.active_games = {}  # Dictionary to store active games by channel ID
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Initializes the actor database when the cog is loaded."""
        await self.actor_db.load_actors()
        logger.info("Actor Game cog is ready")
    
    @commands.group(name="actor", invoke_without_command=True)
    async def actor_group(self, ctx):
        """Command group for the actor guessing game."""
        await ctx.send(f"Use `{Config.PREFIX}actor start` to start a new game or "
                      f"`{Config.PREFIX}actor help` for more information.")
    
    @actor_group.command(name="help")
    async def actor_help(self, ctx):
        """Display help information for the actor game."""
        embed = discord.Embed(
            title="Guess the Actor - Help",
            description="A game where players try to guess which actor they've been assigned.",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="How to Play", 
            value=("1. Start a game with `!actor start`\n"
                  "2. Players join with `!actor join`\n"
                  "3. Select a category with `!actor category [hollywood/bollywood]`\n"
                  "4. Start the game with `!actor begin`\n"
                  "5. Each player will be assigned an actor (they won't know who)\n"
                  "6. Players take turns asking yes/no questions to figure out their actor\n"
                  "7. Guess your actor with `!actor guess [name]`"), 
            inline=False
        )
        
        embed.add_field(
            name="Commands", 
            value=(f"`{Config.PREFIX}actor start` - Start a new game in this channel\n"
                  f"`{Config.PREFIX}actor join` - Join the game in this channel\n"
                  f"`{Config.PREFIX}actor category [type]` - Select Hollywood or Bollywood\n"
                  f"`{Config.PREFIX}actor begin` - Begin the game after all players joined\n"
                  f"`{Config.PREFIX}actor guess [name]` - Guess your assigned actor\n"
                  f"`{Config.PREFIX}actor end` - End the current game"), 
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @actor_group.command(name="start")
    async def start_game(self, ctx):
        """Start a new actor guessing game in the current channel."""
        channel_id = ctx.channel.id
        
        # Check if there's already an active game in this channel
        if channel_id in self.active_games:
            await ctx.send("There's already an active game in this channel. "
                           f"Use `{Config.PREFIX}actor end` to end it first.")
            return
        
        # Create a new game
        self.active_games[channel_id] = {
            "host": ctx.author,
            "players": [ctx.author],
            "player_ids": {ctx.author.id},
            "category": None,
            "started": False,
            "actor_assignments": {},
            "guessed_correctly": set(),
            "turn_index": 0
        }
        
        await ctx.send(f"Actor guessing game started by {ctx.author.mention}! "
                       f"Other players can join with `{Config.PREFIX}actor join`. "
                       f"The host should select a category with `{Config.PREFIX}actor category [hollywood/bollywood]`.")
    
    @actor_group.command(name="join")
    async def join_game(self, ctx):
        """Join an existing actor guessing game in the current channel."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send(f"There's no active game in this channel. Start one with `{Config.PREFIX}actor start`.")
            return
        
        game = self.active_games[channel_id]
        
        # Check if the game has already started
        if game["started"]:
            await ctx.send("This game has already started. Wait for the current game to end.")
            return
        
        # Check if the player is already in the game
        if ctx.author.id in game["player_ids"]:
            await ctx.send("You've already joined this game!")
            return
        
        # Check if max players limit is reached
        if len(game["players"]) >= Config.MAX_PLAYERS:
            await ctx.send(f"The game is full (maximum {Config.MAX_PLAYERS} players).")
            return
        
        # Add the player to the game
        game["players"].append(ctx.author)
        game["player_ids"].add(ctx.author.id)
        
        await ctx.send(f"{ctx.author.mention} has joined the game! "
                      f"Current players: {', '.join(player.display_name for player in game['players'])}")
    
    @actor_group.command(name="category")
    async def set_category(self, ctx, category: str = None):
        """Set the category for the actor guessing game (hollywood/bollywood)."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send(f"There's no active game in this channel. Start one with `{Config.PREFIX}actor start`.")
            return
        
        game = self.active_games[channel_id]
        
        # Check if the command user is the host
        if ctx.author != game["host"]:
            await ctx.send("Only the game host can set the category.")
            return
        
        # Check if the game has already started
        if game["started"]:
            await ctx.send("Cannot change the category after the game has started.")
            return
        
        # Validate and set the category
        if category and category.lower() in ["hollywood", "bollywood"]:
            game["category"] = category.lower()
            await ctx.send(f"Category set to {category.title()}. "
                           f"Start the game with `{Config.PREFIX}actor begin` when everyone has joined.")
        else:
            await ctx.send(f"Invalid category. Please choose either 'hollywood' or 'bollywood'.\n"
                           f"Example: `{Config.PREFIX}actor category hollywood`")
    
    @actor_group.command(name="begin")
    async def begin_game(self, ctx):
        """Start the actor guessing game after all players have joined."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send(f"There's no active game in this channel. Start one with `{Config.PREFIX}actor start`.")
            return
        
        game = self.active_games[channel_id]
        
        # Check if the command user is the host
        if ctx.author != game["host"]:
            await ctx.send("Only the game host can begin the game.")
            return
        
        # Check if the game has already started
        if game["started"]:
            await ctx.send("The game has already started!")
            return
        
        # Check if a category has been selected
        if not game["category"]:
            await ctx.send(f"Please select a category first with `{Config.PREFIX}actor category [hollywood/bollywood]`.")
            return
        
        # Check if there are enough players
        if len(game["players"]) < Config.MIN_PLAYERS:
            await ctx.send(f"Not enough players to start the game. Need at least {Config.MIN_PLAYERS} players.")
            return
        
        # Assign actors to players
        actors = await self.actor_db.get_actors_by_category(game["category"])
        if len(actors) < len(game["players"]):
            await ctx.send(f"Not enough actors in the {game['category']} category. Please choose another category.")
            return
        
        # Randomly select actors for each player
        selected_actors = random.sample(actors, len(game["players"]))
        
        # Assign actors to players
        game["actor_assignments"] = {player.id: actor for player, actor in zip(game["players"], selected_actors)}
        game["started"] = True
        
        # Send the game start message
        await ctx.send("The Actor Guessing Game has begun! Each player has been assigned an actor.")
        
        # Send private messages to each player about other players' assigned actors
        for player in game["players"]:
            message = "**Actor Assignments (Don't share this information!):**\n"
            for other_player in game["players"]:
                if other_player.id != player.id:
                    message += f"{other_player.display_name}: **{game['actor_assignments'][other_player.id]}**\n"
            message += f"\nYou need to figure out your own actor by asking questions! It's a {game['category'].title()} actor."
            
            try:
                await player.send(message)
            except discord.Forbidden:
                await ctx.send(f"{player.mention}, I couldn't send you a private message with the actor assignments. "
                              "Please enable direct messages from server members for this game.")
        
        # Start the game with the first player's turn
        game["turn_index"] = 0
        current_player = game["players"][game["turn_index"]]
        
        await ctx.send(f"It's {current_player.mention}'s turn! Ask a yes/no question to help figure out your actor. "
                      "Other players can answer in the channel.")
    
    @actor_group.command(name="guess")
    async def guess_actor(self, ctx, *, actor_name: str = None):
        """Guess the actor assigned to you."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send(f"There's no active game in this channel. Start one with `{Config.PREFIX}actor start`.")
            return
        
        game = self.active_games[channel_id]
        
        # Check if the game has started
        if not game["started"]:
            await ctx.send("The game hasn't started yet!")
            return
        
        # Check if the player is in the game
        if ctx.author.id not in game["player_ids"]:
            await ctx.send("You're not in this game!")
            return
        
        # Check if the player has already guessed correctly
        if ctx.author.id in game["guessed_correctly"]:
            await ctx.send("You've already guessed your actor correctly!")
            return
        
        # Check if an actor name was provided
        if not actor_name:
            await ctx.send(f"Please provide an actor name to guess. Example: `{Config.PREFIX}actor guess Tom Hanks`")
            return
        
        # Get the assigned actor for the player
        assigned_actor = game["actor_assignments"][ctx.author.id]
        
        # Check if the guess is correct (case-insensitive comparison)
        if actor_name.lower() == assigned_actor.lower():
            game["guessed_correctly"].add(ctx.author.id)
            await ctx.send(f"🎉 Congratulations {ctx.author.mention}! **{assigned_actor}** is correct!")
            
            # Check if all players have guessed correctly
            if len(game["guessed_correctly"]) == len(game["players"]):
                await ctx.send("🏆 All players have guessed their actors correctly! The game is now over.")
                del self.active_games[channel_id]
                return
            
            # Move to the next player's turn
            self._next_player_turn(game)
            current_player = game["players"][game["turn_index"]]
            
            # Skip players who have already guessed correctly
            while current_player.id in game["guessed_correctly"]:
                self._next_player_turn(game)
                current_player = game["players"][game["turn_index"]]
            
            await ctx.send(f"It's now {current_player.mention}'s turn!")
        else:
            await ctx.send(f"Sorry {ctx.author.mention}, that's not the actor assigned to you. Try asking more questions!")
    
    @actor_group.command(name="end")
    async def end_game(self, ctx):
        """End the current actor guessing game."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send("There's no active game in this channel.")
            return
        
        game = self.active_games[channel_id]
        
        # Check if the command user is the host or has manage messages permission
        if ctx.author != game["host"] and not ctx.channel.permissions_for(ctx.author).manage_messages:
            await ctx.send("Only the game host or moderators can end the game.")
            return
        
        # Show the actor assignments if the game had started
        if game["started"]:
            message = "**Game ended! Actor assignments were:**\n"
            for player in game["players"]:
                actor = game["actor_assignments"][player.id]
                guessed = "✅" if player.id in game["guessed_correctly"] else "❌"
                message += f"{player.display_name}: {actor} {guessed}\n"
            
            await ctx.send(message)
        else:
            await ctx.send("Game ended without starting.")
        
        # Remove the game
        del self.active_games[channel_id]
    
    @actor_group.command(name="status")
    async def game_status(self, ctx):
        """Show the current status of the actor guessing game."""
        channel_id = ctx.channel.id
        
        # Check if there's an active game in this channel
        if channel_id not in self.active_games:
            await ctx.send("There's no active game in this channel.")
            return
        
        game = self.active_games[channel_id]
        
        # Create an embed with the game status
        embed = discord.Embed(
            title="Actor Guessing Game Status",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Host", value=game["host"].mention, inline=False)
        embed.add_field(name="Category", value=game["category"].title() if game["category"] else "Not selected", inline=False)
        
        player_list = ""
        for i, player in enumerate(game["players"]):
            status = ""
            if game["started"]:
                if player.id in game["guessed_correctly"]:
                    status = " (Guessed correctly ✅)"
                elif i == game["turn_index"]:
                    status = " (Current turn 🎮)"
            player_list += f"{player.mention}{status}\n"
        
        embed.add_field(name=f"Players ({len(game['players'])})", value=player_list, inline=False)
        embed.add_field(name="Game Started", value="Yes" if game["started"] else "No", inline=False)
        
        if game["started"]:
            correct_guesses = f"{len(game['guessed_correctly'])}/{len(game['players'])}"
            embed.add_field(name="Correct Guesses", value=correct_guesses, inline=False)
        
        await ctx.send(embed=embed)
    
    def _next_player_turn(self, game):
        """Helper method to advance to the next player's turn."""
        game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])

async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(ActorGame(bot))
