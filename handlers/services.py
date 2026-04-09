import logging
import sqlite3
import re
from typing import List
from config import DB_PATH
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from handlers.orders import confirm_order  # Importação explícita

logger = logging.getLogger(__name__)

# =========================================================
# ESTADOS DO CONVERSATION HANDLER (PADRONIZADOS)
# =========================================================
(
    SELECTING_SERVICE,    # 0
    ASKING_QUANTITY,      # 1
    WAIT_CONFIRM_PRICE,   # 2
    ASKING_LINK,          # 3
    CONFIRMING            # 4
) = range(5)

# =========================
# CONFIGURAÇÕES GLOBAIS
# =========================
ICONS_MAP = {
    "instagram": "📸",
    "tiktok": "📱",
    "youtube": "🎥",
    "kwai": "🎥",
    "google": "🌐",
    "facebook": "💙",
    "telegram": "💎",
    "twitter": "🐦",
    "x": "🐦",
    "bluesky": "🦋",
    "threads": "💬",
    "pinterest": "📌",
    "whatsapp": "📞",
    "kick": "🎮",
    "twitch": "🟣",
    "denuncia": "🚫",
    "other": "⭐️",
    "trovo": "👽",
    "tidal": "☁️",
    "snackvideo": "🎥",
    "linkedin": "📊",
    "reddit": "🤖",
    "dribbble": "🏀",
    "rumble": "🎥",
    "coinmarketcap": "💰",
    "site": "💻"
}

FORBIDDEN_TERMS = ["desativado", "manutenção", "testes", "comunidade", "promoção", "provedor"]

PRIORITY_MAP = {
    "📸": 1, "📌": 2, "💬": 3, "📞": 4, "🎮": 5,
    "🟣": 6, "🚫": 7, "⭐️": 8, "👽": 9, "☁️": 10,
    "🏀": 11, "📊": 12, "🤖": 13, "🌐": 14, "💎": 15,
    "🦋": 16, "📱": 17, "🎥": 18, "💻": 19, "🚀": 20
}

EMOJI_REGEX = re.compile(r'^[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]')

# =========================
# FUNÇÕES AUXILIARES DE SEGURANÇA
# =========================
def validate_link(link: str) -> bool:
    """Validação básica de URL para evitar dados maliciosos"""
    link = link.strip()
    if not link:
        return False
    # Aceita http, https, ou apenas domínio simples (ex: @username)
    if re.match(r'^(https?://)?[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(/\S*)?$', link):
        return True
    # Aceita também menções (ex: @usuario)
    if re.match(r'^@[\w_]+$', link):
        return True
    return False

def sanitize_input(text: str) -> str:
    """Remove caracteres potencialmente perigosos para SQL/HTML (apenas para exibição segura)"""
    return re.sub(r'[<>"\']', '', text)

# =========================
# BUSINESS LOGIC (CATEGORIAS)
# =========================
def detect_icon(category: str) -> str:
    cat_lower = category.lower()
    return next((icon for key, icon in ICONS_MAP.items() if key in cat_lower), "🚀")

def normalize_category(category: str) -> str:
    category = category.strip()
    if EMOJI_REGEX.match(category):
        return category
    icon = detect_icon(category)
    return f"{icon} {category}"

def sort_categories(categories: List[str]) -> List[str]:
    def sort_key(item: str):
        emoji = item[0] if item else ""
        priority = PRIORITY_MAP.get(emoji, 99)
        clean_name = item[1:].strip() if len(item) > 1 else item
        return (priority, clean_name)
    return sorted(categories, key=sort_key)

def is_valid_category(category: str) -> bool:
    cat_lower = category.lower().strip()
    if category.isdigit() or len(category) < 3:
        return False
    if any(term in cat_lower for term in FORBIDDEN_TERMS):
        return False
    return True

# =========================
# DATABASE LAYER (ATUALIZADO COM FALLBACK)
# =========================
def fetch_categories_from_db() -> List[str]:
    query_main = """
        SELECT DISTINCT s.category
        FROM services s
        JOIN providers_status ps ON s.provider_id = ps.id
        WHERE s.rate > 0 AND ps.status = 'ONLINE'
    """
    query_fallback = "SELECT DISTINCT category FROM services WHERE rate > 0"
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query_main)
            except sqlite3.OperationalError:
                cursor.execute(query_fallback)
            rows = cursor.fetchall()
        return [row[0] for row in rows if row and row[0]]
    except Exception as e:
        logger.error(f"Erro ao buscar categorias: {e}")
        return []

def get_categories() -> List[str]:
    try:
        raw = fetch_categories_from_db()
        filtered = [cat for cat in raw if is_valid_category(cat)]
        normalized = [normalize_category(cat) for cat in filtered]
        unique = list(dict.fromkeys(normalized))
        return sort_categories(unique)
    except Exception as e:
        logger.error(f"Erro no pipeline de categorias: {e}")
        return []

def get_services(category_name, limit=15):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT service_id, name, rate, min, max FROM services WHERE category = ? AND rate > 0 ORDER BY rate ASC LIMIT ?",
        (category_name, limit),
    )
    services = cursor.fetchall()
    conn.close()
    return services

def get_service_by_id(service_id):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT service_id, name, rate, min, max, category, provider, description FROM services WHERE service_id = ?",
        (service_id,),
    )
    service = cursor.fetchone()
    conn.close()
    return service

