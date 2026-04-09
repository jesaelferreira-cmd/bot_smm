import os
import sqlite3
from config import DB_PATH
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from utils.rate_limit import rate_limit

@rate_limit(seconds=3)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu Principal com Banner e Sistema de Afiliados"""
    user = update.effective_user
    user_id = user.id
    query = update.callback_query

    # --- 1. LÓGICA DE AFILIADOS (CAPTURA INDICAÇÃO) ---
    if context.args and not query:
        referrer_id = context.args[0]
        # Verifica se o ID é número e se não é o próprio usuário se auto-indicando
        if referrer_id.isdigit() and int(referrer_id) != user_id:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            # Só registra se o usuário for novo (referred_by ainda é NULL)
            cursor.execute(
                "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
                (referrer_id, user_id)
            )
            conn.commit()
            conn.close()

    # --- 2. BUSCA DADOS DO USUÁRIO NO BANCO ---
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Garante que o usuário existe e pega o saldo
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0.0))
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0.0
    
    # Conta quantos pedidos ele já fez
    cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))
    compras_count = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    # --- 3. MONTAGEM DO TEXTO E TECLADO ---
    texto = (
        f"👋 Olá, **{user.first_name}**. Seja bem-vindo ao **LIKESPLUS**.\n\n"
        f"🆔 **ID do usuário:** `{user_id}`\n"
        f"💰 **Saldo disponível:** R$ {balance:.2f}\n"
        f"🛒 **Total de pedidos:** {compras_count}\n\n"
    
        f"📌 **INSTRUÇÕES IMPORTANTES:**\n"
        f"• O perfil deve permanecer **PÚBLICO** durante todo o processo\n"
        f"• Verifique atentamente o link/usuário antes de enviar\n"
        f"• Não há reembolso em caso de erro do usuário\n"
        f"• Utilize os serviços com moderação\n\n"
    
        f"📩 **Suporte:**\n"
        f"Em caso de dúvidas ou problemas com pedidos, informe seu ID (**{user_id}**) ao suporte.\n\n"
    
        f"🔒 **Segurança e termos:**\n"
        f"Ao prosseguir, você declara que leu e concorda com nossos termos de uso.\n"
    )
    keyboard = [
        [InlineKeyboardButton("🛒 Comprar Seguidores/Curtidas", callback_data="back_to_categories")],
        [
            InlineKeyboardButton("👤 Meu Perfil", callback_data="my_profile"),
            InlineKeyboardButton("💰 Adicionar Saldo", callback_data="add_balance")
        ],
        [
            InlineKeyboardButton("🗓 Histórico", callback_data="my_history"),
            InlineKeyboardButton("🤝 Afiliados", callback_data="affiliates")
        ],
        # O código correto no seu InlineKeyboardButton:
        [InlineKeyboardButton("🎧 Suporte", url="https://t.me/LPsSuporte")]

    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    foto_path = "banner.jpg"

    # --- 4. ENVIO INTELIGENTE (HÍBRIDO) ---
    if query:
        await query.answer()
        try:
            # Se já existe uma foto, editamos a legenda para manter o banner parado
            if query.message.photo:
                await query.edit_message_caption(
                    caption=texto,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                # Se for uma mensagem de texto, editamos o texto
                await query.edit_message_text(
                    text=texto,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception:
            # Fallback: Se der erro na edição, manda uma nova foto
            if os.path.exists(foto_path):
                with open(foto_path, 'rb') as photo:
                    await context.bot.send_photo(chat_id=user_id, photo=photo, caption=texto, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # Comando /start direto: envia foto nova
        if os.path.exists(foto_path):
            with open(foto_path, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=texto,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

