import os
import logging
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('web_server')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24))

# Global variable to store bot status - will be updated by main.py
bot_status = {
    "connected": False,
    "name": "Harmonia",
    "id": None,
    "guilds": [],
    "guild_count": 0,
    "user_count": 0,
    "active_games": 0,
    "active_music_sessions": 0
}

@app.route('/')
def index():
    """Homepage showing bot status and stats."""
    # Add current datetime for the template
    now = datetime.now()
    
    return render_template('index.html', 
                          bot_status=bot_status,
                          now=now)

@app.route('/guilds')
def guilds():
    """Page showing all connected guilds."""
    if not bot_status["connected"]:
        flash("Bot is not connected.", "danger")
        return redirect(url_for('index'))
    
    # Add current datetime for the template
    now = datetime.now()
    
    return render_template('guilds.html', 
                         bot_status=bot_status,
                         now=now)

@app.route('/actors')
def actors():
    """Page showing all actors in the database."""
    # Add current datetime for the template
    now = datetime.now()
    
    try:
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
                             bot_status=bot_status,
                             hollywood_actors=hollywood_actors,
                             bollywood_actors=bollywood_actors,
                             now=now)
    except Exception as e:
        logger.error(f"Error loading actors: {e}")
        flash(f"Error loading actors: {str(e)}", "danger")
        return render_template('actors.html',
                             bot_status=bot_status,
                             hollywood_actors=[],
                             bollywood_actors=[],
                             now=now)

@app.route('/actor/add', methods=['POST'])
def add_actor():
    """Add a new actor to the database."""
    try:
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
    except Exception as e:
        logger.error(f"Error adding actor: {e}")
        flash(f"Error adding actor: {str(e)}", "danger")
    
    return redirect(url_for('actors'))

@app.route('/actor/remove', methods=['POST'])
def remove_actor():
    """Remove an actor from the database."""
    try:
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
    except Exception as e:
        logger.error(f"Error removing actor: {e}")
        flash(f"Error removing actor: {str(e)}", "danger")
    
    return redirect(url_for('actors'))

@app.route('/api/bot-status')
def api_bot_status():
    """API endpoint to get the bot status."""
    return jsonify(bot_status)

# Function to update bot status - will be called from main.py
def update_bot_status(bot=None):
    """Update the bot status with the latest information."""
    global bot_status
    
    if not bot or not bot.is_ready():
        bot_status["connected"] = False
        return bot_status
    
    # Update bot information
    bot_status["connected"] = True
    bot_status["name"] = bot.user.name
    bot_status["id"] = bot.user.id
    
    # Get guild information
    guilds = []
    user_count = 0
    for guild in bot.guilds:
        guilds.append({
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "icon_url": str(guild.icon.url) if guild.icon else None
        })
        user_count += guild.member_count
    
    bot_status["guilds"] = guilds
    bot_status["guild_count"] = len(guilds)
    bot_status["user_count"] = user_count
    
    # Get game statistics
    game_cog = bot.get_cog('ActorGame')
    active_games = 0
    if game_cog and hasattr(game_cog, 'active_games'):
        active_games = len(game_cog.active_games)
    bot_status["active_games"] = active_games
    
    # Get music statistics
    music_cog = bot.get_cog('MusicPlayer')
    active_music_sessions = 0
    if music_cog and hasattr(music_cog, 'music_queues'):
        active_music_sessions = len(music_cog.music_queues)
    bot_status["active_music_sessions"] = active_music_sessions
    
    return bot_status

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)