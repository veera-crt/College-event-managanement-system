from db import execute_query, logger

def migrate_missing_columns():
    """Add missing columns to existing tables in Neon database."""
    migrations = [
        # Events Table
        ("ALTER TABLE events ADD COLUMN IF NOT EXISTS attendance_locked BOOLEAN DEFAULT FALSE;", "attendance_locked added to events"),
        
        # Registrations Table
        ("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payer_id INTEGER REFERENCES users(id);", "payer_id added to registrations"),
        ("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS edit_count INTEGER DEFAULT 0;", "edit_count added to registrations"),
        
        # Ensure certificates unique constraint from full schema
        ("ALTER TABLE certificates DROP CONSTRAINT IF EXISTS certificates_event_id_student_id_key;", "Dropped old certificates constraint"),
        ("ALTER TABLE certificates ADD CONSTRAINT certificates_event_id_student_id_key UNIQUE(event_id, student_id);", "Added unique constraint to certificates")
    ]

    logger.info("Starting database migration...")
    for query, msg in migrations:
        try:
            execute_query(query, fetch=False)
            logger.info(f"✅ {msg}")
        except Exception as e:
            logger.error(f"❌ Failed: {msg}. Error: {e}")

if __name__ == "__main__":
    migrate_missing_columns()
