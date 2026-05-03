
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Database credentials from settings.py
DB_HOST = "localhost"
DB_PORT = "5432"
DB_USER = "postgres"
DB_PASSWORD = "garcia2012"
NEW_DB_NAME = "dicom_db"

def create_database():
    try:
        # Connect to the default 'postgres' database
        con = psycopg2.connect(
            dbname="postgres",
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()

        # Check if database already exists
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{NEW_DB_NAME}'")
        exists = cur.fetchone()

        if exists:
            print(f"Database '{NEW_DB_NAME}' already exists. Dropping it...")
            # We need to terminate connections before dropping
            cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{NEW_DB_NAME}'")
            cur.execute(f"DROP DATABASE {NEW_DB_NAME}")
            print(f"Database '{NEW_DB_NAME}' dropped.")

        print(f"Creating database '{NEW_DB_NAME}'...")
        cur.execute(f"CREATE DATABASE {NEW_DB_NAME}")
        print(f"Database '{NEW_DB_NAME}' created successfully.")

        cur.close()
        con.close()

    except Exception as e:
        print(f"Error creating database: {e}")

if __name__ == "__main__":
    create_database()
