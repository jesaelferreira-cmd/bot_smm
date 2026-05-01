import sqlite3
import psycopg2
import os

# Caminho do SQLite no volume do Railway (ajuste se necessário)
SQLITE_PATH = "/app/database/bot_smm.db"
POSTGRES_URL = os.getenv("DATABASE_URL")

if not POSTGRES_URL:
    raise Exception("DATABASE_URL não encontrada. Defina a variável no serviço.")

print("Conectando SQLite...")
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_cursor = sqlite_conn.cursor()

print("Conectando PostgreSQL...")
pg_conn = psycopg2.connect(POSTGRES_URL, connect_timeout=60)
pg_conn.autocommit = False
pg_cursor = pg_conn.cursor()

# Recriar schema
pg_cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
pg_cursor.execute("CREATE SCHEMA public")
pg_conn.commit()

# Obter tabelas
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = sqlite_cursor.fetchall()

for (table_name,) in tables:
    print(f"\n📦 Migrando {table_name}...")
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    cols = sqlite_cursor.fetchall()
    col_names = [c[1] for c in cols]
    # Tipos genéricos (TEXT) para simplificar
    col_defs = [f"{name} TEXT" for name in col_names]
    pg_cursor.execute(f"CREATE TABLE {table_name} ({', '.join(col_defs)})")
    pg_conn.commit()

    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    batch = []
    total = 0
    batch_size = 2000
    for row in sqlite_cursor:
        batch.append(row)
        if len(batch) >= batch_size:
            placeholders = ','.join(['%s'] * len(col_names))
            pg_cursor.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", batch)
            pg_conn.commit()
            total += len(batch)
            print(f"   → {total} registros inseridos...", end='\r')
            batch = []
    if batch:
        placeholders = ','.join(['%s'] * len(col_names))
        pg_cursor.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", batch)
        pg_conn.commit()
        total += len(batch)
    print(f"\n   ✅ Total: {total} registros.")

print("\n🎉 Migração concluída!")
sqlite_conn.close()
pg_conn.close()
