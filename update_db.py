#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script robusto de atualização do banco de dados do LikesPlus.
- Migra a tabela users para centavos
- Atualiza a tabela services a partir das APIs dos fornecedores
- Captura descrições de forma inteligente
"""

import sqlite3
import requests
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "bot_smm.db"

# ------------------------------------------------------------
# CONFIGURAÇÃO DE LOGS
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
# 1. CRIAÇÃO/VERIFICAÇÃO DA TABELA SERVICES
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
        print_info("Adicionando coluna 'description' à tabela services...")
        cursor.execute("ALTER TABLE services ADD COLUMN description TEXT")

# ------------------------------------------------------------
# 2. MIGRAÇÃO DA TABELA USERS (centavos)
# ------------------------------------------------------------
def migrate_users_table(cursor):
    print_section("MIGRAÇÃO DA TABELA USERS")
    print_info("Verificando estrutura da tabela users...")
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'affiliate_balance_cents' not in columns:
        print_info("➕ Adicionando coluna affiliate_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance_cents INTEGER DEFAULT 0")
    if 'main_balance_cents' not in columns:
        print_info("➕ Adicionando coluna main_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN main_balance_cents INTEGER DEFAULT 0")

    if 'affiliate_balance' in columns:
        print_info("🔄 Migrando affiliate_balance (FLOAT) para affiliate_balance_cents...")
        cursor.execute("""
            UPDATE users
            SET affiliate_balance_cents = CAST(ROUND(COALESCE(affiliate_balance, 0) * 100) AS INTEGER)
            WHERE affiliate_balance IS NOT NULL
        """)
    if 'balance' in columns:
        print_info("🔄 Migrando balance (FLOAT) para main_balance_cents...")
        cursor.execute("""
            UPDATE users
            SET main_balance_cents = CAST(ROUND(COALESCE(balance, 0) * 100) AS INTEGER)
            WHERE balance IS NOT NULL
        """)

    cursor.execute("UPDATE users SET affiliate_balance_cents = 0 WHERE affiliate_balance_cents IS NULL")
    cursor.execute("UPDATE users SET main_balance_cents = 0 WHERE main_balance_cents IS NULL")
    print_success("Tabela users migrada com sucesso!")

# ------------------------------------------------------------
# 3. FUNÇÕES DE BUSCA E EXTRAÇÃO
# ------------------------------------------------------------
def fetch_services(url: str, key: str, provider_id: int) -> List[Dict[str, Any]]:
    print_info(f"Buscando serviços do Fornecedor {provider_id}...")
    if not url or not key:
        print_warning(f"Fornecedor {provider_id} sem URL ou KEY. Pulando.")
        return []
    try:
        response = requests.post(url, data={'key': key, 'action': 'services'}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                print_success(f"Fornecedor {provider_id}: {len(data)} serviços recebidos.")
                return data
            else:
                print_warning(f"Resposta não é uma lista (tipo: {type(data)}).")
                return []
        else:
            print_error(f"HTTP {response.status_code}")
            return []
    except Exception as e:
        print_error(f"Erro: {e}")
        return []

def extract_field(service: Dict, field_names: List[str], default=None):
    for name in field_names:
        if name in service and service[name] is not None:
            return service[name]
    return default

def extract_description(service: Dict) -> str:
    """Tenta extrair descrição de múltiplos campos possíveis."""
    desc = extract_field(service, ['description', 'desc', 'Description', 'Desc', 'details', 'note', 'observacao', 'Observacao'])
    if desc:
        return str(desc).strip()
    # Se não achou, tenta concatenar campos que podem conter informações úteis
    extra = extract_field(service, ['comments', 'notes', 'info'])
    if extra:
        return f"Informações adicionais: {extra}"
    return ""

# ------------------------------------------------------------
# 4. ATUALIZAÇÃO DE SERVIÇOS
# ------------------------------------------------------------
def update_services(cursor):
    print_section("ATUALIZAÇÃO DA TABELA SERVICES")
    ensure_services_table(cursor)

    # Buscar margem e promo
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
    cursor.execute("SELECT value FROM settings WHERE key = 'margem'")
    row_margem = cursor.fetchone()
    margem = float(row_margem[0]) if row_margem else 1.0
    cursor.execute("SELECT value FROM settings WHERE key = 'promo'")
    row_promo = cursor.fetchone()
    promo = float(row_promo[0]) if row_promo else 0.0
    print_info(f"Margem: {margem}x | Promo: {promo*100}%")

    # Limpa tabela
    cursor.execute("DELETE FROM services")
    print_info("Tabela services limpa.")

    fornecedores = [
        (1, os.getenv("SMM_API_URL_1"), os.getenv("SMM_API_KEY_1")),
        (2, os.getenv("SMM_API_URL_2"), os.getenv("SMM_API_KEY_2")),
    ]

    total_inserido = 0
    categorias = {}
    desc_count = 0

    for prov_id, url, key in fornecedores:
        if not url or not key:
            continue
        servicos = fetch_services(url, key, prov_id)
        if not servicos:
            continue

        for s in servicos:
            try:
                service_id = extract_field(s, ['service', 'id', 'service_id'])
                name = extract_field(s, ['name', 'service_name', 'title'])
                rate_str = extract_field(s, ['rate', 'price', 'preco', 'rate_per_1000'])
                min_qty = extract_field(s, ['min', 'min_amount', 'min_quantity', 'min_order'], 0)
                max_qty = extract_field(s, ['max', 'max_amount', 'max_quantity', 'max_order'], 999999)
                category = extract_field(s, ['category', 'categoria', 'cat', 'type'], 'Outros')
                description = extract_description(s)

                if not service_id or not name:
                    continue
                try:
                    preco_base = float(rate_str) if rate_str is not None else 0.0
                except:
                    continue
                if preco_base <= 0:
                    continue

                preco_venda = round((preco_base * margem) * (1 - promo), 2)
                try:
                    min_qty = int(min_qty) if min_qty is not None else 0
                    max_qty = int(max_qty) if max_qty is not None else 999999
                except:
                    min_qty, max_qty = 0, 999999

                if not description:
                    description = "Sem descrição disponível."
                else:
                    desc_count += 1

                cursor.execute("""
                    INSERT OR REPLACE INTO services
                    (service_id, name, rate, min, max, category, provider, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (service_id, name, preco_venda, min_qty, max_qty, category, prov_id, description))

                total_inserido += 1
                categorias[category] = categorias.get(category, 0) + 1

            except Exception as e:
                print_warning(f"Erro no serviço {s.get('service', s.get('id', '?'))}: {e}")
                continue

    print_section("RESUMO DA ATUALIZAÇÃO")
    print_success(f"Total de serviços inseridos/atualizados: {total_inserido}")
    print_info(f"Serviços com descrição: {desc_count} (de {total_inserido})")
    if categorias:
        print_info("Categorias encontradas:")
        for cat, qtd in sorted(categorias.items(), key=lambda x: x[1], reverse=True)[:15]:
            print(f"   • {cat}: {qtd} serviços")
    else:
        print_warning("Nenhuma categoria processada. Verifique os fornecedores.")

# ------------------------------------------------------------
# 5. MAIN
# ------------------------------------------------------------
def main():
    print_section("LIKESPLUS - SCRIPT DE ATUALIZAÇÃO")
    if not os.path.exists(DB_PATH):
        print_error(f"Banco não encontrado em {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        migrate_users_table(cursor)
        update_services(cursor)
        conn.commit()
        print_section("FIM")
        print_success("Atualização concluída com sucesso!")
    except Exception as e:
        print_error(f"Erro fatal: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
