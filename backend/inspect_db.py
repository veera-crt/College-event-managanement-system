from db import DatabaseConnection
from psycopg2.extras import RealDictCursor

def inspect_db():
    print("Inspecting database...")
    with DatabaseConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check registrations status constraint or just columns
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'registrations'
            """)
            print("\nColumns in 'registrations':")
            for row in cur.fetchall():
                print(f" - {row['column_name']} ({row['data_type']})")

            # Check registration_members columns
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'registration_members'
            """)
            print("\nColumns in 'registration_members':")
            for row in cur.fetchall():
                print(f" - {row['column_name']} ({row['data_type']})")
                
            # Check for constraints on registrations.status
            cur.execute("""
                SELECT conname, pg_get_constraintdef(oid) 
                FROM pg_constraint 
                WHERE conrelid = 'registrations'::regclass AND conname = 'registrations_status_check'
            """)
            print("\nConstraint 'registrations_status_check':")
            for row in cur.fetchall():
                print(f" - {row['conname']}: {row['pg_get_constraintdef']}")

if __name__ == '__main__':
    inspect_db()
