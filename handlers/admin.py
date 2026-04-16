import asyncio
import sqlite3
import requests
import time
import subprocess
import os
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2, ADMIN_ID, is_admin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
START_TIME = time.time()

# =========================================================
# FUNÇÕES AUXILIARES (centavos)
# =========================================================
def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

def get_admin_stats():
    """Retorna estatísticas usando as colunas em centavos"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    try:
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM orders")
        vendas = cursor.fetchone()
        total_vendas = vendas[0] or 0
        faturamento_cents = vendas[1] or 0
        faturamento = cents_to_float(faturamento_cents)
    except:
        try:
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM orders")
            vendas = cursor.fetchone()
            total_vendas = vendas[0] or 0
            faturamento = float(vendas[1] or 0.0)
        except:
            total_vendas, faturamento = 0, 0.0

    conn.close()
    return total_users, total_vendas, faturamento

# =========================================================
# 1. PAINEL ADMIN
# =========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        logger.warning(f"Acesso negado ao painel para {user_id}")
        return

    users, sales, money = get_admin_stats()

    def get_bal(url, key):
        try:
            r = requests.post(url, data={'key': key, 'action': 'balance'}, timeout=5)
            data = r.json()
            return f"{data.get('balance', '0')} {data.get('currency', 'BRL')}"
        except Exception as e:
            logger.error(f"Erro ao obter saldo do fornecedor: {e}")
            return "Offline ❌"

    bal1 = get_bal(SMM_API_URL_1, SMM_API_KEY_1)
    bal2 = get_bal(SMM_API_URL_2, SMM_API_KEY_2)

    uptime_seconds = int(time.time() - START_TIME)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"

    msg = (
        f"👑 **PAINEL ADMINISTRATIVO - LIKESPLUS**\n\n"
        f"⏱ **Uptime:** `{uptime_str}`\n"
        f"👥 **Usuários:** `{users}`\n"
        f"🛒 **Vendas:** `{sales}`\n"
        f"💰 **Faturamento:** `R$ {money:.2f}`\n\n"
        f"🏦 **Saldo Fornecedor 1:** `{bal1}`\n"
        f"🏦 **Saldo Fornecedor 2:** `{bal2}`\n\n"
        f"⚙️ **Comandos Rápidos:**\n"
        f"📈 `/margem 1.5` (Define 50% de lucro)\n"
        f"📢 `/promo 0.20` (Dá 20% de desconto temporário)\n"
        f"🔄 `/atualizar` (Sincroniza serviços)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# =========================================================
# 2. MARGEM
# =========================================================
async def set_margin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        valor = float(context.args[0])
        if valor <= 0:
            raise ValueError
        context.bot_data['margin'] = valor

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('margem', ?)", (valor,))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"🚀 **Margem alterada para {valor}x.**\nRode `/atualizar` para sincronizar.")
    except:
        await update.message.reply_text("❌ Use: `/margem 2.0` (ex: 2.0 = 100% de lucro)")

# =========================================================
# 3. PROMOÇÃO
# =========================================================
async def set_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        valor = float(context.args[0])
        if not (0 <= valor <= 1):
            raise ValueError
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('promo', ?)", (valor,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎁 Promoção de {valor*100:.0f}% gravada! Rode `/atualizar`.")
    except:
        await update.message.reply_text("❌ Use: `/promo 0.15` (para 15% de desconto)")

# =========================================================
# 4. ATUALIZAR SERVIÇOS (chama update_db.py)
# =========================================================
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text("⏳ Atualizando serviços e verificando banco de dados...")

    try:
        script_path = os.path.join(os.path.dirname(__file__), '..', 'update_db.py')
        result = subprocess.run(["python", script_path], capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            await update.message.reply_text("✅ Banco de dados e serviços atualizados com sucesso!")
            logger.info(f"Update DB output: {result.stdout}")
        else:
            await update.message.reply_text(f"❌ Erro na atualização. Verifique logs.\n{result.stderr[:200]}")
    except Exception as e:
        logger.error(f"Falha ao executar update_db: {e}")
        await update.message.reply_text(f"❌ Erro ao atualizar: {str(e)}")

# =========================================================
# 5. BROADCAST
# =========================================================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return

    text_content = None
    photo_file_id = None
    message = update.message

    if context.args:
        text_content = " ".join(context.args)

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        if not text_content and message.reply_to_message.caption:
            text_content = message.reply_to_message.caption
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        if message.caption and not text_content:
            text_content = message.caption

    if not text_content and not photo_file_id:
        await update.message.reply_text(
            "⚠️ Use: `/bc Sua mensagem aqui`\nOu responda a uma foto com `/bc` (legenda opcional).",
            parse_mode="Markdown"
        )
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        usuarios = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao acessar banco para broadcast: {e}")
        await update.message.reply_text("❌ Erro ao buscar lista de usuários.")
        return

    total = len(usuarios)
    if total == 0:
        await update.message.reply_text("📭 Nenhum usuário cadastrado.")
        return

    sucesso = 0
    falha = 0
    aviso = await update.message.reply_text(f"📢 Iniciando transmissão para {total} usuários...")

    for user in usuarios:
        user_id = user[0]
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_file_id,
                    caption=text_content if text_content else None,
                    parse_mode="Markdown" if text_content else None
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text_content,
                    parse_mode="Markdown"
                )
            sucesso += 1
        except Exception as e:
            falha += 1
            logger.debug(f"Falha ao enviar para {user_id}: {e}")
        await asyncio.sleep(0.05)

    await aviso.edit_text(
        f"✅ **Transmissão Finalizada!**\n\n🟢 Sucesso: {sucesso}\n🔴 Falhas: {falha}",
        parse_mode="Markdown"
    )

# =========================================================
# 6. SET BALANCE (centavos)
# =========================================================
async def set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Use: `/setbalance ID VALOR` (ex: `/setbalance 123456 50.00`)", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
        valor_float = float(context.args[1].replace(',', '.'))
        if valor_float < 0:
            raise ValueError
        valor_cents = float_to_cents(valor_float)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (target_id,))
        user_exists = cursor.fetchone()
        if not user_exists:
            cursor.execute("INSERT INTO users (user_id, main_balance_cents, first_name) VALUES (?, ?, ?)",
                           (target_id, 0, f"User_{target_id}"))
            conn.commit()

        cursor.execute("UPDATE users SET main_balance_cents = ? WHERE user_id = ?", (valor_cents, target_id))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Saldo de `{target_id}` atualizado para **R$ {cents_to_float(valor_cents):.2f}**", parse_mode="Markdown")

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"💰 Seu saldo foi alterado pelo administrador para: **R$ {cents_to_float(valor_cents):.2f}**",
                parse_mode="Markdown"
            )
        except:
            pass

    except ValueError:
        await update.message.reply_text("❌ Formato inválido. Use números para ID e valor (ex: 10.50).")
    except Exception as e:
        logger.error(f"Erro em set_balance: {e}")
        await update.message.reply_text("❌ Erro interno ao atualizar saldo.")

# =========================================================
# (Opcional) Migração manual
# =========================================================
async def migrate_balance_column(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(users)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'balance' in cols and 'main_balance_cents' in cols:
            cursor.execute("UPDATE users SET main_balance_cents = CAST(ROUND(COALESCE(balance, 0) * 100) AS INTEGER)")
            conn.commit()
            await update.message.reply_text("✅ Migração da coluna 'balance' para 'main_balance_cents' concluída.")
        else:
            await update.message.reply_text("⚠️ Colunas necessárias não encontradas.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def sync_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para sincronizar serviços do fornecedor (apenas admin)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return
    
    await update.message.reply_text("⏳ Sincronizando serviços com o fornecedor...")
    
    try:
        import subprocess
        import sys
        import os
        
        # Caminho para o update_db.py
        script_path = os.path.join(os.path.dirname(__file__), '..', 'update_db.py')
        
        # Executa o script
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            # Conta quantos serviços foram inseridos
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM services")
            count = cursor.fetchone()[0]
            conn.close()
            
            await update.message.reply_text(
                f"✅ **Sincronização concluída!**\n\n"
                f"📊 Total de serviços no banco: `{count}`\n"
                f"📡 Fornecedor: API atualizada\n\n"
                f"Use `/comprar` para ver os novos serviços."
            )
        else:
            await update.message.reply_text(f"❌ Erro na sincronização:\n```\n{result.stderr[:500]}\n```")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao executar: `{str(e)}`")

async def test_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe uma amostra dos serviços no banco (apenas admin)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Total de serviços
    cursor.execute("SELECT COUNT(*) FROM services")
    total = cursor.fetchone()[0]

    # Categorias distintas
    cursor.execute("SELECT DISTINCT category FROM services ORDER BY category LIMIT 15")
    categorias = [row[0] for row in cursor.fetchall()]

    # Primeiros 5 serviços
    cursor.execute("SELECT service_id, name, rate, category FROM services LIMIT 5")
    servicos = cursor.fetchall()

    conn.close()

    msg = f"📊 **Total de serviços:** `{total}`\n\n"
    msg += "📂 **Categorias (amostra):**\n"
    for cat in categorias:
        msg += f"• `{cat}`\n"

    msg += "\n🛒 **Primeiros serviços:**\n"
    for s in servicos:
        msg += f"• ID `{s[0]}` – {s[1]} (R$ {s[2]:.2f}) – *{s[3]}*\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def debug_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas administrador.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Total de serviços
    cursor.execute("SELECT COUNT(*) FROM services")
    total = cursor.fetchone()[0]

    # 2. Categorias cruas (primeiras 10)
    cursor.execute("SELECT DISTINCT category FROM services WHERE rate > 0 LIMIT 10")
    raw_cats = [row[0] for row in cursor.fetchall()]

    # 3. Amostra de serviços (primeiros 5)
    cursor.execute("SELECT service_id, name, category FROM services LIMIT 5")
    sample_services = cursor.fetchall()

    # 4. Categorias processadas pelo get_categories()
    from handlers.services import get_categories
    final_cats = get_categories()

    conn.close()

    # Monta mensagem sem Markdown (texto puro)
    msg = f"=== DIAGNÓSTICO ===\n\n"
    msg += f"Total de serviços: {total}\n\n"
    msg += "Categorias cruas (banco, primeiras 10):\n"
    for cat in raw_cats:
        msg += f"- {cat}\n"
    msg += "\nCategorias processadas (get_categories):\n"
    for cat in final_cats[:10]:
        msg += f"- {cat}\n"
    msg += "\nAmostra de serviços (ID, nome, categoria):\n"
    for s in sample_services:
        msg += f"- {s[0]} – {s[1][:50]} – {s[2]}\n"

    # Envia sem parse_mode (evita erros de formatação)
    await update.message.reply_text(msg)

async def test_api_fields(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    import requests
    url = os.getenv("SMM_API_URL_1")
    key = os.getenv("SMM_API_KEY_1")
    try:
        r = requests.post(url, data={'key': key, 'action': 'services'}, timeout=30)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            primeiro = data[0]
            campos = list(primeiro.keys())
            await update.message.reply_text(f"Campos do primeiro serviço:\n{', '.join(campos)}")
        else:
            await update.message.reply_text("Resposta inesperada.")
    except Exception as e:
        await update.message.reply_text(f"Erro: {e}")

async def check_descriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas administrador.")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT service_id, name, description FROM services WHERE description IS NOT NULL AND description != '' LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    if rows:
        msg = "📝 **Serviços com descrição (até 5):**\n\n"
        for r in rows:
            msg += f"🆔 `{r[0]}` – {r[1][:40]}\n📄 {r[2][:100]}\n\n"
    else:
        msg = "❌ Nenhum serviço possui descrição no banco."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_providers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Contagem por fornecedor
    cursor.execute("SELECT provider, COUNT(*) FROM services GROUP BY provider")
    counts = cursor.fetchall()
    msg = "📊 Serviços por fornecedor:\n"
    for prov, count in counts:
        msg += f"  Fornecedor {prov}: {count}\n"
    # Amostra de categorias do fornecedor 2
    cursor.execute("SELECT DISTINCT category FROM services WHERE provider = 2 LIMIT 10")
    cats2 = cursor.fetchall()
    msg += "\n📂 Categorias do Fornecedor 2 (amostra):\n"
    for cat in cats2:
        msg += f"  - {cat[0]}\n"
    # Amostra de categorias do fornecedor 1
    cursor.execute("SELECT DISTINCT category FROM services WHERE provider = 1 LIMIT 10")
    cats1 = cursor.fetchall()
    msg += "\n📂 Categorias do Fornecedor 1 (amostra):\n"
    for cat in cats1:
        msg += f"  - {cat[0]}\n"
    conn.close()
    await update.message.reply_text(msg)

async def debug_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /debug_cats - Mostra quantas categorias de cada provedor
    estão sendo retornadas por get_categories().
    """
    from handlers.services import get_categories   # import local para evitar circular

    cats = get_categories()
    if not cats:
        await update.message.reply_text("⚠️ Nenhuma categoria retornada.")
        return

    c1 = [c for c in cats if '[C1]' in c]
    c2 = [c for c in cats if '[C2]' in c]

    msg = (
        f"📊 **Total de categorias:** {len(cats)}\n"
        f"🔵 Fornecedor 1: {len(c1)}\n"
        f"🟢 Fornecedor 2: {len(c2)}\n\n"
    )

    if c2:
        # Mostra as primeiras 15 categorias do C2 para inspeção
        preview = "\n".join(c2[:15])
        msg += f"**Exemplos C2:**\n{preview}"
    else:
        msg += "❌ **Nenhuma categoria do Fornecedor 2 foi retornada!**"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def fix_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /corrigir_pedido para inserir pedido manualmente e debitar saldo."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "Uso: /corrigir_pedido <user_id> <order_id_api> <amount_float> <provider_id> <service_name> <quantity>\n"
            "Exemplo: /corrigir_pedido 8250294969 874907 1.50 2 \"Seguidores Instagram\" 100"
        )
        return

    try:
        user_id = int(args[0])
        order_id_api = int(args[1])
        amount_float = float(args[2])
        provider_id = int(args[3])
        service_name = ' '.join(args[4:-1])
        quantity = int(args[-1])
    except ValueError:
        await update.message.reply_text("❌ Parâmetros inválidos. Verifique os tipos (números onde esperado).")
        return

    amount_cents = int(amount_float * 100)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Insere o pedido
        cursor.execute("""
            INSERT INTO orders (user_id, service_name, quantity, amount_cents, order_id_api, status, date, provider_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, service_name, quantity, amount_cents, order_id_api, "Pendente", datetime.now().strftime("%d/%m/%Y %H:%M"), provider_id))

        # Debita o saldo
        cursor.execute("UPDATE users SET main_balance_cents = main_balance_cents - ? WHERE user_id = ?", (amount_cents, user_id))
        conn.commit()

        await update.message.reply_text(
            f"✅ Pedido `{order_id_api}` corrigido.\n"
            f"👤 Usuário: `{user_id}`\n"
            f"💰 Valor debitado: R$ {amount_float:.2f}"
        )
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def limpar_fornecedor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /limpar_fornecedor 1 ou 2"""
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        prov = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM services WHERE provider = ?", (prov,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Serviços do Fornecedor {prov} removidos.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
