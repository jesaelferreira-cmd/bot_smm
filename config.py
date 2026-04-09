import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")


# Diretório base do bot
BASE_DIR = Path.home() / "bot_smm"

# Caminho do banco
DB_PATH = BASE_DIR / "database" / "bot_smm.db"

# Caminho dos logs
LOG_PATH = BASE_DIR / "logs" / "bot.log"

# Fornecedor 1
SMM_API_URL_1 = os.getenv("SMM_API_URL_1")
SMM_API_KEY_1 = os.getenv("SMM_API_KEY_1")

# Fornecedor 2
SMM_API_URL_2 = os.getenv("SMM_API_URL_2")
SMM_API_KEY_2 = os.getenv("SMM_API_KEY_2")

#Mercado pago
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) # Converte para int para facilitar a comparação

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID
