import json
from datetime import datetime
from flask import Blueprint, request, jsonify
import razorpay
from utils.auth_utils import require_auth
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.invoice_generator import generate_and_send_invoice
from utils.gsheets_bot import append_to_sheet
from utils.crypto_utils import decrypt_data

registrations_bp = Blueprint('registrations', __name__)

@registrations_bp.route('/initiate', methods=['POST'])
@require_auth(roles=['student'])
def initiate_registration(current_user):
    data = request.json
    event_id = data.get('event_id')
    team_name = data.get('team_name')

    try:
        student_id = int(current_user['sub'])
        friend_ids = [int(fid) for fid in data.get('friend_ids', [])]
        all_member_ids = [student_id] + friend_ids
        print(f"DEBUG: Initiating reg for event {event_id} by student {student_id}. Team: {friend_ids}")
    except (ValueError, TypeError) as e:
        print(f"DEBUG: ID conversion error: {e}")
        return jsonify({"error": "Invalid participant ID format"}), 400

    if not event_id:
        return jsonify({"error": "Event ID is required"}), 400

    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Check if ANY member is already 'approved'
                cur.execute("SELECT student_id FROM registrations WHERE event_id = %s AND status = 'approved' AND student_id = ANY(%s)", (event_id, all_member_ids))
                already = cur.fetchone()
                if already:
                    return jsonify({"error": f"Member {already['student_id']} is already registered (approved) for this event"}), 400

                # 2. Cleanup ANY existing 'pending' registration for the current leader for this event
                # This allows them to restart the process if they previously closed the payment window.
                cur.execute("DELETE FROM registrations WHERE event_id = %s AND student_id = %s AND status = 'pending'", (event_id, student_id))

                # Fetch profiles for all members for completeness check
                cur.execute("""
                    SELECT id, full_name, reg_no, phone_number, address, dob, gender, department, college_email 
                    FROM users WHERE id = ANY(%s)
                """, (all_member_ids,))
                team_profiles = cur.fetchall()
                profiles_map = {int(p['id']): p for p in team_profiles}
                
                print(f"DEBUG: Found {len(team_profiles)} profiles for IDs {all_member_ids}")
                
                required_fields = ['reg_no', 'phone_number', 'address', 'dob', 'gender', 'department', 'college_email']
                for uid in all_member_ids:
                    p = profiles_map.get(uid)
                    if not p:
                        print(f"DEBUG: CRITICAL - Profile for ID {uid} missing in DB results. IDs fetched: {list(profiles_map.keys())}")
                        return jsonify({"error": f"Internal Error: Profile for ID {uid} not found"}), 404
                    missing = [f for f in required_fields if not p.get(f)]
                    if missing:
                        name_label = "Your" if uid == student_id else f"{p['full_name']}'s"
                        return jsonify({
                            "error": f"Incomplete Profile: {name_label}",
                            "details": f"{name_label} profile is missing: {', '.join(missing).replace('_', ' ')}. All team members must have complete profiles before registration.",
                            "missing_user_id": uid
                        }), 403

                # Fetch Event details
                cur.execute("""
                    SELECT e.title, e.reg_amount, e.club_id, e.female_mandatory, e.min_team_size, e.team_size as max_team_size,
                           e.reg_deadline, e.end_date,
                           c.razorpay_key_id, c.razorpay_key_secret
                    FROM events e
                    LEFT JOIN clubs c ON e.club_id = c.id
                    WHERE e.id = %s
                """, (event_id,))
                event = cur.fetchone()
                if not event: return jsonify({"error": "Event not found"}), 404

                now = datetime.now()
                if event['end_date'] and now > event['end_date']:
                    return jsonify({"error": "Cannot register for a past event"}), 400
                if event['reg_deadline'] and now > event['reg_deadline']:
                    return jsonify({"error": "Registration deadline reached"}), 400

                # 3. Team Size Validation
                team_count = len(all_member_ids)
                if team_count < (event['min_team_size'] or 1):
                    return jsonify({"error": f"Minimum {event['min_team_size']} members required"}), 400
                if team_count > (event['max_team_size'] or 1):
                    return jsonify({"error": f"Maximum {event['max_team_size']} members allowed"}), 400

                # 4. Gender Validation & Friend Verification
                cur.execute("SELECT id, gender, full_name FROM users WHERE id = ANY(%s)", (all_member_ids,))
                users_data = cur.fetchall()
                users_map = {u['id']: u for u in users_data}
                
                # Check if all friends are indeed "accepted" friends of the leader
                if friend_ids:
                    cur.execute("""
                        SELECT friend_id, user_id FROM friends 
                        WHERE status = 'accepted' AND 
                        ((user_id = %s AND friend_id = ANY(%s)) OR (friend_id = %s AND user_id = ANY(%s)))
                    """, (student_id, friend_ids, student_id, friend_ids))
                    valid_friends = cur.fetchall()
                    if len(valid_friends) < len(friend_ids):
                         return jsonify({"error": "One or more members are not in your confirmed friends list"}), 403

                # Policy Restriction: 1 Female Mandatory
                if event['female_mandatory']:
                    has_female = any(u['gender'] and u['gender'].lower() == 'female' for u in users_data)
                    if not has_female:
                        return jsonify({"error": "Policy Restriction: At least one female participant is mandatory for this event."}), 403

                # NEW: PRE-CHECK for duplicate registrations for ANY member
                cur.execute("""
                    SELECT r.student_id, u.full_name 
                    FROM registrations r
                    JOIN users u ON r.student_id = u.id
                    WHERE r.event_id = %s AND r.student_id = ANY(%s) AND r.status != 'cancelled'
                """, (event_id, all_member_ids))
                already_reg = cur.fetchall()
                if already_reg:
                    names = ", ".join([row['full_name'] for row in already_reg])
                    return jsonify({"error": f"One or more members are already registered for this mission: {names}"}), 400

                reg_amount = float(event['reg_amount'])

                if reg_amount <= 0:
                    # FREE EVENT: Create ONE registration for the team
                    cur.execute("""
                        SELECT e.title, e.start_date, c.name as club_name, c.master_gsheet_link
                        FROM events e
                        LEFT JOIN clubs c ON e.club_id = c.id
                        WHERE e.id = %s
                    """, (event_id,))
                    meta = cur.fetchone()
                    
                    # 1. Create one primary registration row for the team
                    target_leader_id = data.get('leader_id') or student_id
                    # 1. Create registration rows for EVERY member (explicit tracking)
                    target_leader_id = data.get('leader_id') or student_id
                    new_reg_id = None
                    for uid in all_member_ids:
                        cur.execute("""
                            INSERT INTO registrations (event_id, student_id, status, team_name, leader_id, payer_id)
                            VALUES (%s, %s, 'approved', %s, %s, %s) RETURNING id
                        """, (event_id, uid, team_name, target_leader_id, student_id))
                        if uid == target_leader_id:
                            new_reg_id = cur.fetchone()['id']
                        else:
                            # If we just inserted a member, we still need one ID for registration_members link
                            inserted_id = cur.fetchone()['id']
                            if not new_reg_id: new_reg_id = inserted_id

                    # 2. Add all members to registration_members
                    pay_datetime = datetime.now().isoformat()
                    for uid in all_member_ids:
                        cur.execute("INSERT INTO registration_members (registration_id, student_id) VALUES (%s, %s)", (new_reg_id, uid))
                        
                        # Sync and Invoice
                        p = profiles_map.get(uid)
                        if meta and meta['master_gsheet_link']:
                            try:
                                from utils.gsheets_bot import append_to_sheet
                                append_to_sheet(
                                    meta['master_gsheet_link'], meta['title'], meta['club_name'], 
                                    meta['start_date'].isoformat() if meta['start_date'] else "",
                                    p['full_name'], p['dob'], p['reg_no'], p['phone_number'],
                                    p['email'], p['college_email'], "FREE_REG", pay_datetime, team_name
                                )
                                generate_and_send_invoice(
                                    p['full_name'], [p['email'], p['college_email']], meta['title'], meta['club_name'], 
                                    0, "FREE_REG", pay_datetime,
                                    reg_no=p['reg_no'], student_p_email=p['email'],
                                    payer_name=profiles_map.get(student_id)['full_name'],
                                    payer_reg_no=profiles_map.get(student_id)['reg_no']
                                )
                            except Exception as e:
                                print(f"Free reg automation failed for {uid}: {e}")

                    conn.commit()
                    return jsonify({"message": "Successfully registered team for free event", "type": "free"}), 200

                # Paid Event: One order for the whole team (Leader pays)
                dec_key_id = decrypt_data(event['razorpay_key_id']) if event.get('razorpay_key_id') else None
                dec_key_secret = decrypt_data(event['razorpay_key_secret']) if event.get('razorpay_key_secret') else None
                if not dec_key_id or not dec_key_secret:
                    return jsonify({"error": "Payment gateway not configured for this club"}), 400

                client = razorpay.Client(auth=(dec_key_id, dec_key_secret))
                razorpay_order = client.order.create(dict(amount=int(reg_amount * 100), currency='INR', receipt=f"team_{event_id}_{student_id}"))
                
                # Insert pending registration for leader record (Primary record)
                target_leader_id = data.get('leader_id') or student_id
                cur.execute("""
                    INSERT INTO registrations (event_id, student_id, status, razorpay_order_id, amount_paid, team_name, leader_id, payer_id)
                    VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s) RETURNING id
                """, (event_id, target_leader_id, razorpay_order['id'], reg_amount, team_name, target_leader_id, student_id))
                reg_id = cur.fetchone()['id']
                
                # Insert members into registration_members (including leader for clarity)
                for uid in all_member_ids:
                    cur.execute("INSERT INTO registration_members (registration_id, student_id) VALUES (%s, %s)", (reg_id, uid))
                
                conn.commit()
                return jsonify({
                    "message": "Order created", "type": "paid", "order_id": razorpay_order['id'],
                    "amount": reg_amount, "key": dec_key_id
                }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@registrations_bp.route('/verify', methods=['POST'])
@require_auth(roles=['student'])
def verify_payment(current_user):
    data = request.json
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    
    if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
         return jsonify({"error": "Missing payment signature parameters"}), 400

    try:
         with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find pending registration
                cur.execute("""
                     SELECT r.id, r.event_id, r.amount_paid, r.student_id, r.leader_id, r.payer_id, r.team_name, e.title, e.start_date, 
                            c.name as club_name, c.razorpay_key_id, c.razorpay_key_secret, c.master_gsheet_link,
                            u.full_name, u.email, u.dob, u.reg_no, u.phone_number, u.college_email
                     FROM registrations r
                     JOIN events e ON r.event_id = e.id
                     LEFT JOIN clubs c ON e.club_id = c.id
                     JOIN users u ON r.student_id = u.id
                     WHERE r.razorpay_order_id = %s AND r.status = 'pending'
                """, (razorpay_order_id,))
                reg = cur.fetchone()

                if not reg:
                    return jsonify({"error": "No pending registration found for this order"}), 404

                dec_key_id = decrypt_data(reg['razorpay_key_id']) if reg.get('razorpay_key_id') else None
                dec_key_secret = decrypt_data(reg['razorpay_key_secret']) if reg.get('razorpay_key_secret') else None

                client = razorpay.Client(auth=(dec_key_id, dec_key_secret))
                
                # Check Signature
                try:
                    client.utility.verify_payment_signature({
                        'razorpay_order_id': razorpay_order_id,
                        'razorpay_payment_id': razorpay_payment_id,
                        'razorpay_signature': razorpay_signature
                    })
                except razorpay.errors.SignatureVerificationError:
                    return jsonify({"error": "Payment verification failed"}), 400

                # Mark as approved
                pay_datetime = datetime.now().isoformat()
                cur.execute("""
                    UPDATE registrations 
                    SET status = 'approved', razorpay_payment_id = %s, razorpay_signature = %s
                    WHERE id = %s
                """, (razorpay_payment_id, razorpay_signature, reg['id']))
                
                # Register all members from registration_members table
                cur.execute("SELECT student_id FROM registration_members WHERE registration_id = %s", (reg['id'],))
                members = cur.fetchall()
                for member in members:
                    # Skip the primary leader row (as it was updated above)
                    if member['student_id'] != reg['student_id']:
                         cur.execute("""
                            INSERT INTO registrations (event_id, student_id, status, razorpay_payment_id, amount_paid, team_name, leader_id, payer_id)
                            VALUES (%s, %s, 'approved', %s, 0, %s, %s, %s)
                            ON CONFLICT (event_id, student_id) DO UPDATE SET status = 'approved', razorpay_payment_id = EXCLUDED.razorpay_payment_id
                         """, (reg['event_id'], member['student_id'], razorpay_payment_id, reg['team_name'], reg['leader_id'], reg['payer_id']))

                conn.commit()

                # Trigger automations for all members
                try:
                     # 1. Append ALL members to sheet and send Invoices
                     start_dt_str = reg['start_date'].isoformat() if reg['start_date'] else ""
                     
                     cur.execute("""
                        SELECT u.id, u.full_name, u.email, u.dob, u.reg_no, u.phone_number, u.college_email
                        FROM registration_members rm
                        JOIN users u ON rm.student_id = u.id
                        WHERE rm.registration_id = %s
                     """, (reg['id'],))
                     team_members = cur.fetchall()
                     
                     for m in team_members:
                         # Sync to GSHEET
                         append_to_sheet(
                             reg['master_gsheet_link'], reg['title'], reg['club_name'], start_dt_str,
                             m['full_name'], m['dob'], m['reg_no'], m['phone_number'],
                             m['email'], m['college_email'], razorpay_payment_id, pay_datetime, reg['team_name']
                         )
                         # Send Invoice to EVERY Member (Both Emails)
                         generate_and_send_invoice(
                             m['full_name'], [m['email'], m['college_email']], reg['title'], reg['club_name'], 
                             reg['amount_paid'], # Show full mission cost for all teammates
                             razorpay_payment_id, pay_datetime,
                             reg_no=m['reg_no'], student_p_email=m['email'],
                             payer_name=reg['full_name'], payer_reg_no=reg['reg_no']
                         )
                except Exception as ex:
                     import logging
                     logging.error(f"Post-registration automation failed: {ex}")

                return jsonify({"message": "Registration successful"}), 200

    except Exception as e:
         return jsonify({"error": str(e)}), 500

@registrations_bp.route('/my-registrations', methods=['GET'])
@require_auth(roles=['student'])
def get_my_registrations(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                uid = int(current_user['sub'])
                cur.execute("""
                    SELECT DISTINCT r.id as reg_id, r.event_id, r.status, r.amount_paid, r.registered_at, r.team_name, r.razorpay_payment_id, r.edit_count,
                           r.leader_id, r.payer_id,
                           e.title, e.start_date, e.end_date, e.min_team_size, e.team_size as max_team_size,
                           h.name as hall_name, c.name as club_name,
                           COALESCE(att.manual_present, FALSE) as manual_present,
                           COALESCE(att.otp_present, FALSE) as otp_present,
                           att.event_otp
                    FROM registrations r
                    JOIN events e ON r.event_id = e.id
                    LEFT JOIN halls h ON e.hall_id = h.id
                    LEFT JOIN clubs c ON e.club_id = c.id
                    LEFT JOIN attendance att ON att.event_id = r.event_id AND att.student_id = %s
                    WHERE r.student_id = %s 
                       OR r.id IN (SELECT registration_id FROM registration_members WHERE student_id = %s)
                    ORDER BY r.registered_at DESC
                """, (uid, uid, uid))
                regs = cur.fetchall()
                for r in regs:
                    r['is_leader'] = (int(r['leader_id']) == uid)
                for r in regs:
                    if r['start_date']: r['start_date'] = r['start_date'].isoformat()
                    if r['end_date']: r['end_date'] = r['end_date'].isoformat()
                    if r['registered_at']: r['registered_at'] = r['registered_at'].isoformat()
                    
                    # Fetch team members for this registration
                    cur.execute("""
                        SELECT u.id, u.full_name, u.reg_no, u.gender
                        FROM registration_members rm
                        JOIN users u ON rm.student_id = u.id
                        WHERE rm.registration_id = %s
                    """, (r['reg_id'],))
                    r['members'] = cur.fetchall()

                return jsonify(regs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@registrations_bp.route('/edit-team', methods=['POST'])
@require_auth(roles=['student'])
def edit_team(current_user):
    data = request.json
    reg_id = data.get('reg_id')
    new_friend_ids = [int(fid) for fid in data.get('friend_ids', [])]
    
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch current registration & event time
                cur.execute("""
                    SELECT r.id, r.student_id, r.leader_id, r.payer_id, r.event_id, r.team_name, r.amount_paid, r.edit_count, 
                           e.start_date, e.min_team_size, e.team_size as max_team_size
                    FROM registrations r
                    JOIN events e ON r.event_id = e.id
                    WHERE r.id = %s
                """, (reg_id,))
                reg = cur.fetchone()
                
                if not reg: return jsonify({"error": "Registration record not found"}), 404
                
                # Check authorization: Only the current LEADER can edit
                if int(reg['leader_id']) != int(current_user['sub']):
                    return jsonify({"error": "Unauthorized: Only the team leader can modify members"}), 403
                
                # Check for modification limit (Allowing 2 edits now)
                if reg['edit_count'] and reg['edit_count'] >= 2:
                    return jsonify({"error": "Edit limit (2 times) already used for this registration"}), 403
                
                # Time check
                if reg['start_date']:
                    from datetime import timedelta
                    if datetime.now() > reg['start_date'] - timedelta(hours=7):
                        return jsonify({"error": "Modification window closed (Must edit 7+ hours before event)"}), 400

                new_leader_id = int(data.get('new_leader_id')) if data.get('new_leader_id') else int(reg['leader_id'])
                friend_ids = [int(fid) for fid in data.get('friend_ids', [])] # IDs of other members (excludes leader)
                
                all_ids = list(set([new_leader_id] + friend_ids))
                
                # 2. Team Size Validation
                if len(all_ids) < reg['min_team_size'] or len(all_ids) > reg['max_team_size']:
                    return jsonify({"error": f"Invalid team size. Must be between {reg['min_team_size']} and {reg['max_team_size']}"}), 400

                # 3. IDENTIFY UPDATES: Added vs Removed members
                # Current members in registrations for this team
                cur.execute("SELECT student_id FROM registrations WHERE event_id = %s AND leader_id = %s", (reg['event_id'], reg['leader_id']))
                current_members = [row['student_id'] for row in cur.fetchall()]
                
                to_add = [uid for uid in all_ids if uid not in current_members]
                to_remove = [uid for uid in current_members if uid not in all_ids]

                # 4. PERFORM DATABASE UPDATES
                # Remove rows for dropped members
                if to_remove:
                    cur.execute("DELETE FROM registrations WHERE event_id = %s AND leader_id = %s AND student_id = ANY(%s)", 
                               (reg['event_id'], reg['leader_id'], to_remove))
                
                # Global update for kept members (updates leader_id and potentially team_name if we wanted, but let's stick to leader)
                cur.execute("UPDATE registrations SET leader_id = %s WHERE event_id = %s AND leader_id = %s", 
                           (new_leader_id, reg['event_id'], reg['leader_id']))
                
                # Add rows for new members
                for uid in to_add:
                    cur.execute("""
                        INSERT INTO registrations (event_id, student_id, status, team_name, leader_id, payer_id, amount_paid)
                        VALUES (%s, %s, 'approved', %s, %s, %s, 0)
                    """, (reg['event_id'], uid, reg['team_name'], new_leader_id, reg['payer_id']))
                
                # Sync group-roster table (registration_members)
                # Note: We use the OLD reg_id as the anchor, but update its leader if needed above
                cur.execute("DELETE FROM registration_members WHERE registration_id = %s", (reg_id,))
                for uid in all_ids:
                    cur.execute("INSERT INTO registration_members (registration_id, student_id) VALUES (%s, %s)", (reg_id, uid))
                
                # Increment edit count on the primary record
                cur.execute("UPDATE registrations SET edit_count = edit_count + 1 WHERE id = %s", (reg_id,))
                
                conn.commit()
                return jsonify({"message": "Team and Leadership updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@registrations_bp.route('/club-applications', methods=['GET'])
@require_auth(roles=['organizer'])
def get_club_applications(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Get organizer's club_id
                cur.execute("SELECT club_id FROM users WHERE id = %s", (int(current_user['sub']),))
                user = cur.fetchone()
                if not user or not user['club_id']:
                    return jsonify({"error": "No club associated with this account"}), 403
                
                # 2. Fetch registrations (Consolidated View: showing only the Payer's record for each team)
                cur.execute("""
                    SELECT r.id as reg_id, r.event_id, r.status, r.amount_paid, r.registered_at, r.team_name, r.razorpay_payment_id, r.leader_id, r.payer_id,
                           e.title as event_title, 
                           u.full_name as leader_name, u.reg_no as leader_reg, u.email as leader_email
                    FROM registrations r
                    JOIN events e ON r.event_id = e.id
                    JOIN users u ON r.student_id = u.id
                    WHERE e.club_id = %s 
                    AND r.student_id = r.payer_id
                    ORDER BY r.registered_at DESC
                """, (user['club_id'],))
                regs = cur.fetchall()

                for r in regs:
                    if r['registered_at']: r['registered_at'] = r['registered_at'].isoformat()
                    # Fetch members
                    cur.execute("""
                        SELECT u.full_name, u.reg_no, u.gender
                        FROM registration_members rm
                        JOIN users u ON rm.student_id = u.id
                        WHERE rm.registration_id = %s
                    """, (r['reg_id'],))
                    r['members'] = cur.fetchall()

                return jsonify(regs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@registrations_bp.route('/get-attendees/<int:event_id>', methods=['GET'])
@require_auth(roles=['organizer', 'admin'])
def get_attendees(current_user, event_id):
    """Fetch participant list with attendance status for an event."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Permission Check
                cur.execute("SELECT organizer_id, attendance_locked FROM events WHERE id = %s", (event_id,))
                event = cur.fetchone()
                if not event: return jsonify({"error": "Event not found"}), 404
                
                is_locked = event['attendance_locked']
                
                if current_user['role'] == 'organizer' and int(event['organizer_id']) != int(current_user['sub']):
                    return jsonify({"error": "Unauthorized"}), 403

                # 2. Fetch Participants (Consolidated)
                # We fetch all individuals who are part of an approved registration for this event
                cur.execute("""
                    SELECT u.id as student_id, u.full_name, u.reg_no, u.department, u.gender, u.email, u.college_email,
                           r.id as registration_id, r.team_name,
                           COALESCE(att.manual_present, FALSE) as manual_present,
                           COALESCE(att.otp_present, FALSE) as otp_present,
                           att.event_otp, att.marked_at as manual_marked_at, att.otp_verified_at,
                           EXISTS(SELECT 1 FROM certificates WHERE event_id = %s AND student_id = u.id) as has_certificate
                    FROM registrations r
                    JOIN registration_members rm ON rm.registration_id = r.id
                    JOIN users u ON rm.student_id = u.id
                    LEFT JOIN attendance att ON att.event_id = r.event_id AND att.student_id = u.id
                    WHERE r.event_id = %s AND r.status = 'approved'
                    ORDER BY u.full_name ASC
                """, (event_id, event_id))
                
                participants = cur.fetchall()
                from utils.crypto_utils import decrypt_data
                for p in participants:
                    if p.get('department'):
                        p['department'] = decrypt_data(p['department'])
                    if p.get('manual_marked_at'):
                        p['manual_marked_at'] = p['manual_marked_at'].isoformat()
                    if p.get('otp_verified_at'):
                        p['otp_verified_at'] = p['otp_verified_at'].isoformat()
                
                return jsonify({
                    "participants": participants,
                    "locked": is_locked
                }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
