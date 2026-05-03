import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote
from datetime import datetime, timedelta
from db import DatabaseConnection
from psycopg2.extras import RealDictCursor

def get_gcal_link(title, start_date, end_date, venue, description):
    """Generates a Google Calendar template link."""
    # Dates must be in UTC for Google Calendar 'Z' format
    # Assuming start_date/end_date are already in UTC or local server time
    fmt = "%Y%m%dT%H%M%SZ"
    s = start_date.strftime(fmt)
    e = end_date.strftime(fmt)
    
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    params = f"&text={quote(title)}&dates={s}/{e}&details={quote(description)}&location={quote(venue)}"
    return base_url + params

def send_reminder_email(recipient_email, student_name, event_name, reminder_type, start_time, venue, gcal_link=None):
    """Sends a formatted reminder email."""
    sender_email = os.getenv("MAIL_USERNAME")
    sender_password = os.getenv("MAIL_PASSWORD")
    if not sender_email or not sender_password:
        print("Reminder Error: SMTP Credentials missing")
        return False

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    
    subjects = {
        'initial': f"Mission Confirmed: {event_name} - Add to Calendar",
        '12h': f"Mission Alert: {event_name} starts in 12 hours!",
        '8h': f"Team Briefing: {event_name} - 8 hours to go!",
        '3h': f"Final Countdown: {event_name} starts in 3 hours!",
        '10m': f"Mission Start: {event_name} - See you at the venue!"
    }
    msg['Subject'] = subjects.get(reminder_type, f"Reminder: {event_name}")

    # Determine message content
    time_str = start_time.strftime("%d %b %Y, %I:%M %p")
    
    if reminder_type == 'initial':
        body_text = f"Hello {student_name}, your mission '{event_name}' is confirmed for {time_str} at {venue}. Click the button below to add it to your Google Calendar."
    elif reminder_type == '12h':
        body_text = f"Hello {student_name}, get ready! '{event_name}' starts in 12 hours ({time_str}) at {venue}."
    elif reminder_type == '8h':
        body_text = f"Hello {student_name}, 8 hours remaining! Be ready with your team for '{event_name}'. Review your plan and ensure everyone is prepared."
    elif reminder_type == '3h':
        body_text = f"Hello {student_name}, the final countdown has begun! 3 hours until '{event_name}'. Get ready to participate and head to {venue} soon."
    elif reminder_type == '10m':
        body_text = f"Hello {student_name}, we hope you have reached {venue}! '{event_name}' starts in 10 minutes. Good luck!"
    else:
        body_text = f"Reminder for your upcoming mission: {event_name} at {time_str}."

    # HTML Email with Button
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
            <div style="background: #1e3a8a; padding: 24px; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 24px;">CAMPUSHUB MISSION CONTROL</h1>
            </div>
            <div style="padding: 24px;">
                <p>Hello <strong>{student_name}</strong>,</p>
                <p>{body_text}</p>
                
                <div style="margin: 30px 0; padding: 20px; background: #f8fafc; border-radius: 8px; border-left: 4px solid #1e3a8a;">
                    <p style="margin: 0; font-size: 14px; font-weight: bold; color: #64748b;">MISSION DETAILS</p>
                    <p style="margin: 10px 0 0 0; font-size: 18px; font-weight: 800; color: #1e293b;">{event_name}</p>
                    <p style="margin: 5px 0 0 0; font-size: 14px; color: #334155;">📍 {venue}</p>
                    <p style="margin: 5px 0 0 0; font-size: 14px; color: #334155;">📅 {time_str}</p>
                </div>

                {f'<div style="text-align: center; margin: 30px 0;"><a href="{gcal_link}" target="_blank" style="background: #1e3a8a; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">📅 Schedule to Google Calendar</a></div>' if gcal_link else ''}
                
                <p style="font-size: 12px; color: #94a3b8; margin-top: 40px; text-align: center; border-top: 1px solid #f1f5f9; pt: 20px;">
                    This is an automated mission update. No response required.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(html_content, 'html'))

    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Reminder Email Failed: {e}")
        return False

def check_and_send_reminders():
    """Checks for upcoming events and sends necessary reminders."""
    try:
        with DatabaseConnection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Ensure the reminders_sent table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS reminders_sent (
                        id SERIAL PRIMARY KEY,
                        registration_id INTEGER REFERENCES registrations(id),
                        student_id INTEGER REFERENCES users(id),
                        reminder_type VARCHAR(20),
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(registration_id, student_id, reminder_type)
                    );
                """)
                conn.commit()

                # Fetch all approved registrations for upcoming events
                # We only care about events starting in the next 13 hours
                # Using IST offset (UTC+5:30) to match application logic
                now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                future_limit = now + timedelta(hours=13)
                
                cur.execute("""
                    SELECT r.id as reg_id, rm.student_id, u.full_name, u.college_email,
                           e.title, e.start_date, e.end_date, h.name as venue
                    FROM registrations r
                    JOIN registration_members rm ON r.id = rm.registration_id
                    JOIN users u ON rm.student_id = u.id
                    JOIN events e ON r.event_id = e.id
                    LEFT JOIN halls h ON e.hall_id = h.id
                    WHERE r.status = 'approved'
                      AND e.start_date > %s
                      AND e.start_date < %s
                """, (now, future_limit))
                
                upcoming = cur.fetchall()
                
                for task in upcoming:
                    start_time = task['start_date']
                    diff = start_time - now
                    hours_to_go = diff.total_seconds() / 3600
                    mins_to_go = diff.total_seconds() / 60

                    # Determine which reminder to send
                    reminder_type = None
                    if 11.8 <= hours_to_go <= 12.2: reminder_type = '12h'
                    elif 7.8 <= hours_to_go <= 8.2: reminder_type = '8h'
                    elif 2.8 <= hours_to_go <= 3.2: reminder_type = '3h'
                    elif 8 <= mins_to_go <= 12: reminder_type = '10m'

                    if reminder_type:
                        # Check if already sent
                        cur.execute("""
                            SELECT id FROM reminders_sent 
                            WHERE registration_id = %s AND student_id = %s AND reminder_type = %s
                        """, (task['reg_id'], task['student_id'], reminder_type))
                        
                        if not cur.fetchone():
                            gcal_link = None
                            if reminder_type == '12h': # Send gcal link in the 12h reminder too just in case
                                gcal_link = get_gcal_link(task['title'], task['start_date'], task['end_date'], task['venue'] or "TBA", f"Join us for {task['title']}")
                            
                            success = send_reminder_email(
                                task['college_email'], task['full_name'], task['title'], 
                                reminder_type, task['start_date'], task['venue'] or "TBA", gcal_link
                            )
                            
                            if success:
                                cur.execute("""
                                    INSERT INTO reminders_sent (registration_id, student_id, reminder_type)
                                    VALUES (%s, %s, %s)
                                """, (task['reg_id'], task['student_id'], reminder_type))
                                conn.commit()
                                print(f"Sent {reminder_type} reminder to {task['full_name']} for {task['title']}")
    except Exception as e:
        print(f"Reminder Cron Job Error: {e}")

if __name__ == "__main__":
    check_and_send_reminders()
