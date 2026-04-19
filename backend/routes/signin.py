from flask import Blueprint, request, jsonify, make_response
from werkzeug.security import check_password_hash
from utils.auth_utils import create_tokens, blacklist_token, generate_fingerprint, JWT_SECRET, JWT_ALGORITHM, require_auth
import jwt
import hashlib
from datetime import datetime, timedelta
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.crypto_utils import decrypt_data

from utils.security_utils import limiter

signin_bp = Blueprint('signin', __name__)

@signin_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """
    User login: verify credentials, check role-based approval, and issue JWT token.
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    role = data.get('userType')
    
    if not email or not password or not role:
        return jsonify({"error": "Email, password, and role are required"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM users 
                    WHERE email = %s AND role = %s
                """, (email, role))
                
                user = cur.fetchone()
                
                if not user or not check_password_hash(user['password_hash'], password):
                    return jsonify({"error": "Invalid credentials or role selection"}), 401
                    
                if user['account_status'] == 'pending':
                    return jsonify({"error": "Access Denied: Your account is awaiting Administrative Approval."}), 403
                    
                if user['account_status'] == 'rejected':
                    return jsonify({"error": "Access Denied: Your application was rejected by Administration."}), 403
                    
                # 4. Check for active club administrator if logging in as Organizer
                if role == 'organizer':
                    cur.execute("SELECT id FROM users WHERE role = 'admin' AND organization_name = %s", (user['organization_name'],))
                    if not cur.fetchone():
                         return jsonify({"error": f"Access Denied: The Administrator for '{user['organization_name']}' is not active. Please contact your club head."}), 403

                # 5. Issue JWT and Refresh tokens (20 minute max session)
                access_token, refresh_token = create_tokens({
                    "id": user['id'],
                    "email": user['email'],
                    "role": user['role'],
                    "orgName": user['organization_name'],
                    "club_id": user['club_id']
                })
                
                # --- SESSION TRACKING LOG ---
                cur.execute("""
                    INSERT INTO user_session_history (user_id, action, ip_address, user_agent)
                    VALUES (%s, 'login', %s, %s)
                """, (user['id'], request.remote_addr, request.headers.get('User-Agent')))
                conn.commit()
                # ----------------------------

                resp = make_response(jsonify({
                    "message": "Login successful (Session limited to 20 minutes)",
                    "user": {
                        "id": user['id'],
                        "fullName": user['full_name'],
                        "email": user['email'],
                        "role": user['role'],
                        "orgName": user['organization_name']
                    }
                }))
                
                # Set Secure HTTP-only Cookies with 20 minute limit (1200 seconds)
                resp.set_cookie('access_token', access_token, httponly=True, samesite='Strict', max_age=1200)
                resp.set_cookie('refresh_token', refresh_token, httponly=True, samesite='Strict', max_age=1200)
                
                return resp, 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@signin_bp.route('/refresh', methods=['POST'])
def refresh():
    """Rotate refresh tokens and issue new access token."""
    refresh_token = request.cookies.get('refresh_token')
    if not refresh_token:
        return jsonify({"error": "No refresh session"}), 401
        
    try:
        # 1. Basic JWT validation
        data = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if data.get('type') != 'refresh':
            return jsonify({"error": "Invalid token type"}), 401
            
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 2. Check if this token exists in DB (to prevent reuse/stolen token)
                cur.execute("SELECT * FROM refresh_tokens WHERE token_hash = %s", (token_hash,))
                stored = cur.fetchone()
                
                if not stored:
                    # REUSE DETECTION: If we get a valid signed refresh token that ISN'T in our DB, 
                    # it might be a stolen token that was already rotated. 
                    # SECURITY POLICY: Revoke ALL sessions for this user.
                    cur.execute("DELETE FROM refresh_tokens WHERE user_id = %s", (data['sub'],))
                    return jsonify({"error": "Security breach detected. Sessions terminated."}), 403
                
                # 3. Rotate tokens: Fetch user details to create new identity tokens
                cur.execute("SELECT id, email, role, organization_name as \"orgName\", club_id FROM users WHERE id = %s", (data['sub'],))
                user = cur.fetchone()
                
                # 4. Burn the old refresh token (Consumption)
                cur.execute("DELETE FROM refresh_tokens WHERE id = %s", (stored['id'],))
                
                # --- SESSION TRACKING LOG ---
                cur.execute("""
                    INSERT INTO user_session_history (user_id, action, ip_address, user_agent)
                    VALUES (%s, 'refresh', %s, %s)
                """, (user['id'], request.remote_addr, request.headers.get('User-Agent')))
                # ----------------------------
                conn.commit()
                
                # 5. Issue new pairs while PRESERVING original expiry for hard 20m limit
                # data['exp'] is the current refresh token's expiration
                orig_expiry = datetime.fromtimestamp(data['exp'])
                new_access, new_refresh = create_tokens(user, max_expiry=orig_expiry)
                
                resp = make_response(jsonify({"message": "Session renewed"}))
                resp.set_cookie('access_token', new_access, httponly=True, samesite='Strict', max_age=1200)
                resp.set_cookie('refresh_token', new_refresh, httponly=True, samesite='Strict', max_age=1200)
                return resp, 200
                
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Refresh session expired"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@signin_bp.route('/logout', methods=['POST'])
def logout():
    """Logout: Clear cookies and blacklist active access token."""
    access_token = request.cookies.get('access_token')
    refresh_token = request.cookies.get('refresh_token')
    
    if access_token:
        try:
            data = jwt.decode(access_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            blacklist_token(data['jti'], datetime.fromtimestamp(data['exp']))
        except: pass
        
        try:
            h = hashlib.sha256(refresh_token.encode()).hexdigest()
            with DatabaseConnection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Fetch user_id for tracking before deleting
                    cur.execute("SELECT user_id FROM refresh_tokens WHERE token_hash = %s", (h,))
                    session = cur.fetchone()
                    if session:
                        cur.execute("""
                            INSERT INTO user_session_history (user_id, action, ip_address, user_agent)
                            VALUES (%s, 'logout', %s, %s)
                        """, (session['user_id'], request.remote_addr, request.headers.get('User-Agent')))
                    
                    cur.execute("DELETE FROM refresh_tokens WHERE token_hash = %s", (h,))
                    conn.commit()
        except: pass

    resp = make_response(jsonify({"message": "Signed out safely"}))
    resp.set_cookie('access_token', '', expires=0)
    resp.set_cookie('refresh_token', '', expires=0)
    return resp, 200

@signin_bp.route('/sessions', methods=['GET'])
@require_auth()
def get_session_history(current_user):
    """Fetch session tracking history for the current user."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT action, ip_address, user_agent, timestamp 
                    FROM user_session_history 
                    WHERE user_id = %s 
                    ORDER BY timestamp DESC 
                    LIMIT 20
                """, (current_user['sub'],))
                return jsonify(cur.fetchall()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
