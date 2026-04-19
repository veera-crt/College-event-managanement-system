import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

def send_otp_email(to_email, otp_code):
    """Sends a professional OTP verification email via Gmail SMTP."""
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        print("❌ Gmail credentials NOT found in environment. Mocking instead.")
        return False
        
    msg = MIMEMultipart()
    msg['From'] = f"CampusHub <{MAIL_USERNAME}>"
    msg['To'] = to_email
    msg['Subject'] = "🔒 CampusHub: Email Verification Code"
    
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: auto; border: 1px solid #ddd; border-radius: 10px; padding: 40px; background-color: #fff;">
            <h1 style="color: #1e3a8a; text-align: center;">Verify Your Email</h1>
            <p>Welcome to CampusHub! To complete your registration, please use the following 6-digit verification code:</p>
            <div style="text-align: center; margin: 30px 0;">
                <span style="font-size: 32px; font-weight: bold; background: #f1f5f9; padding: 15px 30px; border-radius: 8px; border: 2px solid #1e3a8a; color: #1e3a8a; letter-spacing: 5px;">{otp_code}</span>
            </div>
            <p style="color: #64748b; font-size: 14px;">This code will expire in 5 minutes. If you did not request this, please ignore this email.</p>
            <hr style="border: none; border-top: 1px solid #eee; margin-top: 30px;">
            <p style="text-align: center; font-size: 12px; color: #94a3b8;">&copy; 2026 CampusHub Development Team</p>
        </div>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(body, 'html'))
    
    try:
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        server.quit()
        print(f"✅ Successfully sent OTP to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")
        return False

def send_organizer_status_email(to_email, full_name, status, org_name):
    """Sends a notification email when an organizer is approved or rejected."""
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        print("❌ Gmail credentials NOT found. Mocking status email.")
        return False
        
    msg = MIMEMultipart()
    msg['From'] = f"CampusHub <{MAIL_USERNAME}>"
    msg['To'] = to_email
    msg['Subject'] = f"Club Organizer Account Status: {status.title()}"
    
    status_color = "#16a34a" if status == 'active' else "#dc2626"
    status_text = "Approved" if status == 'active' else "Rejected"
    
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: auto; border: 1px solid #ddd; border-radius: 10px; padding: 40px; background-color: #fff;">
            <h1 style="color: #1e3a8a; text-align: center;">Account Status Update</h1>
            <p>Dear {full_name},</p>
            <p>The Administrator for <b>{org_name}</b> has processed your registration request.</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <span style="font-size: 24px; font-weight: bold; color: {status_color}; padding: 10px 20px; border: 2px solid {status_color}; border-radius: 8px;">
                    {status_text}
                </span>
            </div>
            
            <p>{"You can now log in to the Organizer Dashboard and start submitting events." if status == 'active' else "If you have any questions, please contact your Club Head."}</p>
            <hr style="border: none; border-top: 1px solid #eee; margin-top: 30px;">
            <p style="text-align: center; font-size: 12px; color: #94a3b8;">&copy; 2026 CampusHub Development Team</p>
        </div>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(body, 'html'))
    
    try:
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Failed to send status email: {str(e)}")
        return False

def send_friend_request_email(to_email, requester_name):
    """Notify a student they've received a friend request."""
    if not MAIL_USERNAME or not MAIL_PASSWORD: return False
    msg = MIMEMultipart(); msg['From'] = f"CampusHub <{MAIL_USERNAME}>"; msg['To'] = to_email; msg['Subject'] = "🤝 CampusHub: New Friend Request"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: auto; border: 1px solid #ddd; border-radius: 10px; padding: 40px; background-color: #fff;">
            <h1 style="color: #1e3a8a; text-align: center;">New Friend Request</h1>
            <p>Hi there,</p>
            <p><b>{requester_name}</b> has sent you a friend request on CampusHub.</p>
            <p>Once you accept this request, they can add you to their teams for campus events.</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://campushub.edu/sign-in" style="background: #1e3a8a; color: white; padding: 12px 25px; text-decoration: none; border-radius: 8px; font-weight: bold;">Login to Approve</a>
            </div>
            <p style="color: #64748b; font-size: 14px;">If you don't know this person, you can simply ignore this request.</p>
            <hr style="border: none; border-top: 1px solid #eee; margin-top: 30px;">
            <p style="text-align: center; font-size: 12px; color: #94a3b8;">&copy; 2026 CampusHub Development Team</p>
        </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(body, 'html'))
    try:
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT); server.starttls(); server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.sendmail(MAIL_USERNAME, to_email, msg.as_string()); server.quit()
        return True
    except Exception: return False
