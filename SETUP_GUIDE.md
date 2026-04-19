# 🛠 Setup & Installation Guide

This guide covers the full setup process for CampusHub on **Windows** and **macOS**. 

---

## 📋 Prerequisites
Ensure you have the following installed before starting:
1. **Python 3.12+** ([python.org](https://www.python.org/downloads/))
2. **PostgreSQL 15+** ([postgresapp.com](https://postgresapp.com/) for Mac, or [postgresql.org](https://www.postgresql.org/download/windows/) for Windows)
3. **Google Chrome / Brave / Safari** (Modern browser for dashboard UI)

---

## 🔑 Environment Variables
Create a `.env` file in the project root with the following keys:

```env
# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/cems

# Authentication Securities
JWT_SECRET=your_ultra_secure_secret_key
JWT_ALGORITHM=HS256

# Payment Gateway (Razorpay)
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_key_secret

# Email Service (SMTP)
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
```

---

## 🍏 macOS / Linux Setup

1. **Clone the Repository**
   ```bash
   git clone <repo-url>
   cd org/backend
   ```

2. **Initialize Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize Database**
   - Option A: Run the integrated script:
     ```bash
     python3 database_creation.py
     ```
   - Option B: Use the centralized SQL file in your PG GUI:
     `database_full_schema.sql`

5. **Launch System**
   ```bash
   python3 app.py
   ```

---

## 🪟 Windows Setup

1. **Clone the Repository**
   ```cmd
   git clone <repo-url>
   cd org\backend
   ```

2. **Initialize Virtual Environment**
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```cmd
   pip install -r requirements.txt
   ```

4. **Initialize Database**
   ```cmd
   python database_creation.py
   ```

5. **Launch System**
   ```cmd
   python app.py
   ```

---

## 🏗 Vercel Deployment Checklist

If you are deploying to **Vercel**:
1. Connect your GitHub repository to Vercel.
2. Set the **Root Directory** as `/`.
3. Add all your `.env` variables in the Vercel Dashboard (Project Settings > Environment Variables).
4. Vercel will automatically use the `requirements.txt` to build your environment.

---

## 🛑 Common Troubleshooting

- **500 Error on Export**: Ensure `openpyxl` is installed and the database columns `description` and `registered_at` exist.
- **Port 5000 Collision (Mac)**: CampusHub is configured to run on **Port 5005** by default to avoid AirPlay conflicts on macOS Sequoia/Sonoma.
- **Razorpay Sandbox**: Ensure you are using "Test Keys" if you are not in production.

---

### Developed with ❤️ by Antigravity
