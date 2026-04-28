from flask import Blueprint, request, jsonify
from utils.auth_utils import require_auth
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

attendance_bp = Blueprint('attendance', __name__)

def validate_attendance_window(event):
    ist_offset = timedelta(hours=5, minutes=30)
    now = datetime.utcnow() + ist_offset
    if now < event['start_date']:
        return "Attendance can only be managed after the event has started."
    if now > event['end_date'] + timedelta(hours=24):
        return "Attendance management window has closed. It is only available for 24 hours after the event ends."
    return None

@attendance_bp.route('/mark', methods=['POST'])
@require_auth(roles=['organizer'])
def mark_attendance(current_user):
    data = request.json
    event_id = data.get('event_id')
    student_id = data.get('student_id')
    
    if not event_id or not student_id:
        return jsonify({"error": "Missing event_id or student_id"}), 400

    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Verify organizer ownership and LACK OF LOCK
                cur.execute("SELECT id, attendance_locked, start_date, end_date FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                event = cur.fetchone()
                if not event:
                     return jsonify({"error": "Unauthorized"}), 403
                
                window_error = validate_attendance_window(event)
                if window_error:
                    return jsonify({"error": window_error}), 403
                
                if event['attendance_locked']:
                    return jsonify({"error": "Registry Locked: This event's attendance is closed for changes."}), 403

                # 2. Mark manual attendance
                cur.execute("""
                    INSERT INTO attendance (event_id, student_id, manual_present, marked_at)
                    VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT (event_id, student_id) 
                    DO UPDATE SET manual_present = TRUE, marked_at = CURRENT_TIMESTAMP
                """, (event_id, student_id))
                
                conn.commit()
                return jsonify({"message": "Manual attendance marked"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@attendance_bp.route('/unmark', methods=['POST'])
@require_auth(roles=['organizer'])
def unmark_attendance(current_user):
    data = request.json
    event_id = data.get('event_id')
    student_id = data.get('student_id')
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, attendance_locked, start_date, end_date FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                event = cur.fetchone()
                if not event:
                     return jsonify({"error": "Unauthorized"}), 403
                
                window_error = validate_attendance_window(event)
                if window_error:
                    return jsonify({"error": window_error}), 403
                
                if event['attendance_locked']:
                    return jsonify({"error": "Registry Locked: Cannot clear attendance."}), 403

                cur.execute("UPDATE attendance SET manual_present = FALSE WHERE event_id = %s AND student_id = %s", (event_id, student_id))
                conn.commit()
                return jsonify({"message": "Manual attendance cleared"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@attendance_bp.route('/toggle-lock', methods=['POST'])
@require_auth(roles=['organizer'])
def toggle_attendance_lock(current_user):
    data = request.json
    event_id = data.get('event_id')
    
    if not event_id:
        return jsonify({"error": "Missing event_id"}), 400

    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, attendance_locked, start_date, end_date FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                event = cur.fetchone()
                if not event:
                    return jsonify({"error": "Unauthorized"}), 403
                
                window_error = validate_attendance_window(event)
                if window_error:
                    return jsonify({"error": window_error}), 403
                
                new_state = not event['attendance_locked']
                cur.execute("UPDATE events SET attendance_locked = %s WHERE id = %s", (new_state, event_id))
                conn.commit()
                
                return jsonify({
                    "message": f"Registry {'Locked' if new_state else 'Released'}", 
                    "locked": new_state
                }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@attendance_bp.route('/generate-otps', methods=['POST'])
@require_auth(roles=['organizer'])
def generate_event_otps(current_user):
    """Generates unique random codes for all approved participants of an event."""
    data = request.json
    event_id = data.get('event_id')
    
    if not event_id:
        return jsonify({"error": "Missing event_id"}), 400

    try:
        import random
        import string

        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Verify ownership and lock
                cur.execute("SELECT id, attendance_locked, start_date, end_date FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                event = cur.fetchone()
                if not event:
                    return jsonify({"error": "Unauthorized"}), 403
                
                window_error = validate_attendance_window(event)
                if window_error:
                    return jsonify({"error": window_error}), 403
                
                if event['attendance_locked']:
                    return jsonify({"error": "Registry Locked: Cannot regenerate OTPs."}), 403

                # Get all approved registrations
                cur.execute("""
                    SELECT rm.student_id 
                    FROM registration_members rm
                    JOIN registrations r ON rm.registration_id = r.id
                    WHERE r.event_id = %s AND r.status = 'approved'
                """, (event_id,))
                students = cur.fetchall()

                for s in students:
                    otp = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    cur.execute("""
                        INSERT INTO attendance (event_id, student_id, event_otp, otp_sent_at)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (event_id, student_id) 
                        DO UPDATE SET event_otp = EXCLUDED.event_otp, otp_sent_at = CURRENT_TIMESTAMP
                    """, (event_id, s['student_id'], otp))

                conn.commit()
                return jsonify({"message": f"OTPs generated for {len(students)} participants"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@attendance_bp.route('/verify-otp', methods=['POST'])
@require_auth(roles=['student'])
def verify_event_otp(current_user):
    """Student submits the code found in their dashboard."""
    data = request.json
    event_id = data.get('event_id')
    otp = data.get('otp', '').strip().upper()
    
    if not event_id or not otp:
        return jsonify({"error": "Missing event_id or OTP"}), 400

    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check event lock first
                cur.execute("SELECT attendance_locked FROM events WHERE id = %s", (event_id,))
                event = cur.fetchone()
                if event and event['attendance_locked']:
                    return jsonify({"error": "Attendance Closed: The organizer has locked the registry for this event."}), 403

                cur.execute("""
                    SELECT event_otp FROM attendance 
                    WHERE event_id = %s AND student_id = %s
                """, (event_id, int(current_user['sub'])))
                record = cur.fetchone()

                if not record or not record['event_otp']:
                    return jsonify({"error": "No OTP has been generated for you yet. Contact the organizer."}), 404
                
                if record['event_otp'] != otp:
                    return jsonify({"error": "Invalid verification code"}), 400

                cur.execute("""
                    UPDATE attendance SET otp_present = TRUE, otp_verified_at = CURRENT_TIMESTAMP
                    WHERE event_id = %s AND student_id = %s
                """, (event_id, int(current_user['sub'])))
                
                conn.commit()
                return jsonify({"message": "Presence verified successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
