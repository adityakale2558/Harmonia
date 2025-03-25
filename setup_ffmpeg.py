#!/usr/bin/env python3
"""
Setup script to ensure FFmpeg is properly configured for Discord audio playback.
This script creates symbolic links and sets up environment variables.
"""
import os
import subprocess
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger('setup_ffmpeg')

def setup_ffmpeg():
    """Setup FFmpeg for Discord bot."""
    # FFmpeg path in replit/nix environment
    ffmpeg_path = '/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin/ffmpeg'
    
    # Check if ffmpeg exists at the expected path
    if not os.path.exists(ffmpeg_path):
        logger.error(f"FFmpeg not found at {ffmpeg_path}")
        return False
    
    # Update PATH environment variable
    os.environ['PATH'] = f"/nix/store/3zc5jbvqzrn8zmva4fx5p0nh4yy03wk4-ffmpeg-6.1.1-bin/bin:{os.environ.get('PATH', '')}"
    
    # Create a symlink in a standard location
    try:
        # Create bin directory in home if not exists
        home_bin = os.path.expanduser('~/.local/bin')
        os.makedirs(home_bin, exist_ok=True)
        
        # Create symlink
        symlink_path = os.path.join(home_bin, 'ffmpeg')
        if not os.path.exists(symlink_path):
            os.symlink(ffmpeg_path, symlink_path)
            logger.info(f"Created symlink: {symlink_path} -> {ffmpeg_path}")
        
        # Add to PATH
        os.environ['PATH'] = f"{home_bin}:{os.environ.get('PATH', '')}"
        
        # Test ffmpeg
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("FFmpeg setup completed successfully")
            logger.info(f"FFmpeg version: {result.stdout.splitlines()[0]}")
            return True
        else:
            logger.error(f"FFmpeg test failed: {result.stderr}")
            return False
    
    except Exception as e:
        logger.error(f"Error setting up FFmpeg: {e}")
        return False

if __name__ == "__main__":
    if setup_ffmpeg():
        print("FFmpeg setup successful. Discord audio playback should work now.")
        sys.exit(0)
    else:
        print("FFmpeg setup failed. Audio playback may not work correctly.")
        sys.exit(1)