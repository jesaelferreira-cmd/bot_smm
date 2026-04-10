#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script robusto de atualização do banco de dados do LikesPlus.
- Migra a tabela users para centavos
- Atualiza a tabela services a partir das APIs dos fornecedores
- Cria tabelas automaticamente se não existirem
- Suporta diferentes formatos de resposta das APIs
"""

import sqlite3
import requests
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

# Carregar variáveis do .env
load_dotenv()

# Caminhos
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
    """Cria a tabela services se ela não existir, com a estrutura correta."""
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
    # Verificar se a coluna 'description' existe (para versões antigas)
    cursor.execute("PRAGMA table_info(services)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'description' not in columns:
        print_info("Adicionando coluna 'description' à tabela services...")
        cursor.execute("ALTER TABLE services ADD COLUMN description TEXT")

# ------------------------------------------------------------
# 2. FUNÇÕES DE MIGRAÇÃO DA TABELA USERS (centavos)
# ------------------------------------------------------------
def migrate_users_table(cursor):
    """Adiciona colunas de centavos e migra dados existentes na tabela users"""
    print_section("MIGRAÇÃO DA TABELA USERS")
    print_info("Verificando estrutura da tabela users...")

    # Obter colunas existentes
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]

    # Adicionar colunas se não existirem
    if 'affiliate_balance_cents' not in columns:
        print_info("➕ Adicionando coluna affiliate_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance_cents INTEGER DEFAULT 0")

    if 'main_balance_cents' not in columns:
        print_info("➕ Adicionando coluna main_balance_cents...")
        cursor.execute("ALTER TABLE users ADD COLUMN main_balance_cents INTEGER DEFAULT 0")

    # Migrar dados das colunas antigas (FLOAT) se existirem
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

    # Corrigir possíveis NULLs
    cursor.execute("UPDATE users SET affiliate_balance_cents = 0 WHERE affiliate_balance_cents IS NULL")
    cursor.execute("UPDATE users SET main_balance_cents = 0 WHERE main_balance_cents IS NULL")

    print_success("Tabela users migrada com sucesso!")

# ------------------------------------------------------------
# 3. FUNÇÕES DE ATUALIZAÇÃO DE SERVIÇOS (ROBUSTA)
# ------------------------------------------------------------
def fetch_services(url: str, key: str, provider_id: int) -> List[Dict[str, Any]]:
    """Busca serviços da API do fornecedor com tratamento de erros."""
    print_info(f"Buscando serviços do Fornecedor {provider_id}...")
    if not url or not key:
        print_warning(f"Fornecedor {provider_id} sem URL ou KEY configurados. Pulando.")
        return []

    try:
        response = requests.post(url, data={'key': key, 'action': 'services'}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                print_success(f"Fornecedor {provider_id}: {len(data)} serviços recebidos.")
                return data
            else:
                print_warning(f"Fornecedor {provider_id}: resposta não é uma lista (tipo: {type(data)}).")
                return []
        else:
            print_error(f"Fornecedor {provider_id}: HTTP {response.status_code}")
            return []
    except requests.exceptions.Timeout:
        print_error(f"Fornecedor {provider_id}: timeout (30s).")
        return []
    except Exception as e:
        print_error(f"Fornecedor {provider_id}: erro - {e}")
        return []

def extract_field(service: Dict, field_names: List[str], default=None):
    """Extrai um campo do dicionário, tentando várias chaves alternativas."""
    for name in field_names:
        if name in service and service[name] is not None:
            return service[name]
    return default

def update_services(cursor):
    """Atualiza a tabela services com dados das APIs, usando fallback para diferentes formatos."""
    print_section("ATUALIZAÇÃO DA TABELA SERVICES")

    # Garantir que a tabela services existe
    ensure_services_table(cursor)

    # Buscar margem e promo do banco (com fallback)
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
    cursor.execute("SELECT value FROM settings WHERE key = 'margem'")
    row_margem = cursor.fetchone()
    margem_atual = float(row_margem[0]) if row_margem else 1.0

    cursor.execute("SELECT value FROM settings WHERE key = 'promo'")
    row_promo = cursor.fetchone()
    promo_atual = float(row_promo[0]) if row_promo else 0.0

    print_info(f"Margem: {margem_atual}x | Promoção: {promo_atual*100}%")

    # Limpa a tabela (opcional – se quiser manter histórico, comente esta linha)
    cursor.execute("DELETE FROM services")
    print_info("Tabela services limpa (modo substituição total).")

    # Lista de fornecedores (adicione quantos quiser)
    fornecedores = [
        (1, os.getenv("SMM_API_URL_1"), os.getenv("SMM_API_KEY_1")),
        (2, os.getenv("SMM_API_URL_2"), os.getenv("SMM_API_KEY_2")),
    ]

    total_inserido = 0
    categorias = {}
    erros = []

    for provider_id, url, key in fornecedores:
        if not url or not key:
            print_warning(f"Fornecedor {provider_id} ignorado (variáveis ausentes).")
            continue

        servicos = fetch_services(url, key, provider_id)
        if not servicos:
            continue

        for idx, s in enumerate(servicos):
            try:
                # Extrai campos com fallback
                service_id = extract_field(s, ['service', 'id', 'service_id'])
                name = extract_field(s, ['name', 'service_name', 'title'])
                rate_str = extract_field(s, ['rate', 'price', 'preco', 'rate_per_1000'])
                min_qty = extract_field(s, ['min', 'min_amount', 'min_quantity', 'min_order'], 0)
                max_qty = extract_field(s, ['max', 'max_amount', 'max_quantity', 'max_order'], 999999)
                category = extract_field(s, ['category', 'categoria', 'cat', 'type'], 'Outros')
                description = extract_field(s, ['description', 'desc', 'details'], '')

                # Validações
                if service_id is None:
                    erros.append(f"Prov{provider_id} serviço #{idx}: sem ID – ignorado")
                    continue
                if not name:
                    erros.append(f"Prov{provider_id} ID {service_id}: sem nome – ignorado")
                    continue
                try:
                    preco_base = float(rate_str) if rate_str is not None else 0.0
                except (ValueError, TypeError):
                    erros.append(f"Prov{provider_id} ID {service_id}: rate inválido ('{rate_str}') – ignorado")
                    continue

                if preco_base <= 0:
                    # Não insere serviço com preço zero ou negativo
                    continue

                # Calcula preço de venda
                preco_venda = round((preco_base * margem_atual) * (1 - promo_atual), 2)

                # Converte min/max para inteiro
                try:
                    min_qty = int(min_qty) if min_qty is not None else 0
                    max_qty = int(max_qty) if max_qty is not None else 999999
                except (ValueError, TypeError):
                    min_qty = 0
                    max_qty = 999999

                # Insere no banco
                cursor.execute("""
                    INSERT OR REPLACE INTO services
                    (service_id, name, rate, min, max, category, provider, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (service_id, name, preco_venda, min_qty, max_qty, category, provider_id, description))

                total_inserido += 1
                categorias[category] = categorias.get(category, 0) + 1

            except Exception as e:
                erros.append(f"Prov{provider_id} ID {s.get('service', s.get('id', '?'))}: {e}")
                continue

    # Relatório final
    print_section("RESUMO DA ATUALIZAÇÃO")
    print_success(f"Total de serviços inseridos/atualizados: {total_inserido}")

    if categorias:
        print_info("Categorias encontradas:")
        for cat, qtd in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
            print(f"   • {cat}: {qtd} serviços")
    else:
        print_warning("Nenhuma categoria foi processada. Verifique a conexão com os fornecedores.")

    if erros:
        print_warning(f"Ocorreram {len(erros)} erros durante o processamento (últimos 10):")
        for err in erros[-10:]:
            print(f"   ⚠️ {err}")

# ------------------------------------------------------------
# 4. MAIN
# ------------------------------------------------------------
def main():
    print_section("LIKESPLUS - SCRIPT DE ATUALIZAÇÃO DO BANCO DE DADOS")
    if not os.path.exists(DB_PATH):
        print_error(f"Banco de dados não encontrado em: {DB_PATH}")
        print_info("Certifique-se de que o caminho está correto e o arquivo existe.")
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
        print_section("FIM DO PROCESSO")
        print_success("Atualização concluída com sucesso!")

    except Exception as e:
        print_error(f"Erro fatal durante a atualização: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
