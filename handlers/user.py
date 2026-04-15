import sqlite3
from config import DB_PATH
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o perfil do usuário (Texto limpo, sem banner)"""
    query = update.callback_query
    tg_user = update.effective_user
    user_id = tg_user.id

    if query:
        await query.answer()

    try:
        # 1. Buscar dados no banco
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Puxa Saldo (AGORA USA main_balance_cents)
        cursor.execute("SELECT main_balance_cents FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance_cents = result[0] if result else 0
        balance = balance_cents / 100.0

        # Puxa Total de Pedidos Realizados
        cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))
        total_pedidos = cursor.fetchone()[0]
        conn.close()

        # 2. Montar o Texto do Perfil
        texto_perfil = (
            f"👤 **MEU PERFIL - LIKESPLUS**\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"👤 **Nome:** {tg_user.first_name}\n"
            f"💰 **Saldo:** R$ {balance:.2f}\n"
            f"📦 **Pedidos Totais:** {total_pedidos}\n\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
            f"🚀 Use os botões abaixo para navegar."
        )

        # 3. Botões de Navegação
        keyboard = [
            [InlineKeyboardButton("🛒 Ir para Loja", callback_data="back_to_categories")],
            [InlineKeyboardButton("🏠 Voltar ao Início", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 4. Envio
        if query:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=user_id,
                text=texto_perfil,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(texto_perfil, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        print(f"Erro ao carregar perfil: {e}")
        await context.bot.send_message(chat_id=user_id, text="⚠️ Erro ao carregar seu perfil.")
