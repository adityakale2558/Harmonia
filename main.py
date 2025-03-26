import os
import logging
import discord
import asyncio
import time
from discord.ext import commands
import config
from threading import Thread
from app import app, update_bot_status
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('discord_bot')

# Initialize the bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=config.PREFIX, intents=intents, help_command=None)

# Track when the bot started
bot.start_time = None

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} servers')
    
    # Set the start time when the bot comes online
    bot.start_time = datetime.now()
    
    # Load cogs
    await load_cogs()
    
    # Set custom status
    activity = discord.Activity(type=discord.ActivityType.playing, 
                               name=f"{config.PREFIX}help | Guess It")
    await bot.change_presence(activity=activity)
    
    # Update web dashboard status
    update_bot_status(bot)
    
    # Schedule periodic status updates
    asyncio.create_task(update_status_periodically())
    
    print(f'Bot is ready! Logged in as {bot.user.name}')

async def update_status_periodically():
    """Update the bot status in the web dashboard periodically."""
    while True:
        await asyncio.sleep(30)  # Update every 30 seconds
        update_bot_status(bot)
        logger.debug("Updated bot status in web dashboard")

async def load_cogs():
    """Load all cogs/extensions for the bot."""
    initial_extensions = [
        'cogs.actor_game',
        # 'cogs.music_player'  # Disabled music player to focus on the actor game
    ]
    
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            logger.info(f'Loaded extension: {extension}')
        except Exception as e:
            logger.error(f'Failed to load extension {extension}: {e}')

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors
        return
    
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
        return
    
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided: {str(error)}")
        return
    
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
        return

    # Log other errors
    logger.error(f'Command error in {ctx.command}: {error}')
    await ctx.send(f"❌ An error occurred: {str(error)}")

@bot.command(name="status")
async def status_command(ctx):
    """Show detailed information about the bot's status."""
    
    # Create embed with bot info
    embed = discord.Embed(
        title="🤖 Bot Status",
        description="Current status and statistics for the bot",
        color=discord.Color.green()
    )
    
    # Add bot info section
    embed.add_field(
        name="📊 General Info",
        value=f"**Name**: {bot.user.name}\n"
              f"**ID**: {bot.user.id}\n"
              f"**Status**: 🟢 Online\n"
              f"**Prefix**: {config.PREFIX}",
        inline=True
    )
    
    # Add server stats
    total_users = sum(guild.member_count for guild in bot.guilds)
    embed.add_field(
        name="🌐 Server Stats",
        value=f"**Servers**: {len(bot.guilds)}\n"
              f"**Users**: {total_users}\n",
        inline=True
    )
    
    # Add uptime information
    if bot.start_time:
        current_time = datetime.now()
        uptime = current_time - bot.start_time
        
        # Format uptime nicely
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        uptime_formatted = []
        if days > 0:
            uptime_formatted.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            uptime_formatted.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            uptime_formatted.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds > 0 or not uptime_formatted:
            uptime_formatted.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        
        uptime_str = ", ".join(uptime_formatted)
        started_at = bot.start_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        uptime_str = "Unknown"
        started_at = "Unknown"
    
    embed.add_field(
        name="⏱️ Uptime",
        value=f"**Running for**: {uptime_str}\n**Started at**: {started_at}",
        inline=False
    )
    
    # Add ping/latency information
    latency = round(bot.latency * 1000)
    embed.add_field(
        name="📡 Connection",
        value=f"**Latency**: {latency}ms",
        inline=True
    )
    
    # Add game statistics
    game_cog = bot.get_cog('ActorGame')
    active_games = 0
    if game_cog and hasattr(game_cog, 'game_sessions'):
        active_games = len(game_cog.game_sessions)
    
    # Add music statistics
    music_cog = bot.get_cog('MusicPlayer')
    active_music_sessions = 0
    if music_cog and hasattr(music_cog, 'music_queues'):
        active_music_sessions = len(music_cog.music_queues)
    
    embed.add_field(
        name="🎮 Activity",
        value=f"**Active Games**: {active_games}\n"
              f"**Music Sessions**: {active_music_sessions}",
        inline=True
    )
    
    # Set footer with timestamp
    embed.set_footer(text=f"Requested by {ctx.author} • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    await ctx.send(embed=embed)

@bot.command(name="help")
async def help_command(ctx, command_name=None):
    """Display help information about available commands."""
    if command_name is None:
        # Create main help embed
        embed = discord.Embed(
            title="Bot Help",
            description=f"Use `{config.PREFIX}help <command>` for more information on a specific command.",
            color=discord.Color.blue()
        )
        
        # Guess It game commands
        game_commands = "`startgame`, `join`, `question`, `guess`, `endgame`, `gamestatus`"
        embed.add_field(
            name="🎭 Guess It Game Commands",
            value=game_commands,
            inline=False
        )
        
        # Utility commands
        utility_commands = "`status`, `ping`, `help`"
        embed.add_field(
            name="🔧 Utility Commands",
            value=utility_commands,
            inline=False
        )
        
        # Bot information
        embed.add_field(
            name="ℹ️ Bot Information",
            value="This bot allows you to play the 'Guess It' game with friends.\nMusic functionality is currently disabled.",
            inline=False
        )
        
        embed.set_footer(text=f"Bot made with discord.py | Prefix: {config.PREFIX}")
        
    else:
        # Help for specific command
        command = bot.get_command(command_name)
        if command is None:
            await ctx.send(f"❌ Command `{command_name}` not found.")
            return
        
        embed = discord.Embed(
            title=f"Help: {command.name}",
            description=command.help or "No description available.",
            color=discord.Color.blue()
        )
        
        # Add usage info if available
        if command.usage:
            embed.add_field(name="Usage", value=f"`{config.PREFIX}{command.name} {command.usage}`", inline=False)
        
        embed.set_footer(text=f"Bot made with discord.py | Prefix: {config.PREFIX}")
    
    await ctx.send(embed=embed)

# Add Flask's context processor to provide current time to templates
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

def start_flask(host='0.0.0.0', port=5000):
    """Start the Flask web server in a separate thread."""
    flask_thread = Thread(target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    logger.info(f"Web server started on {host}:{port}")
    return flask_thread

if __name__ == "__main__":
    # Do not start Flask web server here - we're using the Start application workflow for that
    
    # Get the token from environment variables
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("No Discord token found! Set the DISCORD_TOKEN environment variable.")
        exit(1)
    
    # Add error handling and automatic restart
    while True:
        try:
            # Run the bot
            logger.info("Starting Discord bot - Guess It mode")
            bot.run(token)
        except discord.errors.HTTPException as e:
            if e.status == 429:  # Rate limited
                logger.warning(f"Rate limited. Retrying in 30 seconds... {str(e)}")
                time.sleep(30)
                continue
            else:
                logger.error(f"HTTP Exception: {str(e)}")
                time.sleep(5)
                continue
        except discord.errors.ConnectionClosed:
            # Connection closed, try to reconnect
            logger.warning("Connection closed. Reconnecting...")
            time.sleep(5)
            continue
        except Exception as e:
            # General error, log and try again
            logger.error(f"Unexpected error: {str(e)}")
            time.sleep(10)
            continue
