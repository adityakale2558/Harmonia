import os
import logging
import discord
import asyncio
from discord.ext import commands
import config
from threading import Thread
from app import app, update_bot_status
from datetime import datetime

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

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} servers')
    
    # Load cogs
    await load_cogs()
    
    # Set custom status
    activity = discord.Activity(type=discord.ActivityType.playing, 
                               name=f"{config.PREFIX}help | Actor Game")
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
        
        # Actor Game commands
        game_commands = "`startgame`, `join`, `question`, `guess`, `endgame`, `gamestatus`"
        embed.add_field(
            name="🎭 Actor Game Commands",
            value=game_commands,
            inline=False
        )
        
        # Bot information
        embed.add_field(
            name="ℹ️ Bot Information",
            value="This bot allows you to play the 'Guess the Actor' game with friends.\nMusic functionality is currently disabled.",
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
    
    # Run the bot
    logger.info("Starting Discord bot - Actor Game mode")
    bot.run(token)
