import sqlite3
import logging
import re
from asyncio import Lock
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from config import DB_PATH, ADMIN_ID
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.helpers import escape_markdown
from collections import defaultdict
from datetime import date

logger = logging.getLogger(__name__)
user_daily_pix = defaultdict(int)
last_reset_date = date.today()

# =========================================================
# CONFIGURAÇÕES
# =========================================================

# Estados para o ConversationHandler do saque PIX
PIX_KEY = 1

# Lock para evitar double spending no saque PIX
user_pix_locks = {}

# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================
def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

def is_valid_pix_key(key: str) -> bool:
    """Valida chave PIX (CPF, e-mail, telefone, UUID)"""
    key = key.strip()
    # CPF (11 dígitos, pode ter pontos e traços)
    if re.match(r'^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$', key):
        return True
    # E-mail simples
    if re.match(r'^[^@]+@[^@]+\.[^@]+$', key):
        return True
    # Telefone (com ou sem DDD, com ou sem 9)
    if re.match(r'^\(?\d{2}\)?\s?\d{4,5}-?\d{4}$', key):
        return True
    # Chave aleatória (UUID)
    if re.match(r'^[a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12}$', key, re.I):
        return True
    return False

async def withdraw_pix_start(update, context):
    user_id = update.effective_user.id
    
    # Reset diário
    today = date.today()
    if today != last_reset_date:
        user_daily_pix.clear()
        last_reset_date = today
    
    # Limite de 3 saques PIX por dia
    if user_daily_pix[user_id] >= 3:
        await query.message.reply_text("❌ Você atingiu o limite de 3 saques PIX por dia. Tente amanhã.")
        return ConversationHandler.END
    
    user_daily_pix[user_id] += 1

