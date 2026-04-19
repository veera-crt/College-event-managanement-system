from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Initialize limiter globally for use in Blueprints
# Storage is set to memory for development/simplicity as no Redis is requested.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["5000 per day", "1000 per hour"],
    storage_uri="memory://",
)
