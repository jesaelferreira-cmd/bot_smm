import os
import logging
import psycopg2

logger = logging.getLogger(__name__)

def get_connection():
    """Retorna conexão com PostgreSQL usando DATABASE_URL na nuvem ou fallback local."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            conn = psycopg2.connect(database_url)
            conn.autocommit = False
            logger.info("Conexão estabelecida via DATABASE_URL")
            return conn
        except Exception as e:
            logger.error(f"Falha ao conectar com DATABASE_URL: {e}")
            # Se falhar, não tenta localhost na nuvem; apenas levanta exceção
            raise

    # Fallback local (apenas para desenvolvimento)
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "likesplus")
    user = os.getenv("DB_USER", "u0_a365")
    password = os.getenv("DB_PASS", "")
    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=dbname,
            user=user, password=password
        )
        conn.autocommit = False
        logger.info("Conexão local estabelecida")
        return conn
    except Exception as e:
        logger.error(f"Erro ao conectar localmente: {e}")
        raise

def init_database():
    """Cria as tabelas necessárias se não existirem."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Tabela users
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    balance BIGINT DEFAULT 0,
                    affiliate_balance BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Tabela orders
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    service_id TEXT,
                    quantity INT,
                    link TEXT,
                    price BIGINT DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # (adicione outras tabelas se necessário)
        conn.commit()
        logger.info("Banco de dados inicializado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao inicializar banco: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
