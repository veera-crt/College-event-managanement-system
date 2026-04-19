from flask import Blueprint, request, jsonify
from utils.auth_utils import require_auth
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.email_utils import send_friend_request_email

friends_bp = Blueprint('friends', __name__)

@friends_bp.route('/search', methods=['GET'])
@require_auth(roles=['student'])
def search_users(current_user):
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([]), 200
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Search by full_name or reg_no, excluding self
                # AND only students
                cur.execute("""
                    SELECT id, full_name, reg_no 
                    FROM users 
                    WHERE (LOWER(full_name) LIKE LOWER(%s) OR LOWER(reg_no) LIKE LOWER(%s))
                    AND id != %s AND role = 'student'
                    LIMIT 20
                """, (f"%{query}%", f"%{query}%", current_user['sub']))
                users = cur.fetchall()
                return jsonify(users), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@friends_bp.route('/request', methods=['POST'])
@require_auth(roles=['student'])
def send_request(current_user):
    data = request.json
    friend_id = data.get('friend_id')
    
    if not friend_id:
        return jsonify({"error": "Friend ID required"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                if str(current_user['sub']) == str(friend_id):
                    return jsonify({"error": "You cannot add yourself as a friend"}), 400

                # Check if already friends or request pending
                cur.execute("""
                    SELECT id, status FROM friends 
                    WHERE (user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s)
                """, (current_user['sub'], friend_id, friend_id, current_user['sub']))
                exists = cur.fetchone()
                
                if exists:
                    status = exists[1]
                    if status == 'accepted':
                        return jsonify({"error": "You are already friends with this user"}), 400
                    if status == 'pending':
                        return jsonify({"error": "A friend request is already pending between you two"}), 400
                    
                    # If rejected, we allow a new request (reset the record)
                    cur.execute("DELETE FROM friends WHERE id = %s", (exists[0],))

                # Create new request
                cur.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (%s, %s, 'pending')", 
                            (current_user['sub'], friend_id))
                
                # Notifications...
                cur.execute("SELECT email, full_name FROM users WHERE id = %s", (friend_id,))
                friend = cur.fetchone()
                cur.execute("SELECT full_name FROM users WHERE id = %s", (current_user['sub'],))
                me = cur.fetchone()
                
                if friend and me:
                    send_friend_request_email(friend[0], me[0])
                
                conn.commit()
                return jsonify({"message": "Friend request sent successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@friends_bp.route('/requests', methods=['GET'])
@require_auth(roles=['student'])
def get_requests(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT f.id as request_id, u.id as user_id, u.full_name, u.reg_no, f.created_at
                    FROM friends f
                    JOIN users u ON f.user_id = u.id
                    WHERE f.friend_id = %s AND f.status = 'pending'
                """, (current_user['sub'],))
                requests = cur.fetchall()
                for r in requests:
                    if r['created_at']: r['created_at'] = r['created_at'].isoformat()
                return jsonify(requests), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@friends_bp.route('/requests/sent', methods=['GET'])
@require_auth(roles=['student'])
def get_sent_requests(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT f.id as request_id, u.id as friend_id, u.full_name, u.reg_no, f.created_at
                    FROM friends f
                    JOIN users u ON f.friend_id = u.id
                    WHERE f.user_id = %s AND f.status = 'pending'
                """, (current_user['sub'],))
                requests = cur.fetchall()
                for r in requests:
                    if r['created_at']: r['created_at'] = r['created_at'].isoformat()
                return jsonify(requests), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@friends_bp.route('/respond', methods=['POST'])
@require_auth(roles=['student'])
def respond_request(current_user):
    data = request.json
    request_id = data.get('request_id')
    action = data.get('action') # 'accepted' or 'rejected'
    
    if action not in ['accepted', 'rejected']:
        return jsonify({"error": "Invalid action"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE friends SET status = %s WHERE id = %s AND friend_id = %s", 
                            (action, request_id, current_user['sub']))
                conn.commit()
                return jsonify({"message": f"Request {action} successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@friends_bp.route('/list', methods=['GET'])
@require_auth(roles=['student'])
def get_friends(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Friends are bidirectional once accepted
                cur.execute("""
                    SELECT u.id, u.full_name, u.reg_no, u.gender
                    FROM friends f
                    JOIN users u ON (f.user_id = u.id OR f.friend_id = u.id)
                    WHERE (f.user_id = %s OR f.friend_id = %s)
                    AND u.id != %s AND f.status = 'accepted'
                """, (current_user['sub'], current_user['sub'], current_user['sub']))
                friends = cur.fetchall()
                return jsonify(friends), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
