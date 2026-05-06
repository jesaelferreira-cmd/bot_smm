import sqlite3
import psycopg2
import os
import getpass
from dotenv import load_dotenv

load_dotenv()

# Caminho do SQLite (ajuste se necessário)
DB_PATH = "/data/data/com.termux/files/home/bot_smm/database/bot_smm.db"

PG_URL = os.getenv("DATABASE_URL")
if not PG_URL:
    system_user = getpass.getuser()
    PG_URL = f"postgresql://{system_user}@localhost:5432/likesplus"

TYPE_MAP = {
    "INTEGER": "BIGINT",
    "INT": "BIGINT",
    "TEXT": "TEXT",
    "REAL": "BIGINT",       # Real será convertido para centavos (multiplicado por 100)
    "FLOAT": "BIGINT",
    "NUMERIC": "BIGINT",
    "BLOB": "BYTEA",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
}

# Colunas que devem ser convertidas de reais para centavos (multiplicar por 100)
# Se houver outras tabelas/colunas, adicione aqui.
MONEY_COLUMNS = {
    "users": ["balance", "affiliate_balance"],
    "orders": ["price"],
}

def is_money_column(table, column):
    return table in MONEY_COLUMNS and column in MONEY_COLUMNS[table]

def get_sqlite_columns(cursor, table):
    """Retorna lista de (nome, tipo, é_pk) para uma tabela do SQLite."""
    cursor.execute(f"PRAGMA table_info({table})")
    cols = []
    for row in cursor.fetchall():
        name = row[1]
        col_type = row[2].upper() if row[2] else "TEXT"
        pk = row[5] != 0
        cols.append((name, col_type, pk))
    return cols

def migrate():
    sql_conn = sqlite3.connect(DB_PATH)
    pg_conn = psycopg2.connect(PG_URL)
    pg_conn.autocommit = True

    sql_cur = sql_conn.cursor()
    pg_cur = pg_conn.cursor()

    sql_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in sql_cur.fetchall()]
    print(f"Tabelas encontradas no SQLite: {tables}")

    for table in tables:
        print(f"\n--- Processando tabela: {table} ---")
        columns = get_sqlite_columns(sql_cur, table)

        if not columns:
            print("  - Tabela sem colunas, pulando.")
            continue

        # Construir definição de colunas para PostgreSQL
        pg_cols = []
        for name, col_type, pk in columns:
            pg_type = TYPE_MAP.get(col_type, "TEXT")
            # Se for coluna de dinheiro, forçar BIGINT, mesmo que o tipo original não seja REAL
            if is_money_column(table, name):
                pg_type = "BIGINT"
            pg_cols.append(f"{name} {pg_type}")

        # Chave primária
        pks = [col[0] for col in columns if col[2]]
        if pks:
            pg_cols.append(f"PRIMARY KEY ({', '.join(pks)})")

        create_sql = f"CREATE TABLE {table} (\n  " + ",\n  ".join(pg_cols) + "\n)"
        pg_cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        pg_cur.execute(create_sql)
        print(f"  - Tabela criada no PostgreSQL.")

        # Inserir dados com conversão de centavos
        sql_cur.execute(f"SELECT * FROM {table}")
        rows = sql_cur.fetchall()
        if not rows:
            print("  - Tabela vazia, sem dados para migrar.")
            continue

        col_names = [col[0] for col in columns]
        placeholders = ', '.join(['%s'] * len(col_names))
        insert_sql = f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({placeholders})"

        try:
            for row in rows:
                new_row = list(row)
                for i, col_name in enumerate(col_names):
                    if is_money_column(table, col_name):
                        # Converter real para centavos (arredondando para inteiro)
                        valor_em_reais = row[i] if row[i] is not None else 0.0
                        centavos = int(round(float(valor_em_reais) * 100))
                        new_row[i] = centavos
                pg_cur.execute(insert_sql, tuple(new_row))
            pg_conn.commit()
            print(f"  - {len(rows)} registros migrados (com conversão para centavos).")
        except Exception as e:
            print(f"  - Erro ao inserir dados: {e}")
            pg_conn.rollback()

    sql_cur.close()
    pg_cur.close()
    sql_conn.close()
    pg_conn.close()
    print("\n✅ Migração concluída com valores em centavos!")

if __name__ == "__main__":
    migrate()