# =========================================================
# CENTRAL DE AFILIADOS
# =========================================================
async def show_affiliates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username

    query = update.callback_query
    if query:
        await query.answer()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT affiliate_balance_cents FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    balance_cents = res[0] if res else 0
    balance_str = cents_to_float(balance_cents)

    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    total_refs = cursor.fetchone()[0]

    # --- TOTAL JÁ GANHO (se existir tabela commissions) ---
    total_earned_str = "📊 em breve"
    try:
        cursor.execute("SELECT SUM(commission_cents) FROM commissions WHERE user_id = ?", (user_id,))
        earned_cents = cursor.fetchone()[0]
        if earned_cents is not None:
            total_earned_str = f"R$ {cents_to_float(earned_cents):.2f}"
    except sqlite3.OperationalError:
        # Tabela commissions não existe ainda
        pass
    conn.close()

    link_convite = f"https://t.me/{bot_username}?start={user_id}"
    safe_link = escape_markdown(link_convite, version=2)

    texto = (
        "🤝 **PROGRAMA DE AFILIADOS LIKESPLUS**\n\n"
        "💰 **Ganhe saldo GRÁTIS indicando seus amigos!** 💰\n\n"
        "• Ser afiliado é a melhor forma de ganhar saldo sem custo.\n"
        "• Você recebe **10% de cada recarga** do seu indicado.\n"
        "• **Saques via PIX** (mínimo R$30) ou **resgate para saldo do bot** (mínimo R$1).\n"
        "• Ganhos ilimitados! 🚀\n\n"
        f"👥 **Indicados ativos:** `{total_refs}`\n"
        f"💰 **Saldo de Comissão disponível:** `R$ {balance_str:.2f}`\n"
        f"🏆 **Total já ganho:** `{total_earned_str}`\n\n"
        "🔗 **Seu link exclusivo:**\n"
        f"`{safe_link}`\n\n"
        "📢 Compartilhe seu link e comece a lucrar!"
    )

    keyboard = [
        [InlineKeyboardButton("🛒 Resgatar para Saldo Bot", callback_data="aff_withdraw_bot")],
        [InlineKeyboardButton("🏦 Sacar via PIX (Dinheiro)", callback_data="aff_withdraw_pix")],
        [InlineKeyboardButton("👥 Ver meus indicados", callback_data="aff_my_referrals")],
        [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            try:
                await query.edit_message_caption(caption=texto, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

# =========================================================
# VER MEUS INDICADOS
# =========================================================
async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe lista de usuários que o usuário indicou"""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = update.effective_user.id
    else:
        user_id = update.effective_user.id

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, first_name, username, created_at
        FROM users
        WHERE referred_by = ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        texto = "📭 Você ainda não indicou nenhum usuário.\n\nCompartilhe seu link e comece a ganhar!"
        keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="affiliates")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if query:
            try:
                await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception:
                try:
                    await query.edit_message_caption(caption=texto, reply_markup=reply_markup, parse_mode="Markdown")
                except Exception:
                    await query.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        return

    texto = "👥 **SEUS INDICADOS (últimos 10)**\n\n"
    for row in rows:
        uid, name, username, date = row
        data_formatada = date[:10] if date else "data desconhecida"
        nome_exib = name if name else f"User {uid}"
        if username:
            texto += f"• [{nome_exib}](https://t.me/{username}) – `{data_formatada}`\n"
        else:
            texto += f"• {nome_exib} – `{data_formatada}`\n"
    
    texto += "\n✅ *A cada recarga deles, você ganha 10% de comissão!*"

    keyboard = [[InlineKeyboardButton("⬅️ Voltar", callback_data="affiliates")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.edit_message_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            try:
                await query.edit_message_caption(caption=texto, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

# =========================================================
# SAQUE PARA SALDO DO BOT
# =========================================================
async def withdraw_to_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT affiliate_balance_cents FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        balance_cents = res[0] if res else 0

        if balance_cents < 100:
            await query.message.reply_text(f"❌ Saldo insuficiente. Mínimo: R$ 1,00. Você tem R$ {cents_to_float(balance_cents):.2f}")
            return

        cursor.execute(
            "UPDATE users SET main_balance_cents = main_balance_cents + ?, affiliate_balance_cents = 0 WHERE user_id = ?",
            (balance_cents, user_id)
        )
        conn.commit()
        await query.message.reply_text(
            f"✅ **Resgate realizado!**\n\nValor transferido: R$ {cents_to_float(balance_cents):.2f}"
        )
        logger.info(f"Resgate de afiliado: user={user_id}, amount={balance_cents} cents")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no resgate: {e}")
        await query.message.reply_text("❌ Erro interno. Tente novamente.")
    finally:
        conn.close()

# =========================================================
# SAQUE PIX (COM CONVERSATION HANDLER E SEGURANÇA)
# =========================================================
async def withdraw_pix_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    user_id = update.effective_user.id

    # Verifica se já existe um saque em andamento para este usuário
    if user_id in user_pix_locks and user_pix_locks[user_id].locked():
        await query.answer()
        await query.message.reply_text("⏳ Você já tem uma solicitação de saque em andamento. Aguarde.")
        return ConversationHandler.END

    # Cria um lock para este usuário
    user_pix_locks[user_id] = Lock()
    await user_pix_locks[user_id].acquire()

    try:
        await query.answer()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT affiliate_balance_cents, first_name FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()

        if not res:
            await query.message.reply_text("❌ Usuário não encontrado.")
            return ConversationHandler.END

        balance_cents = res[0]
        name = res[1]

        if balance_cents < 3000:
            await query.message.reply_text(f"❌ Saldo insuficiente. Mínimo: R$ 30,00. Você tem R$ {cents_to_float(balance_cents):.2f}")
            return ConversationHandler.END

        context.user_data['pix_amount_cents'] = balance_cents
        context.user_data['pix_user_name'] = name

        keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data="cancel_pix")]]
        await query.message.reply_text(
            f"💰 **Valor a sacar:** R$ {cents_to_float(balance_cents):.2f}\n\n"
            "Envie sua **chave PIX** (CPF, e-mail, telefone ou aleatória):\n"
            "Digite ou cole a chave agora.\n\n"
            "⚠️ *Chave inválida cancela a solicitação.*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PIX_KEY
    except Exception as e:
        logger.error(f"Erro em withdraw_pix_start: {e}")
        await query.message.reply_text("❌ Erro interno. Tente novamente.")
        return ConversationHandler.END
    finally:
        # O lock será liberado apenas quando o fluxo terminar (no receive_pix_key ou cancel_pix)
        pass

async def receive_pix_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pix_key = update.message.text.strip()

    # Valida a chave PIX
    if not is_valid_pix_key(pix_key):
        await update.message.reply_text(
            "❌ **Chave PIX inválida!**\n"
            "Envie uma chave válida (CPF, e-mail, telefone ou aleatória).\n"
            "Exemplo: `11999999999` ou `email@exemplo.com`\n\n"
            "Digite novamente ou /cancel para sair."
        )
        return PIX_KEY

    amount_cents = context.user_data.get('pix_amount_cents')
    name = context.user_data.get('pix_user_name')

    if not amount_cents:
        await update.message.reply_text("❌ Sessão expirada. Inicie o saque novamente.")
        return ConversationHandler.END

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Tenta debitar o saldo com condição (atomicidade total)
        cursor.execute(
            "UPDATE users SET affiliate_balance_cents = affiliate_balance_cents - ? WHERE user_id = ? AND affiliate_balance_cents >= ?",
            (amount_cents, user_id, amount_cents)
        )
        if cursor.rowcount == 0:
            await update.message.reply_text("❌ Saldo insuficiente ou já utilizado. Saque cancelado.")
            logger.warning(f"Tentativa de saque duplicado ou saldo insuficiente: user={user_id}, amount={amount_cents}")
            return ConversationHandler.END

        conn.commit()

        # Registra log detalhado da solicitação
        logger.warning(f"SAQUE PIX SOLICITADO: user={user_id}, amount={amount_cents} cents, key={pix_key}, time={datetime.now()}")

        # Notifica o admin com a chave PIX
        safe_name = escape_markdown(name, version=2)
        safe_key = escape_markdown(pix_key, version=2)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🚨 **SAQUE PIX SOLICITADO**\n\n"
                f"👤 Usuário: {safe_name}\n"
                f"🆔 ID: `{user_id}`\n"
                f"💰 Valor: **R$ {cents_to_float(amount_cents):.2f}**\n"
                f"🔑 Chave: `{safe_key}`\n\n"
                f"⏰ Data: `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`"
            ),
            parse_mode="MarkdownV2"
        )

        await update.message.reply_text(
            f"✅ **Saque solicitado com sucesso!**\n\n"
            f"💰 Valor: R$ {cents_to_float(amount_cents):.2f}\n"
            f"🔑 Chave: `{pix_key}`\n\n"
            "O administrador processará o pagamento em até 24 horas.\n"
            "Qualquer dúvida, entre em contato com o suporte."
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no saque PIX: {e}")
        await update.message.reply_text("❌ Erro interno ao processar saque. Tente novamente.")
    finally:
        conn.close()
        # Limpa dados temporários e libera o lock
        context.user_data.pop('pix_amount_cents', None)
        context.user_data.pop('pix_user_name', None)
        if user_id in user_pix_locks:
            user_pix_locks[user_id].release()
            del user_pix_locks[user_id]

    return ConversationHandler.END

async def cancel_pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()
        await query.message.reply_text("❌ Saque via PIX cancelado.")
    else:
        await update.message.reply_text("❌ Operação cancelada.")

    context.user_data.pop('pix_amount_cents', None)
    context.user_data.pop('pix_user_name', None)

    if user_id in user_pix_locks:
        user_pix_locks[user_id].release()
        del user_pix_locks[user_id]

    return ConversationHandler.END

# =========================================================
# CONVERSATION HANDLER (para registrar no main.py)
# =========================================================
pix_withdrawal_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(withdraw_pix_start, pattern="^aff_withdraw_pix$")],
    states={
        PIX_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pix_key),
            CallbackQueryHandler(cancel_pix, pattern="^cancel_pix$")
        ],
    },
    fallbacks=[CallbackQueryHandler(cancel_pix, pattern="^cancel_pix$")],
    allow_reentry=False,  # Não permite reentrada enquanto um saque está ativo
)
