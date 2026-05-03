import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
import razorpay
from utils.auth_utils import require_auth
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from utils.invoice_generator import generate_and_send_invoice
from utils.gsheets_bot import append_to_sheet
from utils.crypto_utils import decrypt_data

def check_event_clashes(cur, student_ids, new_start, new_end, current_reg_id=None):
    """
    Returns a list of clashes for the given students within the time window.
    """
    cur.execute("""
        SELECT rm.student_id, u.full_name, u.reg_no, e.title as event_title, e.start_date, e.end_date
        FROM registration_members rm
        JOIN registrations r ON rm.registration_id = r.id
        JOIN events e ON r.event_id = e.id
        JOIN users u ON rm.student_id = u.id
        WHERE rm.student_id = ANY(%s)
          AND r.status IN ('approved', 'ready_to_pay', 'waiting_friends')
          AND r.id != COALESCE(%s, -1)
          AND (
            (e.start_date::date = %s::date OR e.end_date::date = %s::date)
            OR (e.start_date < %s AND e.end_date > %s)
          )
    """, (student_ids, current_reg_id, new_start, new_end, new_end, new_start))
    potential_clashes = cur.fetchall()
    
    clashes = []
    for c in potential_clashes:
        # Overlap check: (start1 < end2) AND (end1 > start2)
        is_overlap = (new_start < c['end_date']) and (new_end > c['start_date'])
        clash_type = 'same_time' if is_overlap else 'same_day'
        clashes.append({
            "student_id": c['student_id'],
            "full_name": c['full_name'],
            "reg_no": c['reg_no'],
            "event_title": c['event_title'],
            "clash_type": clash_type,
            "start_time": c['start_date'].isoformat(),
            "end_time": c['end_date'].isoformat()
        })
    return clashes

