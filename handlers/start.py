import logging
from datetime import datetime
from html import escape as escape_html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.connection import get_connection
from config import ADMIN_ID

logger = logging.getLogger(__name__)

# ===== TEXTOS =====
WELCOME_HEADER = "✨ <b>LikesPlus</b> ✨\n🤖 Assistente Virtual\n\n"
INSTRUCTIONS = (
    "📌 <b>INSTRUÇÕES IMPORTANTES</b>\n"
    "   🔓 O perfil deve permanecer <b>PÚBLICO</b> durante todo o processo\n"
    "   🔍 Verifique atentamente o link/usuário antes de enviar\n"
    "   ❌ Não há reembolso em caso de erro do usuário\n"
    "   ⚠️ Utilize os serviços com moderação\n\n"
)
SUPPORT_TEMPLATE = (
    "📞 <b>Suporte</b>\n"
    "Em caso de dúvidas ou problemas com pedidos, informe seu ID (<code>{user_id}</code>) ao suporte.\n\n"
)
TERMS_TEXT = "🔒 <b>Segurança e Termos</b>\nAo prosseguir, você declara que leu e concorda com nossos termos de uso."


def build_main_keyboard() -> InlineKeyboardMarkup:
    """Constrói o teclado inline com botões lado a lado e destaque para compra."""
    keyboard = [
        [InlineKeyboardButton("🛒 COMPRAR SEGUIDORES E CURTIDAS", callback_data="back_to_categories")],
        [
            InlineKeyboardButton("👤 Meu Perfil", callback_data="my_profile"),
            InlineKeyboardButton("💳 Adicionar Saldo", callback_data="add_balance"),
        ],
        [
            InlineKeyboardButton("📜 Histórico", callback_data="my_history"),
            InlineKeyboardButton("🤝 Afiliados", callback_data="affiliates"),
        ],
        [
            InlineKeyboardButton("🎧 Suporte", url="https://t.me/LPsSuporte"),
            InlineKeyboardButton("📊 Consultoria de Perfil", callback_data="profile_consulting"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start: exibe mensagem de boas-vindas e menu principal."""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "Usuário"
    username = update.effective_user.username

    safe_first_name = escape_html(first_name)
    safe_user_id = escape_html(str(user_id))

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Upsert do usuário
                cur.execute(
                    """
                    INSERT INTO users (
                        user_id,
                        first_name,
                        username,
                        balance,
                        affiliate_balance,
                        created_at
                    )
                    VALUES (%s, %s, %s, 0, 0, %s)
                    ON CONFLICT (user_id) DO NOTHING;
                    """,
                    (user_id, first_name, username, datetime.now())
                )
                conn.commit()

                # Saldo
                cur.execute(
                    "SELECT balance FROM users WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
                saldo_centavos = int(row[0]) if row else 0
                saldo_reais = saldo_centavos / 100.0

                # Pedidos
                cur.execute(
                    "SELECT COUNT(*) FROM orders WHERE user_id = %s",
                    (user_id,)
                )
                total_pedidos = cur.fetchone()[0]

    except Exception:
        logger.exception("Erro ao carregar dados do usuário %s", user_id)

        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>Erro interno.</b> Tente novamente mais tarde.",
                parse_mode="HTML"
            )
        return

    msg = (
        WELCOME_HEADER +
        f"👋 Olá, <b>{safe_first_name}</b>! Seja bem-vindo ao <b>LIKESPLUS</b>.\n\n"
        f"🆔 <b>ID do usuário:</b> <code>{safe_user_id}</code>\n"
        f"💰 <b>Saldo disponível:</b> <code>R$ {saldo_reais:.2f}</code>\n"
        f"📦 <b>Total de pedidos:</b> <code>{total_pedidos}</code>\n\n"
        + INSTRUCTIONS +
        SUPPORT_TEMPLATE.format(
            user_id=f"<code>{safe_user_id}</code>"
        ) +
        TERMS_TEXT
    )

    reply_markup = build_main_keyboard()

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=msg,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

    elif update.message:
        await update.message.reply_text(
            text=msg,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

    else:
        logger.error(
            "Tipo de update desconhecido no start_command para o usuário %s",
            user_id
        )



