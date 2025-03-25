import os
import discord
from discord.ext import commands
import logging
import asyncio
from config import Config

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("discord_bot")

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Need members intent for the actor game

bot = commands.Bot(command_prefix=commands.when_mentioned_or(Config.PREFIX), intents=intents)

# Bot events
@bot.event
async def on_ready():
    """Event fired when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} guilds')
    
    # Load cogs
    for cog in ['cogs.actor_game', 'cogs.music']:
        try:
            await bot.load_extension(cog)
            logger.info(f'Loaded extension {cog}')
        except Exception as e:
            logger.error(f'Failed to load extension {cog}: {e}')
    
    # Set bot activity
    await bot.change_presence(activity=discord.Game(name=f"{Config.PREFIX}help for commands"))

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for commands."""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Command not found. Use `{Config.PREFIX}help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param.name}. "
                       f"Please check `{Config.PREFIX}help {ctx.command.name}` for usage.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(f"I need the following permissions to run this command: {', '.join(error.missing_permissions)}")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds.")
    else:
        logger.error(f"Command error in {ctx.command}: {error}")
        await ctx.send(f"An error occurred while executing the command: {str(error)}")

@bot.command(name="ping")
async def ping(ctx):
    """Check if the bot is responsive."""
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! Bot latency: {latency}ms")

@bot.command(name="info")
async def info(ctx):
    """Display information about the bot."""
    embed = discord.Embed(
        title="Discord Game Bot",
        description="A bot with games and music functionality",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Features", value="• Guess the Actor game\n• Music playback from YouTube and Spotify", inline=False)
    embed.add_field(name="Prefix", value=f"`{Config.PREFIX}` or mention the bot", inline=False)
    embed.add_field(name="Commands", value=f"Use `{Config.PREFIX}help` to see all commands", inline=False)
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    # Get the bot token from environment variables
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        logger.error("No Discord token found in environment variables!")
        exit(1)
    
    # Run the bot
    asyncio.run(bot.start(token))
