#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
import requests
import os
import sys
import re
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any, Tuple

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "bot_smm.db"

# ------------------------------------------------------------
# FUNÇÕES DE IMPRESSÃO
# ------------------------------------------------------------
def print_section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def print_success(msg: str):
    print(f"✅ {msg}")

def print_error(msg: str):
    print(f"❌ {msg}")

def print_warning(msg: str):
    print(f"⚠️ {msg}")

def print_info(msg: str):
    print(f"📌 {msg}")

# ------------------------------------------------------------
# MAPEAMENTO DE PLATAFORMAS (prioridade pela primeira ocorrência)
# ------------------------------------------------------------
PLATFORM_KEYWORDS: List[Tuple[str, str]] = [
    ("instagram", "Instagram"),
    ("tiktok", "TikTok"),
    ("youtube", "YouTube"),
    ("facebook", "Facebook"),
    ("kwai", "Kwai"),
    ("telegram", "Telegram"),
    ("twitter", "X/Twitter"),
    ("x", "X/Twitter"),
    ("whatsapp", "WhatsApp"),
    ("spotify", "Spotify"),
    ("twitch", "Twitch"),
    ("pinterest", "Pinterest"),
    ("linkedin", "LinkedIn"),
    ("reddit", "Reddit"),
    ("bluesky", "BlueSky"),
    ("threads", "Threads"),
    ("snackvideo", "SnackVideo"),
    ("tidal", "Tidal"),
    ("dribbble", "Dribbble"),
    ("rumble", "Rumble"),
    ("coinmarketcap", "CoinMarketCap"),
    ("google", "Google"),
    ("site", "Site"),
    ("denuncia", "Denúncias"),
    ("tráfego", "Tráfego"),
    ("trafego", "Tráfego"),
    ("kick", "Kick"),
    ("binance", "Binance"),
    ("deezer", "Deezer"),
    ("discord", "Discord"),
    ("snapchat", "Snapchat"),
    ("soundcloud", "SoundCloud"),
    ("topick", "Topick"),
    ("trovo", "Trovo"),
    ("freefire", "FreeFire"),
]

def detect_platform(service_name: str) -> str:
    """Retorna a plataforma mais provável baseada no nome do serviço."""
    name_lower = service_name.lower()
    best_match = "Outros"
    best_index = len(name_lower)
    for keyword, platform in PLATFORM_KEYWORDS:
        idx = name_lower.find(keyword)
        if idx != -1 and idx < best_index:
            best_match = platform
            best_index = idx
    return best_match

def clean_text(text: str) -> str:
    """Remove emojis, símbolos especiais e normaliza espaços."""
    if not text:
        return ""
    # Remove caracteres não ASCII (inclui emojis) - opcional, mas útil
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    # Remove pontuação e setas
    text = re.sub(r'[➡→⭐🌟✨💫🔥]', '', text)
    text = re.sub(r'[^\w\s-]', '', text)
    # Normaliza espaços
    text = ' '.join(text.split())
    return text.strip()

def normalize_category(raw_category: str, platform: str) -> str:
    """Cria uma categoria padronizada no formato 'Plataforma - Tipo'."""
    # Limpa a string
    clean = clean_text(raw_category)
    if not clean:
        clean = "Geral"

    # Remove prefixo da plataforma se já existir
    lower_clean = clean.lower()
    lower_platform = platform.lower()
    if lower_clean.startswith(lower_platform):
        clean = clean[len(platform):].strip()
        if clean.startswith('-'):
            clean = clean[1:].strip()

    # Remove palavras redundantes
    redundant = ["serviços para", "serviços de", "serviço de", "serviço para", "serviços"]
    for word in redundant:
        clean = re.sub(rf'\b{word}\b', '', clean, flags=re.IGNORECASE)
    clean = ' '.join(clean.split())

    if not clean:
        clean = "Geral"

    return f"{platform} - {clean}"

