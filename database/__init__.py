import sqlite3
import psycopg2
from config import DB_ENGINE, DB_PATH, DB_CONNECTION_STRING

def get_connection():
    if DB_ENGINE == "postgresql":
        return psycopg2.connect(DB_CONNECTION_STRING)
    else:
        return sqlite3.connect(DB_PATH)
