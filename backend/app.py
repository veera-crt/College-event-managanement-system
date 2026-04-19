import os
from flask import Flask, send_from_directory, request
from flask_cors import CORS
from dotenv import load_dotenv

# Ensure secrets are always loaded from the project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=True)

# Import Blueprints
from routes.signup import signup_bp
from routes.otp import otp_bp
from routes.signin import signin_bp
from routes.admin import admin_bp
from routes.profile import profile_bp
from routes.student_profile import student_profile_bp
from routes.admin_profile import admin_profile_bp
from routes.forgot_password import forgot_password_bp
from routes.events import events_bp
from routes.registrations import registrations_bp
from routes.culturals import culturals_bp
from routes.friends import friends_bp
from routes.attendance import attendance_bp
from routes.certificates import certificates_bp

# Setup frontend path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'frontend'))

app = Flask(__name__, static_folder=FRONTEND_DIR, template_folder=FRONTEND_DIR)
CORS(app, supports_credentials=True) # Essential for cookie-based auth

# Initialize Security Utilities
from utils.security_utils import limiter
limiter.init_app(app)

# Register Blueprints
app.register_blueprint(signup_bp, url_prefix='/api/auth')
app.register_blueprint(otp_bp, url_prefix='/api/auth')
app.register_blueprint(signin_bp, url_prefix='/api/auth')
app.register_blueprint(admin_bp, url_prefix='/api/admin')
app.register_blueprint(profile_bp, url_prefix='/api/profile')
app.register_blueprint(student_profile_bp, url_prefix='/api/student/profile')
app.register_blueprint(admin_profile_bp, url_prefix='/api/admin/profile')
app.register_blueprint(forgot_password_bp, url_prefix='/api/recover')
app.register_blueprint(events_bp, url_prefix='/api/events')
app.register_blueprint(registrations_bp, url_prefix='/api/registrations')
app.register_blueprint(culturals_bp, url_prefix='/api/culturals')
app.register_blueprint(friends_bp, url_prefix='/api/friends')
app.register_blueprint(attendance_bp, url_prefix='/api/attendance')
app.register_blueprint(certificates_bp, url_prefix='/api/certificates')

# --- FRONTEND SERVING ROUTES ---

# --- SECURITY & PERFORMANCE HEADERS ---
@app.after_request
def add_security_headers(response):
    """
    Implements Defense-in-Depth headers.
    - XSS protection via CSP
    - Anti-clickjacking via X-Frame-Options
    - MIME-sniffing prevention
    - Cache-control for dynamic content
    """
    # 1. Standard Security Headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    
    # 2. Strict Content Security Policy (Allow Google Fonts, Tailwind CDN, Unsplash, Razorpay, etc)
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' unpkg.com cdn.tailwindcss.com checkout.razorpay.com cdn.razorpay.com cdn.jsdelivr.net cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com unpkg.com; "
        "font-src 'self' fonts.gstatic.com; "
        "img-src 'self' data: images.unsplash.com lh3.googleusercontent.com; "
        "connect-src 'self' unpkg.com lumberjack.razorpay.com;"
        "frame-src 'self' api.razorpay.com checkout.razorpay.com;"
    )
    response.headers['Content-Security-Policy'] = csp
    
    # 3. Disable caching for HTML files to ensure AuthGuard runs (Prevent BFCache session leaks)
    if request.path.endswith('.html') or request.path == '/' or 'dashboard' in request.path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
    return response

@app.route('/')
def index():
    """Serve the root index.html."""
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve arbitrary files from the frontend directory (HTML, CSS, JS)."""
    # If a directory is requested without a filename, try index.html
    if os.path.isdir(os.path.join(FRONTEND_DIR, filename)):
        return send_from_directory(os.path.join(FRONTEND_DIR, filename), 'index.html')
    
    # Otherwise, serve the file directly
    return send_from_directory(FRONTEND_DIR, filename)

@app.route('/api/health', methods=['GET'])
def health_check():
    return {"status": "healthy", "service": "CampusHub API Server"}, 200

if __name__ == '__main__':
    # Force development mode on port 5005 (to avoid macOS AirPlay 5000 conflicts)
    app.run(debug=True, port=5005)
