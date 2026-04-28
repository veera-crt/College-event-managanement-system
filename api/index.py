import sys
import os

# Add the backend directory to the sys.path
# This allows 'import app' and ensures app.py can find the 'routes' package
current_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(current_dir, '..', 'backend'))
sys.path.append(backend_dir)

# Now import the Flask app
from backend.app import app

# Vercel needs the 'app' object
# The Flask app 'app' will be used to handle requests
