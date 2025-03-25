import os
import logging
from flask import Flask, render_template, redirect, url_for, flash, request
import discord
from threading import Thread

# Setup logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('web_server')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24))

# Global variable to hold the bot instance (will be set from main.py)
discord_bot = None

@app.route('/')
def index():
    """Homepage showing bot status and stats."""
    if not discord_bot or not discord_bot.is_ready():
        return render_template('index.html', 
                             bot_name="Discord Bot", 
                             status="Offline", 
                             guilds=[],
                             user_count=0)
    
    # Get bot stats
    guilds = discord_bot.guilds
    user_count = sum(guild.member_count for guild in guilds)
    
    # Get game statistics
    game_cog = discord_bot.get_cog('ActorGame')
    active_games = 0
    if game_cog:
        active_games = len(game_cog.active_games)
    
    # Get music statistics
    music_cog = discord_bot.get_cog('MusicPlayer')
    active_music_sessions = 0
    if music_cog:
        active_music_sessions = len(music_cog.music_queues)
    
    return render_template('index.html', 
                         bot_name=discord_bot.user.name,
                         bot_id=discord_bot.user.id,
                         status="Online",
                         guilds=guilds,
                         user_count=user_count,
                         active_games=active_games,
                         active_music_sessions=active_music_sessions)

@app.route('/guilds')
def guilds():
    """Page showing all connected guilds."""
    if not discord_bot or not discord_bot.is_ready():
        flash("Bot is not connected.", "danger")
        return redirect(url_for('index'))
    
    return render_template('guilds.html', 
                         bot_name=discord_bot.user.name,
                         guilds=discord_bot.guilds)

@app.route('/guild/<int:guild_id>')
def guild_details(guild_id):
    """Page showing details for a specific guild."""
    if not discord_bot or not discord_bot.is_ready():
        flash("Bot is not connected.", "danger")
        return redirect(url_for('index'))
    
    guild = discord_bot.get_guild(guild_id)
    if not guild:
        flash(f"Guild with ID {guild_id} not found.", "danger")
        return redirect(url_for('guilds'))
    
    # Get game data for this guild
    game_cog = discord_bot.get_cog('ActorGame')
    active_game = None
    if game_cog:
        for channel_id, game in game_cog.active_games.items():
            if game.channel.guild.id == guild_id:
                active_game = game
                break
    
    # Get music data for this guild
    music_cog = discord_bot.get_cog('MusicPlayer')
    music_queue = None
    if music_cog and guild_id in music_cog.music_queues:
        music_queue = music_cog.music_queues[guild_id]
    
    return render_template('guild_details.html',
                         bot_name=discord_bot.user.name,
                         guild=guild,
                         active_game=active_game,
                         music_queue=music_queue)

@app.route('/actors')
def actors():
    """Page showing all actors in the database."""
    from utils.actor_database import ActorDatabase
    import asyncio
    
    actor_db = ActorDatabase()
    # Create event loop to run the async load_actors method
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(actor_db.load_actors())
    
    # Get categories
    hollywood_actors = loop.run_until_complete(actor_db.get_actors_by_category("hollywood"))
    bollywood_actors = loop.run_until_complete(actor_db.get_actors_by_category("bollywood"))
    
    return render_template('actors.html',
                         bot_name=discord_bot.user.name if discord_bot else "Discord Bot",
                         hollywood_actors=hollywood_actors,
                         bollywood_actors=bollywood_actors)

@app.route('/actor/add', methods=['POST'])
def add_actor():
    """Add a new actor to the database."""
    from utils.actor_database import ActorDatabase
    import asyncio
    
    category = request.form.get('category')
    actor_name = request.form.get('actor_name')
    
    if not category or not actor_name:
        flash("Category and actor name are required.", "danger")
        return redirect(url_for('actors'))
    
    actor_db = ActorDatabase()
    # Create event loop to run the async add_actor method
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Load actors first
    loop.run_until_complete(actor_db.load_actors())
    
    # Add the actor
    success = loop.run_until_complete(actor_db.add_actor(category.lower(), actor_name))
    
    if success:
        flash(f"Actor '{actor_name}' added to {category} successfully.", "success")
    else:
        flash(f"Failed to add actor '{actor_name}'. Actor might already exist.", "danger")
    
    return redirect(url_for('actors'))

@app.route('/actor/remove', methods=['POST'])
def remove_actor():
    """Remove an actor from the database."""
    from utils.actor_database import ActorDatabase
    import asyncio
    
    category = request.form.get('category')
    actor_name = request.form.get('actor_name')
    
    if not category or not actor_name:
        flash("Category and actor name are required.", "danger")
        return redirect(url_for('actors'))
    
    actor_db = ActorDatabase()
    # Create event loop to run the async remove_actor method
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Load actors first
    loop.run_until_complete(actor_db.load_actors())
    
    # Remove the actor
    success = loop.run_until_complete(actor_db.remove_actor(category.lower(), actor_name))
    
    if success:
        flash(f"Actor '{actor_name}' removed from {category} successfully.", "success")
    else:
        flash(f"Failed to remove actor '{actor_name}'. Actor might not exist.", "danger")
    
    return redirect(url_for('actors'))

def start_webserver(bot_instance, port=5000):
    """Start the Flask webserver in a separate thread."""
    global discord_bot
    discord_bot = bot_instance
    
    # Set up templates and static folders if they don't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Create thread for the webserver
    def run_webserver():
        app.run(host='0.0.0.0', port=port, debug=False)
    
    webserver_thread = Thread(target=run_webserver)
    webserver_thread.daemon = True
    webserver_thread.start()
    
    logger.info(f"Web server started on port {port}")
    return webserver_thread