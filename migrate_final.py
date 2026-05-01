import sqlite3
import psycopg2
import time

# ========== CONFIGURAÇÕES ==========
SQLITE_FILE = "database/bot_smm.db"   # arquivo local do seu bot
POSTGRES_URL = "postgresql://postgres:qyVLjqOxdGQBbBGTaHMrQvuFszRjXaNy@switchyard.proxy.rlwy.net:16394/railway"   # 🟡 COLE A URL AQUI
# ===================================

print("🔌 Conectando ao SQLite local...")
sqlite_conn = sqlite3.connect(SQLITE_FILE)
sqlite_cursor = sqlite_conn.cursor()

print("🐘 Conectando ao PostgreSQL remoto...")
try:
    pg_conn = psycopg2.connect(POSTGRES_URL, connect_timeout=60, keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=2)
    pg_conn.autocommit = False
    pg_cursor = pg_conn.cursor()
except Exception as e:
    print(f"❌ Erro ao conectar no PostgreSQL: {e}")
    exit(1)

# Limpa e recria schema (apaga tudo)
pg_cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
pg_cursor.execute("CREATE SCHEMA public")
pg_conn.commit()

# Obtém tabelas do SQLite
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = sqlite_cursor.fetchall()

for (table_name,) in tables:
    print(f"\n📦 Migrando tabela: {table_name}")
    # Recupera colunas
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    cols = sqlite_cursor.fetchall()
    col_names = [c[1] for c in cols]
    # Cria tabela no PostgreSQL (todos os campos como TEXT para evitar incompatibilidades)
    col_defs = [f"{name} TEXT" for name in col_names]
    create_sql = f"CREATE TABLE {table_name} ({', '.join(col_defs)})"
    pg_cursor.execute(create_sql)
    pg_conn.commit()

    # Insere dados em lotes pequenos (200 registros por vez)
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    batch = []
    total = 0
    batch_size = 200
    for row in sqlite_cursor:
        batch.append(row)
        if len(batch) >= batch_size:
            placeholders = ','.join(['%s'] * len(col_names))
            insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
            try:
                pg_cursor.executemany(insert_sql, batch)
                pg_conn.commit()
                total += len(batch)
                print(f"   → {total} registros inseridos...", end='\r')
                batch = []
            except Exception as e:
                print(f"\n   ❌ Erro no batch: {e}. Tentando novamente...")
                time.sleep(2)
                pg_cursor.executemany(insert_sql, batch)
                pg_conn.commit()
                total += len(batch)
                batch = []

    if batch:
        placeholders = ','.join(['%s'] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
        pg_cursor.executemany(insert_sql, batch)
        pg_conn.commit()
        total += len(batch)
    print(f"\n   ✅ {total} registros inseridos em {table_name}.")

print("\n🎉 Migração concluída com sucesso!")
sqlite_conn.close()
pg_conn.close()
