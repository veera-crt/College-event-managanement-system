from flask import Blueprint, request, jsonify
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.auth_utils import require_auth
from utils.email_utils import send_otp_email
from utils.crypto_utils import encrypt_data, decrypt_data
import random
from datetime import datetime, timedelta

profile_bp = Blueprint('profile', __name__)

@profile_bp.route('/get', methods=['GET'])
@require_auth(['student', 'organizer', 'admin'])
def get_profile(current_user):
    """Fetch current user's profile details."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT u.id, u.full_name, u.email, u.reg_no, u.phone_number, u.address, u.dob, u.department, u.college_email, c.name as organization_name 
                    FROM users u
                    LEFT JOIN clubs c ON u.club_id = c.id 
                    WHERE u.id = %s
                """, (current_user['sub'],))
                user_data = cur.fetchone()
                
                if not user_data:
                    return jsonify({"error": "User not found"}), 404
                
                # Decrypt sensitive fields (orgName is plaintext now)
                user_data['phone_number'] = decrypt_data(user_data['phone_number'])
                user_data['address'] = decrypt_data(user_data['address'])
                user_data['dob'] = decrypt_data(user_data['dob'])
                user_data['department'] = decrypt_data(user_data['department'])
                    
                return jsonify({"user": user_data}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route('/update-basic', methods=['POST'])
@require_auth(['student', 'organizer', 'admin'])
def update_profile(current_user):
    """Update non-sensitive profile fields."""
    data = request.json
    full_name = data.get('full_name')
    phone = data.get('phone_number')
    dob = data.get('dob')
    dept = data.get('department')
    address = data.get('address')
    
    try:
        # Encrypt what we store
        enc_phone = encrypt_data(phone)
        enc_dob = encrypt_data(dob)
        enc_dept = encrypt_data(dept)
        enc_address = encrypt_data(address)

        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users 
                    SET full_name = %s, phone_number = %s, dob = %s, department = %s, address = %s 
                    WHERE id = %s
                """, (full_name, enc_phone, enc_dob, enc_dept, enc_address, current_user['sub']))
                conn.commit()
                return jsonify({"message": "Profile updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route('/send-college-email-otp', methods=['POST'])
@require_auth(['student'])
def send_college_otp(current_user):
    """Send OTP to verify a new college email address."""
    data = request.json
    new_email = data.get('college_email')
    
    if not new_email or '@' not in new_email:
        return jsonify({"error": "Valid college email is required"}), 400
        
    otp = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                # Upsert OTP into the verification table
                cur.execute("""
                    INSERT INTO otp_verifications (email, role, otp_code, payload, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email, role) DO UPDATE 
                    SET otp_code = EXCLUDED.otp_code, expires_at = EXCLUDED.expires_at, payload = EXCLUDED.payload
                """, (new_email, 'PROFILE_COLLEGE_UPDATE', otp, str(current_user['sub']), expires_at))
                conn.commit()
        
        # Call the existing SMTP module
        email_sent = send_otp_email(new_email, otp)
        print(f"✉️ Profile Update OTP sent to {new_email} for User {current_user['sub']}")
        
        return jsonify({"message": "OTP sent to your college email", "status": email_sent}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route('/verify-college-email', methods=['POST'])
@require_auth(['student'])
def verify_college_email(current_user):
    """Verify OTP and then update the users table with the new college email."""
    data = request.json
    email = data.get('email')
    otp_submitted = data.get('otp')
    
    if not email or not otp_submitted:
        return jsonify({"error": "Email and OTP are required"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check verification record
                cur.execute("""
                    SELECT * FROM otp_verifications 
                    WHERE email = %s AND role = %s AND expires_at > %s
                """, (email, 'PROFILE_COLLEGE_UPDATE', datetime.utcnow()))
                record = cur.fetchone()
                
                if not record or record['otp_code'] != str(otp_submitted).strip():
                    return jsonify({"error": "Invalid or expired verification code"}), 400
                
                # Check if this OTP belongs to THE current user
                if str(record['payload']) != str(current_user['sub']):
                    return jsonify({"error": "Security breach: OTP ownership mismatch"}), 403
                
                # Success: Update the users table
                cur.execute("UPDATE users SET college_email = %s WHERE id = %s", (email, current_user['sub']))
                
                # Cleanup: Delete used OTP
                cur.execute("DELETE FROM otp_verifications WHERE id = %s", (record['id'],))
                
                conn.commit()
                return jsonify({"message": "College email verified and updated successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route('/send-password-otp', methods=['POST'])
@require_auth(['student', 'organizer', 'admin'])
def send_password_otp(current_user):
    """Send OTP to primary email to authorize password change."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (current_user['sub'],))
                user = cur.fetchone()
                if not user:
                    return jsonify({"error": "User not found"}), 404
                email = user[0]
                
        otp = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO otp_verifications (email, role, otp_code, payload, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email, role) DO UPDATE 
                    SET otp_code = EXCLUDED.otp_code, expires_at = EXCLUDED.expires_at, payload = EXCLUDED.payload
                """, (email, 'PROFILE_PASSWORD_UPDATE', otp, str(current_user['sub']), expires_at))
                conn.commit()
                
        email_sent = send_otp_email(email, otp)
        return jsonify({"message": "Password reset OTP sent to your primary email", "status": email_sent}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route('/verify-password', methods=['POST'])
@require_auth(['student', 'organizer', 'admin'])
def verify_password_update(current_user):
    """Verify OTP and update password."""
    data = request.json
    otp_submitted = data.get('otp')
    new_password = data.get('new_password')
    
    if not otp_submitted or not new_password:
        return jsonify({"error": "OTP and new password are required"}), 400
        
    try:
        from werkzeug.security import generate_password_hash
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (current_user['sub'],))
                user = cur.fetchone()
                if not user: return jsonify({"error": "User not found"}), 404
                email = user['email']
                
                cur.execute("""
                    SELECT * FROM otp_verifications 
                    WHERE email = %s AND role = %s AND expires_at > %s
                """, (email, 'PROFILE_PASSWORD_UPDATE', datetime.utcnow()))
                record = cur.fetchone()
                
                if not record or record['otp_code'] != str(otp_submitted).strip():
                    return jsonify({"error": "Invalid or expired OTP"}), 400
                    
                if str(record['payload']) != str(current_user['sub']):
                    return jsonify({"error": "OTP ownership mismatch"}), 403
                    
                password_hash = generate_password_hash(new_password)
                
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, current_user['sub']))
                cur.execute("DELETE FROM otp_verifications WHERE id = %s", (record['id'],))
                
                conn.commit()
                return jsonify({"message": "Password successfully updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
