import time
import psycopg2
import os

DATABASE_URL = os.getenv("DATABASE_URL")

while True:
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        print("PostgreSQL is ready!")
        break
    except psycopg2.OperationalError:
        print("Waiting for PostgreSQL...")
        time.sleep(2)