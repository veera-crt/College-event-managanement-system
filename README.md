# CampusHub 🎓
### The Ultimate College Event Management & Intelligence System

CampusHub is a state-of-the-art, full-stack event management platform designed specifically for collegiate ecosystems. It streamlines everything from event proposal and multi-sheet hall booking to 2FA attendance verification and automated reward distribution.

 🚀 Visionary Features

 1. **Intelligence Reports & Dossiers**
Generate professional, data-rich Excel reports (`.xlsx`) with a single click. Every dossier includes:
- **Event Intel**: Venue details, organizer logs, and financial summaries.
* **Participant Registrar**: Comprehensive rosters including **Manual Presence** vs. **OTP Verification** metrics.

 2. **Bulletproof 2FA Attendance**
Prevent proxy attendance with our dual-verification protocol:
- **Phase 1**: Manual verification by event volunteers.
* **Phase 2**: Direct student OTP verification via a unique event-level 10-digit code.
 3. **Smart Certificate Distribution**
Automated "Zero-Storage" reward system:
- Certificates are dynamically linked from Google Drive based on verified attendance.
- Pre-calculated "Redirect Logic" ensures zero lag when students download their honors.

 4. **Financial Mastery**
Full integration with **Razorpay** for paid events:
- Secure payment gateways.
- Automated invoice generation and tracking.
- Club-specific payment keys for isolated financial management.

---

🛠 Tech Stack

- **Backend**: Python 3.12+ / Flask (RESTful Architecture)
- **Database**: PostgreSQL (Structured Relational Integrity)
- **Security**: JWT (Session Management) & Argon2/Bcrypt (Hashing)
- **UI/UX**: HTML5, CSS (Tailwind Engine), Vanilla JavaScript
- **Deployment**: Optimized for Vercel / Production WSGI

---

## 📂 Project Structure & Module Map

 **Backend Architecture**
*   **Authentication Hub**: `signup.py`, `signin.py`, `otp.py`, `forgot_password.py`.
*   **Role-Based Portals**: `admin.py`, `events.py` (Organizer), `registrations.py` (Student).
*   **Intelligence & Rewards**: `certificates.py`, `attendance.py`, `culturals.py`.
*   **Utilities**: `invoice_generator.py`, `gsheets_bot.py`, `security_utils.py`.

 **Frontend Map**
*   **Public Access**: `index.html`, `sign-in.html`, `sign-up.html`, `recover.html`.
*   **Dashboards**: `admin.html`, `organizer.html`, `student.html` (Located in `frontend/dashboard/`).

---

📜 Documentation
For detailed installation and configuration steps, please refer to the **[SETUP_GUIDE.md](SETUP_GUIDE.md)**.

---


