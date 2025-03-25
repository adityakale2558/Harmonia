import json
import os
import logging
import random
import aiofiles
from typing import Dict, List, Optional

logger = logging.getLogger("discord_bot.actor_database")

class ActorDatabase:
    """
    Utility class to manage the actor database for the game.
    Loads and provides actor data by category.
    """
    
    def __init__(self):
        self.actors = {"hollywood": [], "bollywood": []}
        self.data_file = "data/actors.json"
    
    async def load_actors(self) -> None:
        """
        Load actors from the JSON data file.
        If the file doesn't exist, create it with default data.
        """
        try:
            # Check if data directory exists, create if not
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            
            # Check if the data file exists
            if not os.path.exists(self.data_file):
                logger.info(f"Actor database file not found. Creating default database at {self.data_file}")
                await self._create_default_database()
            
            # Load the actor data
            async with aiofiles.open(self.data_file, 'r') as f:
                content = await f.read()
                data = json.loads(content)
                
                # Validate the data structure
                if not isinstance(data, dict):
                    logger.error("Invalid actor database format. Expected a dictionary.")
                    await self._create_default_database()
                    return
                
                # Load actors by category
                self.actors["hollywood"] = data.get("hollywood", [])
                self.actors["bollywood"] = data.get("bollywood", [])
                
                logger.info(f"Loaded {len(self.actors['hollywood'])} Hollywood actors and "
                          f"{len(self.actors['bollywood'])} Bollywood actors")
        
        except Exception as e:
            logger.error(f"Error loading actor database: {e}")
            await self._create_default_database()
    
    async def _create_default_database(self) -> None:
        """Create a default actor database with some sample actors."""
        default_data = {
            "hollywood": [
                "Tom Hanks", "Leonardo DiCaprio", "Brad Pitt", "Jennifer Lawrence", 
                "Meryl Streep", "Denzel Washington", "Robert Downey Jr.", "Scarlett Johansson",
                "Johnny Depp", "Will Smith", "Emma Stone", "Chris Hemsworth", 
                "Ryan Reynolds", "Dwayne Johnson", "Anne Hathaway", "Chris Evans",
                "Morgan Freeman", "Sandra Bullock", "Tom Cruise", "Julia Roberts",
                "Samuel L. Jackson", "Angelina Jolie", "Hugh Jackman", "Jennifer Aniston",
                "Chris Pratt", "Matt Damon", "Natalie Portman", "Benedict Cumberbatch",
                "Keanu Reeves", "Charlize Theron"
            ],
            "bollywood": [
                "Shah Rukh Khan", "Amitabh Bachchan", "Deepika Padukone", "Aamir Khan",
                "Priyanka Chopra", "Salman Khan", "Kareena Kapoor", "Hrithik Roshan",
                "Aishwarya Rai", "Ranbir Kapoor", "Katrina Kaif", "Akshay Kumar",
                "Anushka Sharma", "Ranveer Singh", "Alia Bhatt", "Shahid Kapoor",
                "Kajol", "Ajay Devgn", "Madhuri Dixit", "Varun Dhawan",
                "Vidya Balan", "Sanjay Dutt", "Sonam Kapoor", "John Abraham",
                "Shraddha Kapoor", "Irrfan Khan", "Kangana Ranaut", "Anil Kapoor",
                "Tabu", "Nawazuddin Siddiqui"
            ]
        }
        
        try:
            # Create the data directory if it doesn't exist
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            
            # Write the default data to the file
            async with aiofiles.open(self.data_file, 'w') as f:
                await f.write(json.dumps(default_data, indent=2))
            
            # Load the actors into memory
            self.actors["hollywood"] = default_data["hollywood"]
            self.actors["bollywood"] = default_data["bollywood"]
            
            logger.info("Created default actor database")
        
        except Exception as e:
            logger.error(f"Error creating default actor database: {e}")
    
    async def get_actors_by_category(self, category: str) -> List[str]:
        """
        Get the list of actors for a specific category.
        
        Args:
            category: The category of actors ("hollywood" or "bollywood")
            
        Returns:
            A list of actor names
        """
        category = category.lower()
        
        if category not in self.actors:
            logger.warning(f"Invalid category: {category}. Using Hollywood as default.")
            category = "hollywood"
        
        return self.actors[category]
    
    async def add_actor(self, category: str, actor_name: str) -> bool:
        """
        Add a new actor to the database.
        
        Args:
            category: The category to add the actor to
            actor_name: The name of the actor to add
            
        Returns:
            True if the actor was added, False otherwise
        """
        category = category.lower()
        
        if category not in self.actors:
            logger.warning(f"Invalid category: {category}")
            return False
        
        # Check if actor already exists
        if actor_name in self.actors[category]:
            logger.warning(f"Actor {actor_name} already exists in {category}")
            return False
        
        # Add the actor
        self.actors[category].append(actor_name)
        
        # Save the updated database
        await self._save_database()
        
        return True
    
    async def remove_actor(self, category: str, actor_name: str) -> bool:
        """
        Remove an actor from the database.
        
        Args:
            category: The category to remove the actor from
            actor_name: The name of the actor to remove
            
        Returns:
            True if the actor was removed, False otherwise
        """
        category = category.lower()
        
        if category not in self.actors:
            logger.warning(f"Invalid category: {category}")
            return False
        
        # Check if actor exists
        if actor_name not in self.actors[category]:
            logger.warning(f"Actor {actor_name} not found in {category}")
            return False
        
        # Remove the actor
        self.actors[category].remove(actor_name)
        
        # Save the updated database
        await self._save_database()
        
        return True
    
    async def _save_database(self) -> None:
        """Save the current actor database to the JSON file."""
        try:
            data = {
                "hollywood": self.actors["hollywood"],
                "bollywood": self.actors["bollywood"]
            }
            
            async with aiofiles.open(self.data_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
            logger.info("Actor database saved")
        
        except Exception as e:
            logger.error(f"Error saving actor database: {e}")
