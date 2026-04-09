import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ========== DIRETÓRIO BASE DINÂMICO ==========
# No Railway, o código fica em /app
# No Termux local, __file__ aponta para a pasta do config.py
BASE_DIR = Path(__file__).resolve().parent

# ========== BANCO DE DADOS ==========
DB_PATH = BASE_DIR / "database" / "bot_smm.db"

# ========== LOGS ==========
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)          # cria a pasta se não existir
LOG_PATH = LOG_DIR / "bot.log"

# ========== VARIÁVEIS DO BOT ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ========== FORNECEDORES ==========
SMM_API_URL_1 = os.getenv("SMM_API_URL_1")
SMM_API_KEY_1 = os.getenv("SMM_API_KEY_1")
SMM_API_URL_2 = os.getenv("SMM_API_URL_2")
SMM_API_KEY_2 = os.getenv("SMM_API_KEY_2")

# ========== MERCADO PAGO ==========
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

# ========== ADMIN ==========
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID
