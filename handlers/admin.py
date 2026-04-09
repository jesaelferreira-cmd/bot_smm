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
