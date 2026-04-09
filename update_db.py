import sqlite3
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar variáveis do .env
load_dotenv()

# Caminhos
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "bot_smm.db"

# ------------------------------------------------------------
# 1. FUNÇÕES DE MIGRAÇÃO DA TABELA USERS (centavos)
# ------------------------------------------------------------
def migrate_users_table(cursor):
    """Adiciona colunas de centavos e migra dados existentes na tabela users"""
    print("🔧 Verificando estrutura da tabela users...")
    
    # Obter colunas existentes
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Adicionar colunas se não existirem
    if 'affiliate_balance_cents' not in columns:
        print("   ➕ Adicionando coluna affiliate_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance_cents INTEGER DEFAULT 0")
    
    if 'main_balance_cents' not in columns:
        print("   ➕ Adicionando coluna main_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN main_balance_cents INTEGER DEFAULT 0")
    
    # Migrar dados das colunas antigas (FLOAT) se existirem
    if 'affiliate_balance' in columns:
        print("   🔄 Migrando affiliate_balance (FLOAT) para affiliate_balance_cents...")
        cursor.execute("""
            UPDATE users 
            SET affiliate_balance_cents = CAST(ROUND(COALESCE(affiliate_balance, 0) * 100) AS INTEGER)
            WHERE affiliate_balance IS NOT NULL
        """)
    
    if 'balance' in columns:
        print("   🔄 Migrando balance (FLOAT) para main_balance_cents...")
        cursor.execute("""
            UPDATE users 
            SET main_balance_cents = CAST(ROUND(COALESCE(balance, 0) * 100) AS INTEGER)
            WHERE balance IS NOT NULL
        """)
    
    # Corrigir possíveis NULLs
    cursor.execute("UPDATE users SET affiliate_balance_cents = 0 WHERE affiliate_balance_cents IS NULL")
    cursor.execute("UPDATE users SET main_balance_cents = 0 WHERE main_balance_cents IS NULL")
    
    print("✅ Tabela users migrada com sucesso!")

# ------------------------------------------------------------
# 2. FUNÇÕES DE ATUALIZAÇÃO DE SERVIÇOS (já existentes)
# ------------------------------------------------------------
def fetch_services(url, key, provider_id):
    print(f"📡 Buscando serviços do Fornecedor {provider_id}...")
    try:
        response = requests.post(url, data={'key': key, 'action': 'services'}, timeout=15)
        if response.status_code == 200:
            return response.json()
        print(f"⚠️ Erro HTTP {response.status_code} no Fornecedor {provider_id}")
    except Exception as e:
        print(f"❌ Falha ao conectar no Fornecedor {provider_id}: {e}")
    return []

def update_services(cursor):
    """Atualiza a tabela services com dados das APIs"""
    print("\n📦 Atualizando tabela services...")
    
    # Buscar margem e promo do banco
    cursor.execute("SELECT value FROM settings WHERE key = 'margem'")
    margem_atual = float(cursor.fetchone()[0])
    cursor.execute("SELECT value FROM settings WHERE key = 'promo'")
    promo_atual = float(cursor.fetchone()[0])
    
    print(f"📈 Margem: {margem_atual}x | Promoção: {promo_atual*100}%")
    
    # Limpa a tabela para atualizar com os novos dados
    cursor.execute("DELETE FROM services")
    
    f1_services = fetch_services(os.getenv("SMM_API_URL_1"), os.getenv("SMM_API_KEY_1"), 1)
    f2_services = fetch_services(os.getenv("SMM_API_URL_2"), os.getenv("SMM_API_KEY_2"), 2)
    
    total_inserido = 0
    for provider_id, services in [(1, f1_services), (2, f2_services)]:
        if not isinstance(services, list):
            continue
        
        for s in services:
            try:
                preco_base = float(s['rate'])
                rate_venda = round((preco_base * margem_atual) * (1 - promo_atual), 2)
                descricao = s.get('description', s.get('desc', 'Sem descrição disponível.'))
                
                cursor.execute("""
                    INSERT INTO services (service_id, name, rate, min, max, category, provider, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (s['service'], s['name'], rate_venda, s['min'], s['max'], s['category'], provider_id, descricao))
                total_inserido += 1
            except Exception as e:
                continue
    
    print(f"✅ {total_inserido} serviços inseridos/atualizados.")

# ------------------------------------------------------------
# 3. MAIN
# ------------------------------------------------------------
def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Passo 1: Migrar tabela users (centavos)
        migrate_users_table(cursor)
        
        # Passo 2: Atualizar serviços
        update_services(cursor)
        
        # Commit final
        conn.commit()
        print("\n🎉 Atualização concluída com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro durante a atualização: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
