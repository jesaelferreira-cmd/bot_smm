import sqlite3
import psycopg2
import os, getpass
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "/data/data/com.termux/files/home/bot_smm/database/bot_smm.db"
PG_URL = os.getenv("DATABASE_URL")
if not PG_URL:
    system_user = getpass.getuser()
    PG_URL = f"postgresql://{system_user}@localhost:5432/likesplus"

sql_conn = sqlite3.connect(DB_PATH)
pg_conn = psycopg2.connect(PG_URL)
pg_conn.autocommit = True

sql_cur = sql_conn.cursor()
pg_cur = pg_conn.cursor()

# Copiar colunas (apenas services)
sql_cur.execute("PRAGMA table_info(services)")
cols = [(r[1], r[2]) for r in sql_cur.fetchall()]  # (nome, tipo)
col_names = [c[0] for c in cols]
# Mapear todos para %s placeholders
placeholders = ', '.join(['%s'] * len(col_names))

# Inserir dados SEM conversão de centavos (rate já é reais)
sql_cur.execute("SELECT * FROM services")
rows = sql_cur.fetchall()
for row in rows:
    pg_cur.execute(f"INSERT INTO services ({', '.join(col_names)}) VALUES ({placeholders})", row)

print(f"{len(rows)} serviços migrados com rate em reais.")
pg_conn.commit()
sql_cur.close()
pg_cur.close()
sql_conn.close()
pg_conn.close()
