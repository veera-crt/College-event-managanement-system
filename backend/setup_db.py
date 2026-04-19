import os
import sys
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 1. Load environment variables from the project root
# This ensures DATABASE_URL is available
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path, override=True)

try:
    # 2. Import the existing database connection utility
    # We do this after loading env to ensure db.py sees the correct DATABASE_URL
    from db import DatabaseConnection, DATABASE_URL
except ImportError:
    logger.error("❌ Could not import 'db.py'. Ensure this script is run from the 'backend' directory.")
    sys.exit(1)

def setup_database():
    """Reads the SQL schema file and executes it against the configured database."""
    
    schema_file = 'database_full_schema.sql'
    
    if not os.path.exists(schema_file):
        logger.error(f"❌ Schema file '{schema_file}' not found in the current directory.")
        return

    logger.info(f"🚀 Starting Database Setup...")
    logger.info(f"🔗 Target Database: {DATABASE_URL[:40]}..." if DATABASE_URL else "🔗 Target Database: Local PostgreSQL (cems)")

    try:
        # Read the full SQL schema
        with open(schema_file, 'r') as f:
            full_sql = f.read()

        # Connect and execute
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                logger.info("⏳ Initializing tables, triggers, and sequences...")
                cur.execute(full_sql)
                # Success is handled by the DatabaseConnection context manager (commits on exit)
        
        logger.info("✅ Database Setup Completed Successfully!")
        logger.info("✨ Your Neon DB is now fully configured with all required tables.")

    except Exception as e:
        logger.error(f"💥 Failed to configure database: {e}")
        logger.info("💡 Pro-tip: Check your DATABASE_URL in .env and ensure your IP is allowed in Neon Console.")

if __name__ == "__main__":
    setup_database()
