from db import execute_query, logger

def create_tables():
    """Create the necessary database tables for CampusHub."""
    
    # Define table creation queries
    queries = [
        """
        DROP TABLE IF EXISTS attendance CASCADE;
        DROP TABLE IF EXISTS registrations CASCADE;
        DROP TABLE IF EXISTS events CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        DROP TABLE IF EXISTS clubs CASCADE;
        DROP TABLE IF EXISTS halls CASCADE;
        DROP TABLE IF EXISTS refresh_tokens CASCADE;
        DROP TABLE IF EXISTS revoked_tokens CASCADE;
        DROP TABLE IF EXISTS otp_verifications CASCADE;
        """,
        """
        CREATE TABLE IF NOT EXISTS clubs (
            id SERIAL PRIMARY KEY,
            category VARCHAR(100) NOT NULL,
            name VARCHAR(255) UNIQUE NOT NULL,
            razorpay_key_id VARCHAR(255),
            razorpay_key_secret VARCHAR(255),
            master_gsheet_link TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS halls (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            capacity INTEGER NOT NULL,
            description TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(100) NOT NULL,
            email VARCHAR(255) NOT NULL,
            reg_no VARCHAR(50),
            password_hash VARCHAR(255) NOT NULL,
            phone_number TEXT,
            address TEXT,
            dob TEXT,
            role VARCHAR(20) NOT NULL CHECK (role IN ('student', 'organizer', 'admin')),
            account_status VARCHAR(20) DEFAULT 'active' CHECK (account_status IN ('pending', 'active', 'rejected')),
            department TEXT,
            college_email TEXT,
            gender VARCHAR(10),
            organization_name TEXT,
            club_id INTEGER REFERENCES clubs(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, role)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS friends (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            friend_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, friend_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS registration_members (
            id SERIAL PRIMARY KEY,
            registration_id INTEGER REFERENCES registrations(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(registration_id, student_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            start_date TIMESTAMP NOT NULL,
            end_date TIMESTAMP NOT NULL,
            reg_deadline TIMESTAMP NOT NULL,
            reg_amount DECIMAL(10, 2) DEFAULT 0.00,
            min_team_size INTEGER DEFAULT 1,
            team_size INTEGER DEFAULT 1,
            female_mandatory BOOLEAN DEFAULT FALSE,
            poster_url TEXT,
            organizer_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            club_id INTEGER REFERENCES clubs(id) ON DELETE SET NULL,
            status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
            admin_message TEXT,
            approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            event_flow JSONB,
            refreshments JSONB,
            hall_id INTEGER REFERENCES halls(id) ON DELETE SET NULL,
            attendance_code VARCHAR(10),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id SERIAL PRIMARY KEY,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            payment_proof_url TEXT,
            razorpay_order_id VARCHAR(255),
            razorpay_payment_id VARCHAR(255),
            razorpay_signature VARCHAR(255),
            amount_paid DECIMAL(10, 2),
            invoice_url TEXT,
            status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, student_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, student_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(255) UNIQUE NOT NULL,
            device_id VARCHAR(255),
            ip_address VARCHAR(45),
            user_agent TEXT,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti VARCHAR(255) PRIMARY KEY,
            expires_at TIMESTAMP NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS otp_verifications (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(100) NOT NULL,
            otp_code VARCHAR(6) NOT NULL,
            payload TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, role)
        );
        """,
        """
        -- Trigger: Automatically set club_id on event creation based on organizer_id
        CREATE OR REPLACE FUNCTION set_event_club_id()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.club_id IS NULL THEN
                SELECT club_id INTO NEW.club_id FROM users WHERE id = NEW.organizer_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_set_event_club_id ON events;
        CREATE TRIGGER trg_set_event_club_id
        BEFORE INSERT ON events
        FOR EACH ROW
        EXECUTE FUNCTION set_event_club_id();
        """
    ]

    try:
        logger.info("Initializing database creation...")
        for query in queries:
            execute_query(query, fetch=False)
            logger.info("Executed query successfully.")
            
        from db import DatabaseConnection
        with DatabaseConnection() as conn:
            with conn.cursor() as cur:
                # 1. Populate Clubs
                clubs_data = [
                    ('Technical & Research Teams', 'SRMKZILLA'),
                    ('Technical & Research Teams', 'Google Developer Student Club (GDSC)'),
                    ('Technical & Research Teams', 'Next Tech Lab'),
                    ('Technical & Research Teams', 'Data Science Community SRM'),
                    ('Technical & Research Teams', 'IoT Alliance Club'),
                    ('Technical & Research Teams', 'SRM Rudra'),
                    ('Technical & Research Teams', 'Camber Racing'),
                    ('Technical & Research Teams', '4ZE Racing'),
                    ('Technical & Research Teams', 'SRM UAV'),
                    ('Technical & Research Teams', 'Quantum Computing Club'),
                    ('Technical & Research Teams', 'Infi-alpha-Hyperloop'),
                    ('Cultural & Creative Clubs', 'Dance Club'),
                    ('Cultural & Creative Clubs', 'Music Club'),
                    ('Cultural & Creative Clubs', 'Literary Club'),
                    ('Cultural & Creative Clubs', 'Movies and Dramatics Club'),
                    ('Cultural & Creative Clubs', 'Photography Club'),
                    ('Cultural & Creative Clubs', 'Fashion Club'),
                    ('Cultural & Creative Clubs', 'Astrophilia'),
                    ('Cultural & Creative Clubs', 'Fine Arts Club'),
                    ('Professional Chapters & Societies', 'ACM'),
                    ('Professional Chapters & Societies', 'IEEE'),
                    ('Professional Chapters & Societies', 'CSI'),
                    ('Professional Chapters & Societies', 'IEI'),
                    ('Professional Chapters & Societies', 'SAE'),
                    ('Professional Chapters & Societies', 'IET'),
                    ('Social & Special Interest Clubs', 'Rotaract Club of SRM KTR'),
                    ('Social & Special Interest Clubs', 'E-Cell (Entrepreneurship Cell)'),
                    ('Social & Special Interest Clubs', 'The Listening Space'),
                    ('Social & Special Interest Clubs', 'SRM MUN'),
                    ('Social & Special Interest Clubs', 'NSS (National Service Scheme)'),
                    ('Department-Specific Clubs', 'Pie Club'),
                    ('Department-Specific Clubs', 'Tekmedica'),
                    ('Department-Specific Clubs', 'BIS Standards Club'),
                    ('Department-Specific Clubs', 'Finance & Media Clubs'),
                    ('Major Fest Committees', 'Aaruush'),
                    ('Major Fest Committees', 'Milan')
                ]
                cur.executemany("INSERT INTO clubs (category, name) VALUES (%s, %s) ON CONFLICT DO NOTHING;", clubs_data)
                
                # 2. Populate Halls
                halls_data = [
                    ("SRM TP 404 & 405", 120, "Combined large classroom in TP building"),
                    ("SRM GANESAN AUDITORIUM", 500, "Large auditorium for main events"),
                    ("MEDICAL HALL", 200, "Hall near the medical block"),
                    ("BELL LAB 502", 40, "Laboratory/Seminar Room")
                ]
                cur.executemany("INSERT INTO halls (name, capacity, description) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING;", halls_data)
                
                conn.commit()
                
        logger.info("✅ Database fully initialized with automation triggers and seed data!")
    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}")

if __name__ == "__main__":
    create_tables()