# =========================
# HANDLERS (COM VALIDAÇÕES ADICIONAIS)
# =========================
async def list_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    categories = get_categories()
    if not categories:
        if query:
            await query.answer("Nenhuma categoria disponível no momento.")
        else:
            await update.message.reply_text("⚠️ Nenhum serviço disponível. Tente mais tarde.")
        return ConversationHandler.END

    keyboard = []
    for i in range(0, len(categories), 2):
        cat_name = categories[i]
        callback_id = cat_name[:40]
        row = [InlineKeyboardButton(cat_name, callback_data=f"cat_{callback_id}")]
        if i + 1 < len(categories):
            cat_name2 = categories[i+1]
            callback_id2 = cat_name2[:40]
            row.append(InlineKeyboardButton(cat_name2, callback_data=f"cat_{callback_id2}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu Principal", callback_data="back_to_start")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📦 **ESCOLHA UMA CATEGORIA:**"

    if query:
        await query.answer()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao editar list_services: {e}")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_SERVICE

async def category_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    raw_data = query.data.replace("cat_", "")
    # Remove emoji se existir
    if " " in raw_data[:4]:
        category_partial = raw_data.split(" ", 1)[1]
    else:
        category_partial = raw_data

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT category FROM services WHERE category LIKE ? AND rate > 0",
        (f"%{category_partial}%",)
    )
    res = cursor.fetchone()
    conn.close()
    category = res[0] if res else category_partial

    services = get_services(category)
    if not services:
        await query.edit_message_text("❌ Nenhum serviço disponível nesta categoria.")
        return SELECTING_SERVICE

    keyboard = []
    for s in services:
        # s[1] = name, s[2] = rate (float), s[0] = service_id
        btn_text = f"{s[1]} - R$ {s[2]:.2f}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"serv_{s[0]}")])

    keyboard.append([InlineKeyboardButton("⬅️ Voltar para Categorias", callback_data="back_to_categories")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🚀 **SERVIÇOS: {category.upper()}**"

    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro ao editar category_services: {e}")
    return SELECTING_SERVICE

async def receive_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = query.data.replace("serv_", "")
    service = get_service_by_id(service_id)
    if not service:
        await query.edit_message_text("❌ Serviço não encontrado.")
        return SELECTING_SERVICE

    context.user_data["service_id"] = service[0]
    context.user_data["service_name"] = service[1]
    context.user_data["rate"] = float(service[2])
    context.user_data["min"] = int(service[3])
    context.user_data["max"] = int(service[4])

    text = (
        f"📦 **{service[1]}**\n\n"
        f"💰 Preço por 1000: **R$ {service[2]:.2f}**\n"
        f"📉 Mínimo: `{service[3]}` | 📈 Máximo: `{service[4]}`\n\n"
        f"❓ **Quanto deseja comprar?**\n"
        f"_(Digite apenas o número, ex: 500)_"
    )
    category_raw = service[5] if len(service) > 5 else "back"
    back_callback = f"cat_{category_raw[:40]}"
    keyboard = [[InlineKeyboardButton("⬅️ Escolher outro Serviço", callback_data=back_callback)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ASKING_QUANTITY

async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    text_input = update.message.text.strip()

    if not text_input.isdigit():
        await update.message.reply_text("⚠️ Por favor, digite apenas números (ex: 500).")
        return ASKING_QUANTITY

    quantity = int(text_input)
    rate = user_data.get('rate')
    if rate is None:
        await update.message.reply_text("⚠️ Sessão expirada. Use /comprar novamente.")
        return ConversationHandler.END

    service_min = user_data.get('min', 0)
    service_max = user_data.get('max', 999999)

    if quantity < service_min or quantity > service_max:
        await update.message.reply_text(
            f"❌ **Quantidade Inválida!**\n"
            f"Mínimo: **{service_min}** | Máximo: **{service_max}**\n"
            f"Digite um valor válido:"
        )
        return ASKING_QUANTITY

    total_price = (rate / 1000) * quantity
    user_data['quantity'] = quantity
    user_data['total_price'] = round(total_price, 2)

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar Valor", callback_data="confirm_price"),
            InlineKeyboardButton("❌ Cancelar", callback_data="back_to_categories")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        f"💰 **RESUMO DO VALOR**\n\n"
        f"📦 Serviço: {user_data.get('service_name', 'Serviço')}\n"
        f"🔢 Quantidade: {quantity}\n"
        f"💵 **Total a pagar: R$ {user_data['total_price']:.2f}**\n\n"
        f"Deseja prosseguir para o envio do link?"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return WAIT_CONFIRM_PRICE

async def confirm_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔗 **Envie o link do Perfil ou Post:**\n"
        "_(Certifique-se que o perfil está público)_",
        parse_mode="Markdown"
    )
    return ASKING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not validate_link(link):
        await update.message.reply_text("❌ Link inválido. Envie um URL completo (ex: https://instagram.com/...) ou @usuario.")
        return ASKING_LINK
    context.user_data['link'] = link
    keyboard = [
        [InlineKeyboardButton("🚀 FINALIZAR PEDIDO", callback_data="execute_order")],
        [InlineKeyboardButton("❌ CANCELAR", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        f"⚠️ **CONFIRMAÇÃO FINAL**\n\n"
        f"📦 {context.user_data.get('service_name', 'Serviço')}\n"
        f"🔢 Quantidade: {context.user_data.get('quantity', 0)}\n"
        f"🔗 Link: `{link}`\n"
        f"💰 **Total: R$ {context.user_data.get('total_price', 0):.2f}**\n\n"
        f"Tudo certo com o seu pedido?"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING

async def execute_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Processando pedido...")
    # Chama a função confirm_order já atualizada (centavos)
    return await confirm_order(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Ação cancelada com sucesso.")
    return ConversationHandler.END

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Função auxiliar para voltar à lista de categorias (callback de fallback)"""
    query = update.callback_query
    if query:
        await query.answer()
        return await list_services(update, context)
    else:
        return ConversationHandler.END

async def cancel_to_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Pedido cancelado.")
    return await back_to_categories(update, context)
