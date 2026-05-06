import logging
import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

logger = logging.getLogger(__name__)

def get_connection():
    """Retorna uma conexão com o PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error(f"Erro ao conectar ao PostgreSQL: {e}")
        raise

def init_database():
    """Cria as tabelas necessárias se não existirem."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    balance BIGINT DEFAULT 0,              -- centavos
                    affiliate_balance BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
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
            # Adicione outras tabelas conforme necessário
        conn.commit()
        logger.info("Banco de dados inicializado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao inicializar banco: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
