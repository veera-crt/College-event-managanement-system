from flask import Blueprint, request, jsonify
from utils.auth_utils import require_auth
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json

events_bp = Blueprint('events', __name__)

@events_bp.route('/halls', methods=['GET'])
@require_auth(roles=['organizer', 'admin'])
def get_halls(current_user):
    """Fetch the list of all available campus halls."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch Halls
                cur.execute("SELECT id, name, capacity, description FROM halls ORDER BY name ASC")
                halls = cur.fetchall()
                
                # 2. Fetch approved bookings from today onwards
                cur.execute("""
                    SELECT e.id, e.hall_id, e.title, e.start_date, e.end_date, u.organization_name as club_name
                    FROM events e 
                    LEFT JOIN users u ON e.organizer_id = u.id
                    WHERE e.status = 'approved' 
                    AND e.end_date >= NOW()
                    ORDER BY e.start_date ASC
                """)
                bookings = cur.fetchall()
                
                # 3. Associate bookings with halls
                for hall in halls:
                    hall['bookings'] = [
                        {
                            "id": b['id'],
                            "title": b['title'],
                            "club_name": b['club_name'],
                            "start": b['start_date'].isoformat(),
                            "end": b['end_date'].isoformat()
                        } 
                        for b in bookings if b['hall_id'] == hall['id']
                    ]
                
                return jsonify(halls), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@events_bp.route('/create', methods=['POST'])
@require_auth(roles=['organizer'])
def create_event(current_user):
    """Create a new event request from an organizer."""
    data = request.json
    try:
        # Extract fields
        title = data.get('title')
        description = data.get('description')
        hall_id = data.get('hall_id')
        team_size = data.get('team_size')
        min_team_size = data.get('min_team_size', 1)
        female_mandatory = data.get('female_mandatory', False)
        poster_url = data.get('poster_url')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        reg_deadline = data.get('reg_deadline')
        reg_amount = data.get('reg_amount', 0) if data.get('reg_type') == 'paid' else 0
        
        # New sections
        event_flow = data.get('event_flow', [])
        refreshments = data.get('refreshments', [])

        if not all([title, hall_id, start_date, end_date, reg_deadline]):
            return jsonify({"error": "Missing mandatory fields"}), 400

        # Date Validation
        try:
            now = datetime.now()
            dt_start = datetime.fromisoformat(start_date)
            dt_end = datetime.fromisoformat(end_date)
            dt_reg = datetime.fromisoformat(reg_deadline)
            
            if dt_start < now:
                return jsonify({"error": "Start date cannot be in the past"}), 400
            if dt_end <= dt_start:
                return jsonify({"error": "End date must be after start date"}), 400
            if dt_reg >= dt_start:
                return jsonify({"error": "Registration deadline must be before start date"}), 400
            if dt_reg < now:
                return jsonify({"error": "Registration deadline cannot be in the past"}), 400
        except ValueError:
            return jsonify({"error": "Invalid date format"}), 400

        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Use club_id from token, fallback to lookup if needed (rely on trigger as ultimate fallback)
                club_id = current_user.get('club_id')
                
                # 2. Insert the event
                cur.execute("""
                    INSERT INTO events (
                        title, description, hall_id, organizer_id, club_id, 
                        min_team_size, team_size, female_mandatory, poster_url, 
                        start_date, end_date, reg_deadline, reg_amount, status,
                        event_flow, refreshments
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                    RETURNING id
                """, (
                    title, description, hall_id, current_user['sub'], club_id,
                    min_team_size, team_size, female_mandatory, poster_url, 
                    start_date, end_date, reg_deadline, reg_amount,
                    json.dumps(event_flow), json.dumps(refreshments)
                ))
                new_event = cur.fetchone()
                conn.commit()
                return jsonify({"message": "Event request submitted successfully", "event_id": new_event['id']}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@events_bp.route('/my-events', methods=['GET'])
@require_auth(roles=['organizer'])
def get_my_events(current_user):
    """Fetch events created by the logged-in organizer."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch the club_id if not in current_user
                club_id = current_user.get('club_id')
                if not club_id:
                     # Fallback to DB lookup if token is old
                     cur.execute("SELECT club_id FROM users WHERE id = %s", (current_user['sub'],))
                     u = cur.fetchone()
                     club_id = u['club_id'] if u else None
                
                if not club_id:
                     return jsonify([]), 200

                cur.execute("""
                    SELECT e.*, h.name as hall_name, u.full_name as organizer_name, 
                           u.organization_name as club_name, a.full_name as approved_by_name
                    FROM events e 
                    LEFT JOIN halls h ON e.hall_id = h.id
                    LEFT JOIN users u ON e.organizer_id = u.id
                    LEFT JOIN users a ON e.approved_by = a.id
                    WHERE e.club_id = %s
                    ORDER BY e.created_at DESC
                """, (club_id,))
                events = cur.fetchall()

                # For rejected events, suggest alternative halls on the same day
                for event in events:
                    if event['status'] == 'rejected':
                        cur.execute("""
                            SELECT name FROM halls 
                            WHERE id NOT IN (
                                SELECT hall_id FROM events 
                                WHERE status = 'approved'
                                AND (
                                    (start_date <= %s AND end_date >= %s) OR
                                    (start_date <= %s AND end_date >= %s) OR
                                    (start_date >= %s AND end_date <= %s)
                                )
                            )
                        """, (event['start_date'], event['start_date'],
                              event['end_date'], event['end_date'],
                              event['start_date'], event['end_date']))
                        alts = cur.fetchall()
                        event['alternative_halls'] = [a['name'] for a in alts]
                
                return jsonify(events), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@events_bp.route('/update/<int:event_id>', methods=['POST'])
@require_auth(roles=['organizer'])
def update_event(current_user, event_id):
    """Allows organizers to edit a rejected/pending event request."""
    data = request.json
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Security: Ensure they own the event
                cur.execute("SELECT organizer_id, status FROM events WHERE id = %s", (event_id,))
                event = cur.fetchone()
                if not event or str(event['organizer_id']) != str(current_user['sub']):
                    return jsonify({"error": "Unauthorized access"}), 403

                # Extract update fields
                title = data.get('title')
                description = data.get('description')
                hall_id = data.get('hall_id')
                team_size = data.get('team_size')
                min_team_size = data.get('min_team_size', 1)
                female_mandatory = data.get('female_mandatory')
                poster_url = data.get('poster_url')
                start_date = data.get('start_date')
                end_date = data.get('end_date')
                reg_deadline = data.get('reg_deadline')
                reg_amount = data.get('reg_amount', 0) if data.get('reg_type') == 'paid' else 0
                
                # New sections
                event_flow = data.get('event_flow', [])
                refreshments = data.get('refreshments', [])

                # Date Validation
                try:
                    now = datetime.now()
                    dt_start = datetime.fromisoformat(start_date)
                    dt_end = datetime.fromisoformat(end_date)
                    dt_reg = datetime.fromisoformat(reg_deadline)
                    
                    if dt_start < now:
                        return jsonify({"error": "Start date cannot be in the past"}), 400
                    if dt_end <= dt_start:
                        return jsonify({"error": "End date must be after start date"}), 400
                    if dt_reg >= dt_start:
                        return jsonify({"error": "Registration deadline must be before start date"}), 400
                    if dt_reg < now:
                        return jsonify({"error": "Registration deadline cannot be in the past"}), 400
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid date format or missing dates"}), 400

                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Updating event {event_id} with payload: {data}")

                cur.execute("""
                    UPDATE events 
                    SET title = %s, description = %s, hall_id = %s, min_team_size = %s, team_size = %s, 
                        female_mandatory = %s, poster_url = %s, start_date = %s, 
                        end_date = %s, reg_deadline = %s, reg_amount = %s, 
                        status = 'pending', admin_message = NULL,
                        event_flow = %s, refreshments = %s
                    WHERE id = %s
                """, (
                    title, description, hall_id, min_team_size, team_size, female_mandatory,
                    poster_url, start_date, end_date, reg_deadline, reg_amount,
                    json.dumps(event_flow), json.dumps(refreshments), event_id
                ))
                return jsonify({"message": "Event request updated and resubmitted"}), 200
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Event update failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@events_bp.route('/approved', methods=['GET'])
@require_auth(roles=['student', 'organizer', 'admin'])
def get_approved_events(current_user):
    """Fetch all events that have been approved by the admin for students/organizers to see."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT e.*, h.name as hall_name, u.full_name as organizer_name, 
                           u.organization_name as club_name, a.full_name as approved_by_name
                    FROM events e 
                    LEFT JOIN halls h ON e.hall_id = h.id
                    LEFT JOIN users u ON e.organizer_id = u.id
                    LEFT JOIN users a ON e.approved_by = a.id
                    WHERE e.status = 'approved'
                    ORDER BY e.start_date ASC
                """)
                events = cur.fetchall()
                # ISO format dates for JS
                for e in events:
                    if e['start_date']: e['start_date'] = e['start_date'].isoformat()
                    if e['end_date']: e['end_date'] = e['end_date'].isoformat()
                    if e['reg_deadline']: e['reg_deadline'] = e['reg_deadline'].isoformat()
                    if e['created_at']: e['created_at'] = e['created_at'].isoformat()
                return jsonify(events), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
