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
from database import get_connection

conn = get_connection()
cursor = conn.cursor()

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
async def safe_edit(query, text: str, reply_markup=None, parse_mode="Markdown"):
    """Edita mensagem com texto ou legenda, com fallback para nova mensagem."""
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass
    await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)

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
    safe_link = link_convite

    texto = (
        "🤝 **PROGRAMA DE AFILIADOS LIKESPLUS**\n\n"
        "💰 **Ganhe saldo GRÁTIS indicando seus amigos!** 💰\n\n"
        "• Ser afiliado é a melhor forma de ganhar saldo sem custo.\n"
        "• Você recebe **10% de cada recarga** do seu indicado.\n"
        "• **Saques via PIX** (mínimo R$30) ou **resgate para saldo do bot** (mínimo R$5).\n"
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

        if balance_cents < 500:
            await query.message.reply_text(f"❌ Saldo insuficiente. Mínimo: R$ 5,00. Você tem R$ {cents_to_float(balance_cents):.2f}")
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
        conn.rollback()
        logger.error(f"Erro no saque PIX: {e}")
    try:
        # Tenta enviar a mensagem de erro, mas com timeout curto e sem esperar muito
        await update.message.reply_text("❌ Erro interno ao processar saque. Tente novamente.")
    except Exception as reply_error:
        logger.error(f"Falha ao enviar mensagem de erro: {reply_error}")
    finally:
        # O lock será liberado apenas quando o fluxo terminar (no receive_pix_key ou cancel_pix)
        pass

async def receive_pix_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pix_key = update.message.text.strip() if update.message and update.message.text else ""

    if not pix_key or not is_valid_pix_key(pix_key):
        await update.message.reply_text(
            "❌ **Chave PIX inválida!**\n"
            "Envie uma chave válida (CPF, e-mail, telefone ou aleatória).\n"
            "Exemplo: `11999999999` ou `email@exemplo.com`\n\n"
            "Digite novamente ou /cancel para sair.",
            parse_mode="Markdown"
        )
        return PIX_KEY

    amount_cents = context.user_data.get('pix_amount_cents')
    name = context.user_data.get('pix_user_name') or "Usuário"

    if not amount_cents:
        await update.message.reply_text("❌ Sessão expirada. Inicie o saque novamente.")
        return ConversationHandler.END

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Verifica saldo
        cursor.execute("SELECT affiliate_balance_cents FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[0] < amount_cents:
            await update.message.reply_text("❌ Saldo insuficiente. Saque cancelado.")
            return ConversationHandler.END

        # Prepara mensagem com botões de confirmação/cancelamento
        admin_text = (
            f"🚨 **SAQUE PIX SOLICITADO**\n\n"
            f"👤 Usuário: {name}\n"
            f"🆔 ID: `{user_id}`\n"
            f"💰 Valor: **R$ {cents_to_float(amount_cents):.2f}**\n"
            f"🔑 Chave: `{pix_key}`\n\n"
            f"⏰ Data: `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmar Pagamento", callback_data=f"confirm_payment_{user_id}_{amount_cents}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel_payment_{user_id}_{amount_cents}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Notifica admin (com tratamento de erro separado)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Falha ao notificar admin: {e}")
            await update.message.reply_text("❌ Erro ao processar solicitação. Tente mais tarde.")
            return ConversationHandler.END

        # Debita saldo
        cursor.execute(
            "UPDATE users SET affiliate_balance_cents = affiliate_balance_cents - ? WHERE user_id = ? AND affiliate_balance_cents >= ?",
            (amount_cents, user_id, amount_cents)
        )
        if cursor.rowcount == 0:
            await update.message.reply_text("❌ Saldo já utilizado. Saque cancelado.")
            return ConversationHandler.END

        conn.commit()
        logger.info(f"SAQUE PIX confirmado: user={user_id}, amount={amount_cents}, key={pix_key}")

        await update.message.reply_text(
            f"✅ **Saque solicitado com sucesso!**\n\n"
            f"💰 Valor: R$ {cents_to_float(amount_cents):.2f}\n"
            f"🔑 Chave: `{pix_key}`\n\n"
            "O administrador processará o pagamento em até 24 horas.\n"
            "Qualquer dúvida, entre em contato com o suporte.",
            parse_mode="Markdown"
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no saque PIX: {e}")
        try:
            await update.message.reply_text("❌ Erro interno ao processar saque. Tente novamente.")
        except Exception:
            pass
    finally:
        conn.close()
        context.user_data.pop('pix_amount_cents', None)
        context.user_data.pop('pix_user_name', None)
        if user_id in user_pix_locks:
            lock = user_pix_locks.pop(user_id, None)
            if lock:
                try:
                    lock.release()
                except:
                    pass

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

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para quando o admin confirma o pagamento do saque."""
    query = update.callback_query
    await query.answer("Pagamento confirmado!")

    # Extrai dados do callback_data: "confirm_payment_userId_amountCents"
    data = query.data.split("_")
    user_id = int(data[2])
    amount_cents = int(data[3])

    # (Opcional) Registrar no banco que o pagamento foi realizado
    # Por exemplo, criar uma tabela 'withdrawals' com status 'paid'
    # Aqui apenas notificamos o usuário

    # Mensagem para o afiliado
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ **Pagamento realizado!**\n\n"
            f"Seu saque de **R$ {cents_to_float(amount_cents):.2f}** foi processado.\n"
            f"O valor foi enviado para a chave PIX informada. Verifique sua conta em alguns instantes.\n\n"
            f"Obrigado por usar o programa de afiliados da LikesPlus! 💰"
        ),
        parse_mode="Markdown"
    )

    # Atualiza a mensagem original do admin (remove os botões e marca como concluído)
    await query.edit_message_text(
        text=query.message.text + "\n\n✅ **Pagamento confirmado pelo administrador.**",
        parse_mode="Markdown"
    )

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para quando o admin cancela o saque (estorna o saldo do afiliado)."""
    query = update.callback_query
    await query.answer("Saque cancelado.")

    data = query.data.split("_")
    user_id = int(data[2])
    amount_cents = int(data[3])

    # Estorna o saldo do afiliado (devolve o que foi debitado)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET affiliate_balance_cents = affiliate_balance_cents + ? WHERE user_id = ?",
            (amount_cents, user_id)
        )
        conn.commit()
        logger.info(f"Estorno de {amount_cents} centavos para o usuário {user_id} (saque cancelado)")
    except Exception as e:
        logger.error(f"Erro ao estornar saldo: {e}")
    finally:
        conn.close()

    # Notifica o usuário sobre o cancelamento
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"❌ **Saque cancelado!**\n\n"
            f"O saque de **R$ {cents_to_float(amount_cents):.2f}** foi cancelado pelo administrador.\n"
            f"O valor foi devolvido para o seu saldo de afiliado.\n\n"
            f"Entre em contato com o suporte para mais informações."
        ),
        parse_mode="Markdown"
    )

    # Atualiza a mensagem do admin
    await query.edit_message_text(
        text=query.message.text + "\n\n❌ **Saque cancelado pelo administrador (saldo estornado).**",
        parse_mode="Markdown"
    )
