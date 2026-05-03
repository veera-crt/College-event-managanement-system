from db import DatabaseConnection

def migrate():
    print("Adding payment_initiated_at columns...")
    with DatabaseConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_initiated_at TIMESTAMP;")
            cur.execute("ALTER TABLE cultural_bookings ADD COLUMN IF NOT EXISTS payment_initiated_at TIMESTAMP;")
            conn.commit()
    print("Migration complete!")

if __name__ == '__main__':
    migrate()
