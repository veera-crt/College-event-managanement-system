from flask import Blueprint, request, jsonify
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.auth_utils import require_auth
from utils.crypto_utils import encrypt_data, decrypt_data

admin_profile_bp = Blueprint('admin_profile', __name__)

@admin_profile_bp.route('/get', methods=['GET'])
@require_auth(['admin'])
def get_admin_profile(current_user):
    """Fetch current admin's profile details."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT u.id, u.full_name, u.email, u.role, u.organization_name, u.club_id, 
                           c.name as club_name, c.razorpay_key_id, c.razorpay_key_secret
                    FROM users u 
                    LEFT JOIN clubs c ON u.club_id = c.id
                    WHERE u.id = %s AND u.role = 'admin'
                """, (current_user['sub'],))
                user_data = cur.fetchone()
                
                if not user_data:
                    return jsonify({"error": "Admin not found"}), 404
                
                # Decrypt Razorpay Keys
                if user_data.get('razorpay_key_id'):
                    user_data['razorpay_key_id'] = decrypt_data(user_data['razorpay_key_id'])
                if user_data.get('razorpay_key_secret'):
                    user_data['razorpay_key_secret'] = decrypt_data(user_data['razorpay_key_secret'])
                
                # Admin profile fetch (orgName is plaintext now)
                
                return jsonify({"user": user_data, "accessLevel": "SUPER_USER"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_profile_bp.route('/update', methods=['POST'])
@require_auth(['admin'])
def update_admin_profile(current_user):
    """Update admin profile fields."""
    data = request.json
    full_name = data.get('full_name')
    org_name = data.get('organization_name')
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users 
                    SET full_name = %s, organization_name = %s 
                    WHERE id = %s AND role = 'admin'
                """, (full_name, org_name, current_user['sub']))
                conn.commit()
                return jsonify({"message": "Admin profile updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_profile_bp.route('/update-club-keys', methods=['POST'])
@require_auth(['admin'])
def update_club_keys(current_user):
    """Allows Admin to set Razorpay keys and Google Sheet sync links for a specific club."""
    data = request.json
    club_id = data.get('club_id')
    razorpay_key_id = data.get('razorpay_key_id')
    razorpay_key_secret = data.get('razorpay_key_secret')
    master_gsheet_link = data.get('master_gsheet_link')

    if not club_id:
        return jsonify({"error": "Club ID required"}), 400

    enc_key_id = encrypt_data(razorpay_key_id) if razorpay_key_id else None
    enc_key_secret = encrypt_data(razorpay_key_secret) if razorpay_key_secret else None

    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE clubs 
                    SET razorpay_key_id = %s, razorpay_key_secret = %s, master_gsheet_link = %s
                    WHERE id = %s
                """, (enc_key_id, enc_key_secret, master_gsheet_link, club_id))
                
                if cur.rowcount == 0:
                     return jsonify({"error": "Club not found"}), 404
                     
                conn.commit()
                return jsonify({"message": "Club integrations updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_profile_bp.route('/get-clubs', methods=['GET'])
@require_auth(['admin'])
def get_clubs(current_user):
    """Fetch all clubs and their current integration keys."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, name, category, razorpay_key_id, razorpay_key_secret, master_gsheet_link FROM clubs ORDER BY name ASC")
                clubs = cur.fetchall()
                for c in clubs:
                    if c.get('razorpay_key_id'): c['razorpay_key_id'] = decrypt_data(c['razorpay_key_id'])
                    if c.get('razorpay_key_secret'): c['razorpay_key_secret'] = decrypt_data(c['razorpay_key_secret'])
                return jsonify(clubs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
