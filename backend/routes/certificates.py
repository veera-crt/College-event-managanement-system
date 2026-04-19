import os
from flask import Blueprint, request, jsonify, send_file
from utils.auth_utils import require_auth
from db import DatabaseConnection, logger
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
import io
import re

certificates_bp = Blueprint('certificates', __name__)

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'uploads', 'certificates')
# Vercel bypass for read-only filesystem
if os.environ.get('VERCEL') == '1':
    UPLOAD_FOLDER = '/tmp/uploads/certificates'

ALLOWED_EXTENSIONS = {'pdf'}

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create upload directory {UPLOAD_FOLDER}: {e}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@certificates_bp.route('/upload', methods=['POST'])
@require_auth(roles=['organizer'])
def upload_certificate(current_user):
    """
    Organizer uploads a PDF certificate for a specific student who attended an event.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    event_id = request.form.get('event_id')
    student_id = request.form.get('student_id')
    
    if not event_id or not student_id or file.filename == '':
        return jsonify({"error": "Missing event_id, student_id or file"}), 400
    
    if file and allowed_file(file.filename):
        try:
            with DatabaseConnection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 1. Verify organizer ownership
                    cur.execute("SELECT id FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                    if not cur.fetchone():
                        return jsonify({"error": "Unauthorized"}), 403

                    # 2. Verify student attendance (Eligibility)
                    cur.execute("SELECT id FROM attendance WHERE event_id = %s AND student_id = %s", (event_id, student_id))
                    if not cur.fetchone():
                        return jsonify({"error": "Student has not marked attendance for this event"}), 400

                    # 3. Save File
                    filename = secure_filename(f"cert_{event_id}_{student_id}.pdf")
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)

                    # 4. Save to Database
                    cur.execute("""
                        INSERT INTO certificates (event_id, student_id, file_url)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (event_id, student_id) 
                        DO UPDATE SET file_url = EXCLUDED.file_url, uploaded_at = CURRENT_TIMESTAMP
                    """, (event_id, student_id, filename))
                    
                    conn.commit()
                    return jsonify({"message": "Certificate uploaded successfully"}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "File type not allowed. Please upload a PDF."}), 400

@certificates_bp.route('/update-folder-link', methods=['POST'])
@require_auth(roles=['organizer'])
def update_cert_folder_link(current_user):
    data = request.json
    event_id = data.get('event_id')
    folder_url = data.get('folder_url')
    
    if not event_id:
        return jsonify({"error": "Missing event_id"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Verify ownership
                cur.execute("SELECT id FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                if not cur.fetchone():
                    return jsonify({"error": "Unauthorized"}), 403
                    
                cur.execute("UPDATE events SET cert_folder_url = %s WHERE id = %s", (folder_url, event_id))
                conn.commit()
                return jsonify({"message": "Certificate folder link updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@certificates_bp.route('/upload-by-reg', methods=['POST'])
@require_auth(roles=['organizer'])
def upload_by_reg_no(current_user):
    """
    Organizer uploads a PDF named exactly 'REG_NO.pdf'.
    Backend matches reg_no to student_id and verify 2FA attendance.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    event_id = request.form.get('event_id')
    
    if not event_id or file.filename == '':
        return jsonify({"error": "Missing event_id or file"}), 400
    
    # Extract reg_no from filename (e.g., RA2111003.pdf -> RA2111003)
    reg_no = os.path.splitext(file.filename)[0].strip()
    
    if file and allowed_file(file.filename):
        try:
            with DatabaseConnection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 1. Verify organizer ownership
                    cur.execute("SELECT id FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                    if not cur.fetchone():
                        return jsonify({"error": "Unauthorized"}), 403

                    # 2. Find student by Registration Number and verify participation
                    cur.execute("""
                        SELECT u.id, u.full_name
                        FROM users u
                        JOIN registration_members rm ON u.id = rm.student_id
                        JOIN registrations r ON rm.registration_id = r.id
                        WHERE u.reg_no = %s AND r.event_id = %s AND r.status = 'approved'
                    """, (reg_no, event_id))
                    student = cur.fetchone()
                    
                    if not student:
                        return jsonify({"error": f"Student with Reg No {reg_no} not found or not registered for this event."}), 404

                    student_id = student['id']

                    # 3. STRICT 2FA Attendance Check (Manual + OTP)
                    cur.execute("""
                        SELECT manual_present, otp_present 
                        FROM attendance 
                        WHERE event_id = %s AND student_id = %s
                    """, (event_id, student_id))
                    attendance = cur.fetchone()

                    if not attendance:
                        return jsonify({"error": f"No attendance record found for {student['full_name']}."}), 400
                    
                    if not (attendance['manual_present'] and attendance['otp_present']):
                        return jsonify({
                            "error": f"Incomplete Attendance: {student['full_name']} must have both manual and OTP verification to receive a certificate."
                        }), 400

                    # 4. VIRTUAL ASSIGNMENT (ZERO STORAGE)
                    # We do NOT save the file contents to reclaim space.
                    # We store the reg_no as the reference in file_url.
                    reference = f"{reg_no}.pdf"

                    # 5. Save/Update to Database
                    cur.execute("""
                        INSERT INTO certificates (event_id, student_id, file_url)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (event_id, student_id) 
                        DO UPDATE SET file_url = EXCLUDED.file_url, uploaded_at = CURRENT_TIMESTAMP
                    """, (event_id, student_id, reference))
                    
                    conn.commit()
                    return jsonify({
                        "message": f"Successfully issued to {student['full_name']}",
                        "student_name": student['full_name'],
                        "reg_no": reg_no
                    }), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Only PDF files named 'REG_NO.pdf' are allowed."}), 400

@certificates_bp.route('/distribute-all', methods=['POST'])
@require_auth(roles=['organizer'])
def distribute_all_certs(current_user):
    """
    Automated Distribution: Finds everyone with 2FA attendance and issues virtual links.
    """
    data = request.json
    event_id = data.get('event_id')
    
    if not event_id:
        return jsonify({"error": "Missing event_id"}), 400
        
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Verify ownership and check for Folder Link
                cur.execute("SELECT cert_folder_url FROM events WHERE id = %s AND organizer_id = %s", (event_id, int(current_user['sub'])))
                event = cur.fetchone()
                if not event:
                    return jsonify({"error": "Event not found or unauthorized"}), 404
                
                if not event['cert_folder_url']:
                    return jsonify({"error": "Please provide a Google Drive Folder Link first."}), 400

                # 2. Find eligible students (Manual + OTP Present)
                # We also join with users to get their reg_no for the virtual link
                cur.execute("""
                    SELECT u.id as student_id, u.full_name, u.reg_no
                    FROM users u
                    JOIN attendance a ON u.id = a.student_id
                    WHERE a.event_id = %s AND a.manual_present = TRUE AND a.otp_present = TRUE
                """, (event_id,))
                eligible_students = cur.fetchall()

                if not eligible_students:
                    return jsonify({"error": "No students found with complete (Manual + OTP) attendance records."}), 404

                # 3. Bulk Assign
                # Extraction logic for folder_id
                folder_url = event['cert_folder_url']
                folder_id_match = re.search(r'folders/([-\w]{25,})', folder_url)
                folder_id = folder_id_match.group(1) if folder_id_match else None
                
                success_count = 0
                for student in eligible_students:
                    # Pre-calculate the full search link
                    reg_no_pdf = f"{student['reg_no']}.pdf"
                    if folder_id:
                        final_link = f"https://drive.google.com/drive/folders/{folder_id}?q={reg_no_pdf}"
                    else:
                        final_link = folder_url # Fallback

                    cur.execute("""
                        INSERT INTO certificates (event_id, student_id, file_url)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (event_id, student_id) 
                        DO UPDATE SET file_url = EXCLUDED.file_url, uploaded_at = CURRENT_TIMESTAMP
                    """, (event_id, student['student_id'], final_link))
                    success_count += 1
                
                conn.commit()
                return jsonify({
                    "message": f"Successfully distributed {success_count} virtual certificates.",
                    "distributed_count": success_count,
                    "students": [s['full_name'] for s in eligible_students]
                }), 200
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@certificates_bp.route('/my-certificates', methods=['GET'])
@require_auth(roles=['student', 'organizer'])
def get_my_certificates(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if current_user['role'] == 'organizer':
                    cur.execute("""
                        SELECT c.id, c.event_id, c.uploaded_at, e.title as event_title, 
                               e.start_date, e.cert_folder_url, u.full_name as student_name, u.reg_no
                        FROM certificates c
                        JOIN events e ON c.event_id = e.id
                        JOIN users u ON c.student_id = u.id
                        WHERE e.organizer_id = %s
                        ORDER BY c.uploaded_at DESC
                    """, (int(current_user['sub']),))
                else:
                    cur.execute("""
                        SELECT c.id, c.event_id, c.file_url, c.uploaded_at, e.title as event_title, e.start_date, e.cert_folder_url
                        FROM certificates c
                        JOIN events e ON c.event_id = e.id
                        WHERE c.student_id = %s
                        ORDER BY c.uploaded_at DESC
                    """, (int(current_user['sub']),))
                return jsonify(cur.fetchall()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@certificates_bp.route('/download/<int:cert_id>', methods=['GET'])
@require_auth(roles=['student', 'admin', 'organizer'])
def download_certificate(current_user, cert_id):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.*, e.cert_folder_url 
                    FROM certificates c 
                    JOIN events e ON c.event_id = e.id 
                    WHERE c.id = %s
                """, (cert_id,))
                cert = cur.fetchone()
                
                if not cert:
                    return jsonify({"error": "Certificate record not found"}), 404
                
                if current_user['role'] == 'student' and int(cert['student_id']) != int(current_user['sub']):
                    return jsonify({"error": "Access Denied"}), 403
                
                # Zero-Storage Referral Logic
                # The file_url now contains the PRE-CALCULATED full Drive link
                final_link = cert['file_url']
                
                if not final_link:
                    return jsonify({"error": "Certificate link missing."}), 400

                return jsonify({"redirect_url": final_link}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
