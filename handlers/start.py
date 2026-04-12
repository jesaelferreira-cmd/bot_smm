import os
import sqlite3
import logging
from config import DB_PATH
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

@rate_limit(seconds=3)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu Principal com Banner e Sistema de Afiliados"""
    user = update.effective_user
    user_id = user.id
    query = update.callback_query

    # --- 1. LÓGICA DE AFILIADOS (CAPTURA INDICAÇÃO) ---
# --- 1. LÓGICA DE AFILIADOS (CAPTURA INDICAÇÃO) ---
if context.args and not query:
    referrer_id_str = context.args[0]
    logger.info(f"📎 /start com argumentos: {context.args} | user={user_id}")

    if referrer_id_str.isdigit():
        referrer_id = int(referrer_id_str)
        if referrer_id != user_id:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Garante que a coluna referred_by existe (cria se necessário)
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'referred_by' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
                conn.commit()
                logger.info("Coluna 'referred_by' adicionada à tabela users")

            # Insere ou ignora o usuário (garante que ele existe)
            cursor.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, username, balance, main_balance_cents, affiliate_balance_cents) "
                "VALUES (?, ?, ?, 0.0, 0, 0)",
                (user_id, user.first_name, user.username)
            )

            # Tenta atualizar o referenciador apenas se ainda não estiver definido
            cursor.execute(
                "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
                (referrer_id, user_id)
            )
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"✅ Indicação registrada: user={user_id} foi indicado por {referrer_id}")
            else:
                # Verifica se já tinha referenciador
                cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
                current_ref = cursor.fetchone()
                if current_ref and current_ref[0]:
                    logger.info(f"ℹ️ Usuário {user_id} já possui referenciador {current_ref[0]}, ignorando.")
                else:
                    logger.warning(f"⚠️ UPDATE não afetou linhas para user={user_id} (possível condição de corrida)")

            conn.close()
        else:
            logger.info(f"❌ Tentativa de autoindicação ignorada: user={user_id}")
    else:
        logger.info(f"❌ Argumento inválido (não numérico): {referrer_id_str}")
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

