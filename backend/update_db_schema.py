from db import DatabaseConnection

def update_schema():
    print("Updating schema...")
    with DatabaseConnection() as conn:
        with conn.cursor() as cur:
            # Drop constraint if exists
            cur.execute("ALTER TABLE registrations DROP CONSTRAINT IF EXISTS registrations_status_check;")
            
            # Add updated constraint
            cur.execute("ALTER TABLE registrations ADD CONSTRAINT registrations_status_check CHECK (status IN ('pending', 'approved', 'rejected', 'waiting_friends', 'ready_to_pay', 'cancelled'));")
            
            # Add columns to registration_members if they don't exist
            cur.execute("""
                ALTER TABLE registration_members 
                ADD COLUMN IF NOT EXISTS invite_status VARCHAR(20) DEFAULT 'accepted';
            """)
            
            cur.execute("""
                ALTER TABLE registration_members 
                ADD COLUMN IF NOT EXISTS invite_expires_at TIMESTAMP;
            """)
            
        conn.commit()
    print("Schema updated successfully!")

if __name__ == '__main__':
    update_schema()
