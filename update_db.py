import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Drop existing UNIQUE(email, role) constraint
    cur.execute("""
        DO $$ 
        DECLARE 
            constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'users'::regclass
            AND contype = 'u'
            AND array_length(conkey, 1) = 2;
            
            IF constraint_name IS NOT NULL THEN
                EXECUTE 'ALTER TABLE users DROP CONSTRAINT ' || constraint_name;
                RAISE NOTICE 'Dropped old constraint: %', constraint_name;
            END IF;
        END $$;
    """)
    
    # Add new constraints (ignore if they already exist)
    cur.execute("""
        DO $$ 
        BEGIN
            BEGIN
                ALTER TABLE users ADD CONSTRAINT unique_email UNIQUE (email);
                RAISE NOTICE 'Added unique_email constraint';
            EXCEPTION WHEN duplicate_table THEN
                -- Do nothing
            WHEN duplicate_object THEN
                -- Do nothing
            END;
            
            BEGIN
                ALTER TABLE users ADD CONSTRAINT unique_reg_no UNIQUE (reg_no);
                RAISE NOTICE 'Added unique_reg_no constraint';
            EXCEPTION WHEN duplicate_table THEN
                -- Do nothing
            WHEN duplicate_object THEN
                -- Do nothing
            END;
        END $$;
    """)
    
    conn.commit()
    print("Database constraints updated successfully on Neon DB!")
    
except Exception as e:
    print(f"Failed: {e}")
finally:
    if 'conn' in locals():
        conn.close()
