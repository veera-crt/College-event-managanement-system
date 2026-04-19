import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.crypto_utils import encrypt_data, decrypt_data

otp_bp = Blueprint('otp', __name__)

@otp_bp.route('/verify-otp', methods=['POST'])
def verify_otp():
    """
    Step 2: Validate the 6-digit OTP and perform actual database registration.
    """
    data = request.json
    email = data.get('email')
    role = data.get('userType')
    otp_submitted = data.get('otp')
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch OTP from DB
                cur.execute("""
                    SELECT otp_code, payload, expires_at 
                    FROM otp_verifications 
                    WHERE email = %s AND role = %s
                """, (email, role))
                record = cur.fetchone()
                
                if not record:
                    return jsonify({"error": "No verification request found. Please resend code."}), 400
                    
                # 2. Check Expiry
                if datetime.utcnow() > record['expires_at']:
                    return jsonify({"error": "OTP has expired. Please request a new one."}), 400
                    
                # Clean the input to remove any accidental spaces/type mismatches
                submitted_clean = str(otp_submitted).strip()
                if record['otp_code'] != submitted_clean:
                    return jsonify({"error": "Invalid verification code."}), 400
                    
                # 4. Decrypt and Parse original payload
                payload_json = decrypt_data(record['payload'])
                payload = json.loads(payload_json)
                
                # Register user logic...
                full_name = payload.get('fullName')
                reg_no = payload.get('regNo')
                password_hash = generate_password_hash(payload.get('password'))
                
                encrypted_phone = encrypt_data(payload.get('phone'))
                encrypted_address = encrypt_data(payload.get('address'))
                encrypted_dob = encrypt_data(payload.get('dob'))
                gender = payload.get('gender')
                
                raw_org_name = payload.get('orgName') if role in ['organizer', 'admin'] else None
                
                # Account starts 'active' for students/admins, but 'pending' for organizers
                account_status = 'active' if role in ['student', 'admin'] else 'pending'
                
                # Fetch club_id if organization_name is provided
                club_id = None
                if raw_org_name:
                    cur.execute("SELECT id FROM clubs WHERE name = %s", (raw_org_name,))
                    club_row = cur.fetchone()
                    if club_row:
                        club_id = club_row['id']
                
                # INSERT User
                # Note: organization_name is NOT encrypted to allow for Admin constraints and filtering
                cur.execute("""
                    INSERT INTO users (
                        full_name, email, reg_no, password_hash, 
                        phone_number, address, dob, gender, role, 
                        account_status, organization_name, club_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (full_name, email, reg_no, password_hash, encrypted_phone, encrypted_address, encrypted_dob, gender, role, account_status, raw_org_name, club_id))
                
                # 5. CLEAR verification record
                cur.execute("DELETE FROM otp_verifications WHERE email = %s AND role = %s", (email, role))
                
                conn.commit()
                
                status_message = "Account verified and active!"
                if role == 'organizer':
                    status_message = "OTP Verified! Your application has been sent to your Club Admin for approval. Please wait for their confirmation."
                    
                return jsonify({
                    "message": status_message, 
                    "account_status": account_status,
                    "redirect": "/sign-in.html"
                }), 201


    except Exception as e:
        return jsonify({"error": f"Database registration failed: {str(e)}"}), 500