def finalize_free_registration(cur, reg_id, event_id, team_name, student_ids):
    cur.execute("""
        SELECT e.title, e.start_date, c.name as club_name, c.master_gsheet_link
        FROM events e
        LEFT JOIN clubs c ON e.club_id = c.id
        WHERE e.id = %s
    """, (event_id,))
    meta = cur.fetchone()
    
    cur.execute("SELECT id, full_name, reg_no, phone_number, dob, gender, college_email FROM users WHERE id = ANY(%s)", (student_ids,))
    profiles_map = {p['id']: p for p in cur.fetchall()}
    pay_dt = (datetime.utcnow() + timedelta(hours=5, minutes=30)).isoformat()
    
    for uid in student_ids:
        p = profiles_map.get(uid)
        if not p: continue
        if meta and meta['master_gsheet_link']:
            try:
                append_to_sheet(meta['master_gsheet_link'], meta['title'], meta['club_name'], meta['start_date'].isoformat(),
                                p['full_name'], p['dob'], p['reg_no'], p['phone_number'], p['college_email'], p['college_email'],
                                "FREE_REG", pay_dt, team_name)
                generate_and_send_invoice(p['full_name'], [p['college_email']], meta['title'], meta['club_name'], 0, "FREE_REG", pay_dt,
                                          reg_no=p['reg_no'], student_p_email=p['college_email'], payer_name="System", payer_reg_no="N/A")
            except Exception as e: print(f"Automation error: {e}")

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
                # 1. Check if ANY member is already 'approved' for this event
                cur.execute("""
                    SELECT r.student_id, u.full_name, u.reg_no 
                    FROM registrations r 
                    JOIN users u ON r.student_id = u.id 
                    WHERE r.event_id = %s AND r.status IN ('approved', 'ready_to_pay', 'waiting_friends') AND r.student_id = ANY(%s)
                """, (event_id, all_member_ids))
                already = cur.fetchone()
                if already:
                    return jsonify({"error": f"{already['full_name']} ({already['reg_no']}) is already registered for this event."}), 400

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
                           e.reg_deadline, e.start_date, e.end_date, e.hall_id,
                           c.razorpay_key_id, c.razorpay_key_secret,
                           h.capacity as hall_capacity
                    FROM events e
                    LEFT JOIN clubs c ON e.club_id = c.id
                    LEFT JOIN halls h ON e.hall_id = h.id
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

                # 4. Hall Capacity Validation
                if event['hall_capacity']:
                    cur.execute("""
                        SELECT COUNT(rm.student_id) as current_count
                        FROM registration_members rm
                        JOIN registrations r ON rm.registration_id = r.id
                        WHERE r.event_id = %s AND r.status IN ('approved', 'pending')
                    """, (event_id,))
                    current_count = cur.fetchone()['current_count']
                    
                    spots_left = event['hall_capacity'] - current_count
                    if spots_left <= 0:
                        return jsonify({"error": "Event full error. The hall capacity has been reached."}), 400
                        
                    if team_count > spots_left:
                        return jsonify({"error": f"Only {spots_left} persons allowed to register. Cannot register a team of {team_count}."}), 400

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

                # NEW: Collision Check
                force_clash = data.get('force_clash_acknowledge', False)
                clashes = check_event_clashes(cur, all_member_ids, event['start_date'], event['end_date'])
                
                if clashes and not force_clash:
                    return jsonify({"error": "Schedule conflict detected", "clashes": clashes}), 409

                reg_amount = float(event['reg_amount'])
                target_leader_id = int(data.get('leader_id', student_id))

                if len(friend_ids) > 0:
                    # ASYNC TEAM FLOW: Waiting for friends
                    cur.execute("""
                        INSERT INTO registrations (event_id, student_id, status, amount_paid, team_name, leader_id, payer_id)
                        VALUES (%s, %s, 'waiting_friends', %s, %s, %s, %s) RETURNING id
                    """, (event_id, target_leader_id, reg_amount, team_name, target_leader_id, student_id))
                    reg_id = cur.fetchone()['id']
                    
                    expiry = datetime.now() + timedelta(hours=1)
                    for uid in all_member_ids:
                        status = 'accepted' if uid == student_id else 'pending'
                        cur.execute("""
                            INSERT INTO registration_members (registration_id, student_id, invite_status, invite_expires_at)
                            VALUES (%s, %s, %s, %s)
                        """, (reg_id, uid, status, expiry))
                    
                    conn.commit()
                    return jsonify({"message": "Invitations sent to team members", "type": "team_invite", "registration_id": reg_id}), 200

                if reg_amount <= 0:
                    # FREE SOLO: Finalize immediately
                    cur.execute("""
                        INSERT INTO registrations (event_id, student_id, status, amount_paid, team_name, leader_id, payer_id)
                        VALUES (%s, %s, 'approved', 0, %s, %s, %s) RETURNING id
                    """, (event_id, target_leader_id, team_name, target_leader_id, student_id))
                    new_reg_id = cur.fetchone()['id']
                    
                    cur.execute("INSERT INTO registration_members (registration_id, student_id, invite_status) VALUES (%s, %s, 'accepted')", (new_reg_id, student_id))
                    
                    finalize_free_registration(cur, new_reg_id, event_id, team_name, all_member_ids)
                    conn.commit()
                    return jsonify({"message": "Successfully registered for free event", "type": "free"}), 200

                # PAID SOLO FLOW: Standard order creation
                client = razorpay.Client(auth=(decrypt_data(event['razorpay_key_id']), decrypt_data(event['razorpay_key_secret'])))
                razorpay_order = client.order.create(dict(amount=int(reg_amount * 100), currency='INR', receipt=f"solo_{event_id}_{student_id}"))
                
                cur.execute("""
                    INSERT INTO registrations (event_id, student_id, status, razorpay_order_id, amount_paid, team_name, leader_id, payer_id)
                    VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s) RETURNING id
                """, (event_id, target_leader_id, razorpay_order['id'], reg_amount, team_name, target_leader_id, student_id))
                reg_id = cur.fetchone()['id']
                cur.execute("INSERT INTO registration_members (registration_id, student_id, invite_status) VALUES (%s, %s, 'accepted')", (reg_id, student_id))
                
                conn.commit()
                return jsonify({
                    "message": "Order created", "type": "paid", "order_id": razorpay_order['id'],
                    "amount": reg_amount, "key": decrypt_data(event['razorpay_key_id'])
                }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
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
                pay_datetime = (datetime.utcnow() + timedelta(hours=5, minutes=30)).isoformat()
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

@registrations_bp.route('/respond-invite', methods=['POST'])
@require_auth(roles=['student'])
def respond_invite(current_user):
    data = request.json
    reg_id = data.get('registration_id')
    action = data.get('action') # 'accepted' or 'rejected'
    student_id = int(current_user['sub'])
    force_clash = data.get('force_clash_acknowledge', False)

    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT rm.invite_status, rm.invite_expires_at, r.event_id, r.status, r.team_name, r.amount_paid, e.start_date, e.end_date
                    FROM registration_members rm
                    JOIN registrations r ON rm.registration_id = r.id
                    JOIN events e ON r.event_id = e.id
                    WHERE rm.registration_id = %s AND rm.student_id = %s
                """, (reg_id, student_id))
                invite = cur.fetchone()
                if not invite: return jsonify({"error": "Invitation not found"}), 404
                if invite['invite_status'] != 'pending': return jsonify({"error": "Invitation already processed"}), 400
                if invite['invite_expires_at'] < datetime.now(): return jsonify({"error": "Invitation expired"}), 400

                if action == 'accepted':
                    clashes = check_event_clashes(cur, [student_id], invite['start_date'], invite['end_date'], current_reg_id=reg_id)
                    if clashes and not force_clash: return jsonify({"error": "Conflict detected", "clashes": clashes}), 409
                    cur.execute("UPDATE registration_members SET invite_status = 'accepted' WHERE registration_id = %s AND student_id = %s", (reg_id, student_id))
                else:
                    cur.execute("UPDATE registration_members SET invite_status = 'rejected' WHERE registration_id = %s AND student_id = %s", (reg_id, student_id))
                    cur.execute("UPDATE registrations SET status = 'cancelled' WHERE id = %s", (reg_id,))

                # Check if all members have accepted
                cur.execute("""
                    SELECT COUNT(*) as total, 
                           SUM(CASE WHEN invite_status = 'accepted' THEN 1 ELSE 0 END) as accepted
                    FROM registration_members WHERE registration_id = %s
                """, (reg_id,))
                stats = cur.fetchone()
                
                if stats['total'] == stats['accepted']:
                    if float(invite['amount_paid']) <= 0:
                        cur.execute("UPDATE registrations SET status = 'approved' WHERE id = %s", (reg_id,))
                        cur.execute("SELECT student_id FROM registration_members WHERE registration_id = %s", (reg_id,))
                        mids = [r['student_id'] for r in cur.fetchall()]
                        finalize_free_registration(cur, reg_id, invite['event_id'], invite['team_name'], mids)
                    else:
                        cur.execute("UPDATE registrations SET status = 'ready_to_pay' WHERE id = %s", (reg_id,))
                
                conn.commit()
                return jsonify({"message": f"Invitation {action} successfully"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@registrations_bp.route('/generate-payment', methods=['POST'])
@require_auth(roles=['student'])
def generate_payment(current_user):
    data = request.json
    reg_id = data.get('registration_id')
    student_id = int(current_user['sub'])
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT r.*, e.razorpay_key_id, e.razorpay_key_secret 
                    FROM registrations r 
                    JOIN events e ON r.event_id = e.id 
                    WHERE r.id = %s AND r.payer_id = %s AND r.status = 'ready_to_pay'
                """, (reg_id, student_id))
                reg = cur.fetchone()
                if not reg: return jsonify({"error": "Registration not ready for payment or unauthorized"}), 400

                client = razorpay.Client(auth=(decrypt_data(reg['razorpay_key_id']), decrypt_data(reg['razorpay_key_secret'])))
                order = client.order.create(dict(amount=int(float(reg['amount_paid']) * 100), currency='INR', receipt=f"team_{reg['event_id']}_{student_id}"))
                cur.execute("UPDATE registrations SET razorpay_order_id = %s, status = 'pending' WHERE id = %s", (order['id'], reg_id))
                conn.commit()
                return jsonify({"order_id": order['id'], "amount": float(reg['amount_paid']), "key": decrypt_data(reg['razorpay_key_id'])}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@registrations_bp.route('/my-registrations', methods=['GET'])
@require_auth(roles=['student'])
def get_my_registrations(current_user):
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                uid = int(current_user['sub'])
                cur.execute("""
                    SELECT DISTINCT r.id as reg_id, r.event_id, r.status, r.amount_paid, r.registered_at, r.team_name, r.razorpay_payment_id, r.edit_count,
                           r.leader_id, r.payer_id, rm_me.invite_status, rm_me.invite_expires_at,
                           e.title, e.start_date, e.end_date, e.min_team_size, e.team_size as max_team_size,
                           h.name as hall_name, c.name as club_name,
                           COALESCE(att.manual_present, FALSE) as manual_present,
                           COALESCE(att.otp_present, FALSE) as otp_present,
                           att.event_otp
                    FROM registrations r
                    JOIN events e ON r.event_id = e.id
                    LEFT JOIN registration_members rm_me ON r.id = rm_me.registration_id AND rm_me.student_id = %s
                    LEFT JOIN halls h ON e.hall_id = h.id
                    LEFT JOIN clubs c ON e.club_id = c.id
                    LEFT JOIN attendance att ON att.event_id = r.event_id AND att.student_id = %s
                    WHERE r.student_id = %s 
                       OR r.id IN (SELECT registration_id FROM registration_members WHERE student_id = %s)
                    ORDER BY r.registered_at DESC
                """, (uid, uid, uid, uid))
                regs = cur.fetchall()
                for r in regs:
                    r['is_leader'] = (int(r['leader_id']) == uid)
                    if r['invite_expires_at']: r['invite_expires_at'] = r['invite_expires_at'].isoformat()
                    if r['start_date']: r['start_date'] = r['start_date'].isoformat()
                    if r['end_date']: r['end_date'] = r['end_date'].isoformat()
                    if r['registered_at']: r['registered_at'] = r['registered_at'].isoformat()
                    
                    cur.execute("""
                        SELECT u.id, u.full_name, u.reg_no, u.gender, rm.invite_status
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
                           e.start_date, e.min_team_size, e.team_size as max_team_size,
                           h.capacity as hall_capacity
                    FROM registrations r
                    JOIN events e ON r.event_id = e.id
                    LEFT JOIN halls h ON e.hall_id = h.id
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

                # 4. Hall Capacity Validation (if adding members)
                if reg['hall_capacity'] and to_add:
                    cur.execute("""
                        SELECT COUNT(rm.student_id) as current_count
                        FROM registration_members rm
                        JOIN registrations r ON rm.registration_id = r.id
                        WHERE r.event_id = %s AND r.status IN ('approved', 'pending')
                    """, (reg['event_id'],))
                    current_count = cur.fetchone()['current_count']
                    
                    spots_left = reg['hall_capacity'] - current_count
                    if spots_left <= 0:
                        return jsonify({"error": "Event full error. The hall capacity has been reached."}), 400
                        
                    if len(to_add) > spots_left:
                        return jsonify({"error": f"Only {spots_left} persons allowed to be added. Cannot add {len(to_add)} members."}), 400

                # 5. PERFORM DATABASE UPDATES
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
