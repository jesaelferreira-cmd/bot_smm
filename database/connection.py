import sqlite3
import os
from pathlib import Path

# Caminho absoluto para o banco no Termux
DB_PATH = Path.home() / "bot_smm" / "database" / "bot_smm.db"

def get_connection():
    """Retorna conexão com o banco SQLite"""
    # Cria diretório se não existir
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Inicializa as tabelas"""
    with get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                category TEXT,
                min_quantity INTEGER,
                max_quantity INTEGER
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_id TEXT,
                link TEXT,
                quantity INTEGER,
                status TEXT DEFAULT 'pending',
                external_order_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
