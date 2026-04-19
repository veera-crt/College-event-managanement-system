import os
import hashlib
import uuid
import jwt
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, make_response
from dotenv import load_dotenv
from db import DatabaseConnection

# Ensure secrets are always loaded from the project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(env_path, override=True)

JWT_SECRET = os.environ.get("JWT_SECRET", "super-secret-campus-hub-key-fallback")
JWT_ALGORITHM = "HS256"

# Authentication Utilities for CampusHub Auth Flow logic-15-fix logic

def generate_fingerprint():
    """Generates a cryptographic fingerprint based on the requester's IP and User Agent."""
    ua = request.headers.get('User-Agent', 'unknown')
    ip = request.remote_addr or 'unknown'
    return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()

def create_tokens(user, max_expiry=None):
    """
    Issue a new Access Token (20m) and Refresh Token (20m).
    Implements Token Rotation and Fingerprinting.
    If max_expiry is provided, the refresh token will not exceed that time (Enforces Hard Session Limit).
    """
    fp = generate_fingerprint()
    jti = str(uuid.uuid4())
    
    # 1. Access Token (Short-lived: Exactly 20 minutes)
    access_payload = {
        'sub': str(user['id']),
        'email': user['email'],
        'role': user['role'],
        'club_id': user.get('club_id'),
        'orgName': user.get('orgName'),
        'fp': fp, # Fingerprint binding
        'jti': jti,
        'type': 'access',
        'exp': datetime.utcnow() + timedelta(minutes=20),
        'iat': datetime.utcnow()
    }
    access_token = jwt.encode(access_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    # 2. Refresh Token (Max Lifetime: 20 minutes for single login restriction)
    refresh_jti = str(uuid.uuid4())
    
    # Enforce hard limit from initial login if provided
    refresh_expiry = max_expiry if max_expiry else (datetime.utcnow() + timedelta(minutes=20))
    
    refresh_payload = {
        'sub': str(user['id']),
        'jti': refresh_jti,
        'type': 'refresh',
        'exp': refresh_expiry,
        'iat': datetime.utcnow()
    }
    refresh_token = jwt.encode(refresh_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    # 3. Securely store Refresh Token in Database for Rotation tracking
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                # Hash the refresh token before storing (Extra layer)
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                cur.execute("""
                    INSERT INTO refresh_tokens (user_id, token_hash, ip_address, user_agent, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user['id'], token_hash, request.remote_addr, request.headers.get('User-Agent'), 
                      refresh_expiry))
    except Exception as e:
        logging.error(f"Failed to store refresh token: {str(e)}")
        
    return access_token, refresh_token

def blacklist_token(jti, expires_at):
    """Blacklists a token (usually on logout)."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO revoked_tokens (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING", (jti, expires_at))
    except Exception as e:
        logging.error(f"Blacklist failure: {e}")

def is_blacklisted(jti):
    """Check if token is blacklisted."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM revoked_tokens WHERE jti = %s", (jti,))
                return cur.fetchone() is not None
    except:
        return False


def require_auth(roles=None):
    """
    Decorator to ensure standard PyJWT validation and specific Role-Based access filtering.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Log headers for debugging
            # print(f"🔍 Headers: {dict(request.headers)}")
            # 1. Extraction (Cookie then Header)
            token = request.cookies.get('access_token')
            if not token and 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                parts = auth_header.split()
                if len(parts) == 2 and parts[0] == 'Bearer':
                    token = parts[1]
            
            if not token:
                return jsonify({"error": "Auth Session Required"}), 401
            
            try:
                data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                
                # 2. Blacklist Validation
                if is_blacklisted(data.get('jti')):
                    return jsonify({"error": "Session revoked. Please login again."}), 401
                
                # 3. Fingerprint Binding Verification (Anti-Token Theft)
                current_fp = generate_fingerprint()
                if data.get('fp') != current_fp:
                    logging.warning(f"🚨 FINGERPRINT MISMATCH detected for user {data.get('sub')}")
                    return jsonify({"error": "Security violation detected. Session terminated."}), 403
                
                current_user = data
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Session expired", "code": "TOKEN_EXPIRED"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid secure session"}), 401
                
            if roles and current_user['role'] not in roles:
                return jsonify({"error": "Insufficient privileges"}), 403
                
            return f(current_user, *args, **kwargs)
        return decorated
    return decorator
