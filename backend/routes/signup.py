import json
import random
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from utils.email_utils import send_otp_email
from utils.crypto_utils import encrypt_data
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor

signup_bp = Blueprint('signup', __name__)

@signup_bp.route('/send-otp', methods=['POST'])
def send_otp():
    """
    Step 1: Validate payload and issue a 6-digit random OTP for email verification.
    Includes logic for club-based constraints (1 admin per club, organizer requires admin).
    """
    data = request.json
    email = data.get('email')
    role = data.get('userType')
    org_name = data.get('orgName')
    
    if not email or not role:
        return jsonify({"error": "Email and User Type are required"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Global Deduplicate: Check if email exists in either email or college_email columns
                cur.execute("""
                    SELECT id FROM users 
                    WHERE email = %s OR college_email = %s
                """, (email, email))
                if cur.fetchone():
                    return jsonify({"error": "This email address is already registered with another account"}), 409

                # Check if registration number is already registered
                reg_no = data.get('regNo')
                if reg_no:
                    cur.execute("SELECT id FROM users WHERE reg_no = %s", (reg_no,))
                    if cur.fetchone():
                        return jsonify({"error": "User already exists with this registration number"}), 409

                # 2. Role-Based Club Constraints
                if role == 'admin' and org_name:
                    # Constraint: Only one admin per club
                    cur.execute("SELECT id FROM users WHERE role = 'admin' AND organization_name = %s", (org_name,))
                    if cur.fetchone():
                        return jsonify({"error": f"Access Denied: An Administrator for '{org_name}' has already been registered."}), 403

                elif role == 'organizer' and org_name:
                    # Constraint: Club admin must exist
                    cur.execute("SELECT id FROM users WHERE role = 'admin' AND organization_name = %s", (org_name,))
                    if not cur.fetchone():
                        return jsonify({"error": f"Registration Denied: No Administrator found for '{org_name}'. Please contact your club head to register as Admin first."}), 403

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Generate Secure 6-digit OTP
    otp = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=5)
    
    # Encrypt the registration payload for DB storage
    encrypted_payload = encrypt_data(json.dumps(data))
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                # Store or overwrite existing OTP for this email+role
                cur.execute("""
                    INSERT INTO otp_verifications (email, role, otp_code, payload, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email, role) DO UPDATE 
                    SET otp_code = EXCLUDED.otp_code, 
                        payload = EXCLUDED.payload, 
                        expires_at = EXCLUDED.expires_at
                """, (email, role, otp, encrypted_payload, expires_at))
                conn.commit()
    except Exception as e:
        return jsonify({"error": f"Failed to store verification: {str(e)}"}), 500

    # REAL SMTP EMAIL SENDING
    email_sent = send_otp_email(email, otp)
    print(f"✉️ SMTP OTP sent to {email} (Result: {email_sent})")
    
    return jsonify({"message": "OTP sent successfully", "mail_status": email_sent}), 200

