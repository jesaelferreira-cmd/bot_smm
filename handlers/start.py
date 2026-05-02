import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime
from config import ADMIN_ID
from database import get_connection

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    username = update.effective_user.username

    # Verifica se o usuário já existe no banco, senão cria
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (user_id, first_name, username, main_balance_cents, affiliate_balance_cents, created_at) VALUES (%s, %s, %s, 0, 0, %s)",
                (user_id, first_name, username, datetime.now())
            )
            conn.commit()
            logger.info(f"Novo usuário: {user_id} - {first_name}")
    except Exception as e:
        logger.error(f"Erro ao inserir usuário: {e}")
        conn.rollback()
    finally:
        conn.close()

    # Verifica se o usuário foi indicado por alguém (via parâmetro start=ref)
    if context.args:
        referrer_id = context.args[0]
        if referrer_id.isdigit() and int(referrer_id) != user_id:
            referrer_id = int(referrer_id)
            conn = get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT referred_by FROM users WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if not row or not row[0]:
                    cursor.execute("UPDATE users SET referred_by = %s WHERE user_id = %s", (referrer_id, user_id))
                    conn.commit()
                    logger.info(f"Usuário {user_id} indicado por {referrer_id}")
            except Exception as e:
                logger.error(f"Erro ao salvar indicação: {e}")
                conn.rollback()
            finally:
                conn.close()

    # Menu principal
    keyboard = [
        [InlineKeyboardButton("🛒 Comprar Serviços", callback_data="back_to_categories")],
        [InlineKeyboardButton("💰 Saldo", callback_data="show_balance")],
        [InlineKeyboardButton("📜 Meus Pedidos", callback_data="my_history")],
        [InlineKeyboardButton("🤝 Indicar Amigos", callback_data="affiliates")],
        [InlineKeyboardButton("❓ Ajuda", callback_data="help_menu")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Painel Admin", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"🎉 *Bem-vindo ao LikesPlus, {first_name}!* 🎉\n\n"
        "🚀 A plataforma mais completa para turbinar suas redes sociais!\n\n"
        "✅ Serviços para Instagram, TikTok, YouTube, Facebook, Kwai, Telegram e muito mais.\n"
        "✅ Pagamento via PIX (cai na hora).\n"
        "✅ Ganhe 10% de comissão indicando amigos!\n\n"
        "Use os botões abaixo para navegar:"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
