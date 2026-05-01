import sqlite3
import psycopg2
import time

# ========== CONFIGURAÇÕES (EDIÇÃO OBRIGATÓRIA) ==========
SQLITE_DB = "database/bot_smm.db"
POSTGRES_URL = "postgresql://postgres:qyVLjqOxdGQBbBGTaHMrQvuFszRjXaNy@switchyard.proxy.rlwy.net:16394/railway"   # 🟡 COLE A URL COMPLETA AQUI
# =======================================================

print("🔌 Conectando ao SQLite...")
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_cursor = sqlite_conn.cursor()

print("🐘 Conectando ao PostgreSQL...")
# Aumenta o timeout de conexão para 60 segundos
pg_conn = psycopg2.connect(POSTGRES_URL, connect_timeout=60)
pg_conn.autocommit = False
pg_cursor = pg_conn.cursor()

# Recriar todo o esquema (apaga todas as tabelas no PostgreSQL)
pg_cursor.execute("DROP SCHEMA public CASCADE")
pg_cursor.execute("CREATE SCHEMA public")
pg_conn.commit()

# Buscar tabelas do SQLite
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = sqlite_cursor.fetchall()

for (table_name,) in tables:
    print(f"\n📦 Migrando tabela: {table_name}")
    # Obter definição das colunas
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    columns = sqlite_cursor.fetchall()
    col_names = [col[1] for col in columns]
    col_defs = [f"{name} TEXT" for name in col_names]   # tipo genérico para evitar erros

    # Criar tabela no PostgreSQL
    pg_cursor.execute(f"CREATE TABLE {table_name} ({', '.join(col_defs)})")
    pg_conn.commit()

    # Inserir dados em lotes (batches) de 500 linhas
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    batch_size = 500
    rows_buffer = []
    inserted_total = 0

    for idx, row in enumerate(sqlite_cursor):
        rows_buffer.append(row)
        if len(rows_buffer) >= batch_size:
            placeholders = ','.join(['%s'] * len(col_names))
            insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})"
            pg_cursor.executemany(insert_sql, rows_buffer)
            pg_conn.commit()
            inserted_total += len(rows_buffer)
            print(f"   → {inserted_total} registros inseridos...")
            rows_buffer = []

    # Inserir o restante
    if rows_buffer:
        placeholders = ','.join(['%s'] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})"
        pg_cursor.executemany(insert_sql, rows_buffer)
        pg_conn.commit()
        inserted_total += len(rows_buffer)

    print(f"   ✅ Total de {inserted_total} registros inseridos em {table_name}.")

print("\n🎉 Migração concluída com sucesso!")
sqlite_conn.close()
pg_conn.close()