# ------------------------------------------------------------
# BANCO DE DADOS
# ------------------------------------------------------------
def ensure_services_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            service_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            rate REAL NOT NULL,
            min INTEGER DEFAULT 0,
            max INTEGER DEFAULT 999999,
            category TEXT,
            provider INTEGER,
            description TEXT,
            PRIMARY KEY (service_id, provider)
        )
    """)
    cursor.execute("PRAGMA table_info(services)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'description' not in columns:
        print_info("Adicionando coluna 'description'...")
        cursor.execute("ALTER TABLE services ADD COLUMN description TEXT")

def migrate_users_table(cursor):
    print_section("MIGRAÇÃO DA TABELA USERS")
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'affiliate_balance_cents' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance_cents INTEGER DEFAULT 0")
    if 'main_balance_cents' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN main_balance_cents INTEGER DEFAULT 0")
    if 'affiliate_balance' in columns:
        cursor.execute("UPDATE users SET affiliate_balance_cents = CAST(ROUND(COALESCE(affiliate_balance,0)*100) AS INTEGER)")
    if 'balance' in columns:
        cursor.execute("UPDATE users SET main_balance_cents = CAST(ROUND(COALESCE(balance,0)*100) AS INTEGER)")
    cursor.execute("UPDATE users SET affiliate_balance_cents = 0 WHERE affiliate_balance_cents IS NULL")
    cursor.execute("UPDATE users SET main_balance_cents = 0 WHERE main_balance_cents IS NULL")
    print_success("Tabela users migrada!")

def fetch_services(url: str, key: str, provider_id: int) -> List[Dict[str, Any]]:
    print_info(f"Buscando Fornecedor {provider_id}...")
    if not url or not key:
        print_warning(f"Fornecedor {provider_id} sem URL/KEY")
        return []
    try:
        r = requests.post(url, data={'key': key, 'action': 'services'}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                print_success(f"Recebidos {len(data)} serviços")
                return data
            else:
                print_warning("Resposta não é lista")
        else:
            print_error(f"HTTP {r.status_code}")
    except Exception as e:
        print_error(f"Erro: {e}")
    return []

def extract_field(service: Dict, field_names: List[str], default=None):
    for name in field_names:
        if name in service and service[name] is not None:
            return service[name]
    return default

def extract_description(service: Dict, name: str, category: str) -> str:
    desc = extract_field(service, ['description', 'desc', 'Description', 'Desc', 'details', 'note', 'observacao'])
    if desc and isinstance(desc, str) and desc.strip():
        return desc.strip()
    return f"📢 Serviço: {name}\n📂 Categoria: {category}\n✅ Entrega rápida e qualidade garantida."

def update_services(cursor):
    print_section("ATUALIZAÇÃO DE SERVIÇOS")
    ensure_services_table(cursor)

    # Margem e promo
    cursor.execute("SELECT value FROM settings WHERE key='margem'")
    row = cursor.fetchone()
    margem = float(row[0]) if row else 1.0
    cursor.execute("SELECT value FROM settings WHERE key='promo'")
    row = cursor.fetchone()
    promo = float(row[0]) if row else 0.0
    print_info(f"Margem: {margem}x | Promo: {promo*100}%")

    cursor.execute("DELETE FROM services")
    fornecedores = []
# Só adiciona fornecedor se AMBAS as variáveis existirem e não forem vazias
        url1 = os.getenv("SMM_API_URL_1")
        key1 = os.getenv("SMM_API_KEY_1")
    if url1 and key1:
    fornecedores.append((1, url1, key1))

        url2 = os.getenv("SMM_API_URL_2")
        key2 = os.getenv("SMM_API_KEY_2")
    if url2 and key2:
    fornecedores.append((2, url2, key2))

    total = 0
    desc_count = 0
    for prov_id, url, key in fornecedores:
        if not url or not key:
            continue
        servicos = fetch_services(url, key, prov_id)
        if not servicos:
            continue
        for s in servicos:
            try:
                sid = extract_field(s, ['service', 'id'])
                name = extract_field(s, ['name', 'title'])
                rate_str = extract_field(s, ['rate', 'price'])
                min_q = extract_field(s, ['min', 'min_amount'], 0)
                max_q = extract_field(s, ['max', 'max_amount'], 999999)
                raw_cat = extract_field(s, ['category', 'categoria'], 'Outros')

                if not sid or not name:
                    continue
                rate = float(rate_str) if rate_str else 0.0
                if rate <= 0:
                    continue

                # NOVA LÓGICA DE CATEGORIZAÇÃO
                platform = detect_platform(name)
                cat = normalize_category(raw_cat, platform)

                price = round((rate * margem) * (1 - promo), 2)
                min_q = int(min_q) if min_q else 0
                max_q = int(max_q) if max_q else 999999
                description = extract_description(s, name, cat)
                if description and "descrição padrão" not in description.lower():
                    desc_count += 1

                cursor.execute("""
                    INSERT OR REPLACE INTO services
                    (service_id, name, rate, min, max, category, provider, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (sid, name, price, min_q, max_q, cat, prov_id, description))
                total += 1
            except Exception as e:
                print_warning(f"Erro no serviço: {e}")
                continue
    print_success(f"Total inseridos: {total}")
    print_info(f"Serviços com descrição real: {desc_count}")
    if total == 0:
        print_error("NENHUM serviço foi inserido. Verifique as variáveis e a API.")

def main():
    print_section("LIKESPLUS - UPDATE")
    if not os.path.exists(DB_PATH):
        print_error(f"Banco não encontrado: {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        migrate_users_table(cur)
        update_services(cur)
        conn.commit()
        print_success("Atualização concluída!")
    except Exception as e:
        print_error(f"Erro fatal: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
