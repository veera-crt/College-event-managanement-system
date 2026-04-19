from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.email_utils import send_otp_email
from utils.crypto_utils import encrypt_data, decrypt_data
import random
import json
from datetime import datetime, timedelta

forgot_password_bp = Blueprint('forgot_password', __name__)

@forgot_password_bp.route('/send-otp', methods=['POST'])
def send_reset_otp():
    """Step 1: Verify existence and send OTP for password recovery."""
    data = request.json
    email = data.get('email')
    role = data.get('userType')
    
    if not email or not role:
        return jsonify({"error": "Email and user type are required"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Verify user exists with this role
                cur.execute("SELECT id, full_name FROM users WHERE email = %s AND role = %s", (email, role))
                user = cur.fetchone()
                
                if not user:
                    return jsonify({"error": f"No {role} account found with this email adress."}), 404

                # 2. Generate OTP
                otp = str(random.randint(100000, 999999))
                expires_at = datetime.utcnow() + timedelta(minutes=10)
                
                # 3. Store in otp_verifications with a special 'RESET_PASSWORD' role suffix
                cur.execute("""
                    INSERT INTO otp_verifications (email, role, otp_code, payload, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email, role) DO UPDATE 
                    SET otp_code = EXCLUDED.otp_code, expires_at = EXCLUDED.expires_at, payload = EXCLUDED.payload
                """, (email, f"RESET_{role}", otp, str(user['id']), expires_at))
                
                conn.commit()

                # 4. Send Email
                # We reuse the utility but we could customize subject if needed
                email_sent = send_otp_email(email, otp)
                
                return jsonify({
                    "message": f"Verification code sent to your {role} email.",
                    "status": email_sent
                }), 200
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@forgot_password_bp.route('/verify-otp', methods=['POST'])
def verify_reset_otp():
    """Step 2: Validate the OTP code."""
    data = request.json
    email = data.get('email')
    role = data.get('userType')
    otp_submitted = data.get('otp')
    
    if not email or not role or not otp_submitted:
        return jsonify({"error": "Missing required verification data"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM otp_verifications 
                    WHERE email = %s AND role = %s AND expires_at > %s
                """, (email, f"RESET_{role}", datetime.utcnow()))
                record = cur.fetchone()
                
                if not record or record['otp_code'] != str(otp_submitted).strip():
                    return jsonify({"error": "Invalid or expired verification code"}), 400
                
                return jsonify({"message": "Identity verified! You may now reset your password."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@forgot_password_bp.route('/reset', methods=['POST'])
def reset_password():
    """Step 3: Update the user's password in target role."""
    data = request.json
    email = data.get('email')
    role = data.get('userType')
    otp = data.get('otp')
    new_password = data.get('newPassword')
    
    if not all([email, role, otp, new_password]):
        return jsonify({"error": "Incomplete reset request"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Re-verify OTP one last time for safety
                cur.execute("""
                    SELECT * FROM otp_verifications 
                    WHERE email = %s AND role = %s AND otp_code = %s AND expires_at > %s
                """, (email, f"RESET_{role}", str(otp).strip(), datetime.utcnow()))
                record = cur.fetchone()
                
                if not record:
                    return jsonify({"error": "Session expired or invalid. Please restart recovery."}), 400
                
                # 2. Update Password
                p_hash = generate_password_hash(new_password)
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (p_hash, record['payload']))
                
                # 3. Cleanup
                cur.execute("DELETE FROM otp_verifications WHERE id = %s", (record['id'],))
                
                conn.commit()
                return jsonify({"message": "Password successfully updated! Please log in with your new credentials."}), 200
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500
