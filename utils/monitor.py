import requests
import sqlite3
import time
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2

PROVIDERS = [
    {"id": 1, "url": SMM_API_URL_1, "key": SMM_API_KEY_1},
    {"id": 2, "url": SMM_API_URL_2, "key": SMM_API_KEY_2}
]

def check_providers():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for p in PROVIDERS:
        try:
            # Tenta buscar o saldo (chamada rápida e barata)
            response = requests.post(p['url'], data={'key': p['key'], 'action': 'balance'}, timeout=15)
            
            # Se o site deles estiver com erro de SQL ou Fora do Ar (Status 500+)
            if response.status_code >= 400 or "SQLSTATE" in response.text:
                new_status = "OFFLINE"
            else:
                new_status = "ONLINE"
                
        except:
            new_status = "OFFLINE"

        cursor.execute("UPDATE providers_status SET status = ?, last_check = DATETIME('now') WHERE id = ?", (new_status, p['id']))
        print(f"📡 Fornecedor {p['id']}: {new_status}")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    while True:
        check_providers()
        time.sleep(300) # Verifica a cada 5 minutos

