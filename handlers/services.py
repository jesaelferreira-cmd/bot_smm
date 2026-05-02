import logging
import re
import hashlib
from typing import List, Tuple, Optional
from config import DB_PATH
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from database import get_connection

logger = logging.getLogger(__name__)

# =========================================================
# ESTADOS DO CONVERSATION HANDLER
# =========================================================
(
    SELECTING_SERVICE,    # 0
    ASKING_QUANTITY,      # 1
    WAIT_CONFIRM_PRICE,   # 2
    ASKING_LINK,          # 3
    CONFIRMING            # 4
) = range(5)

# =========================================================
# CONFIGURAÇÕES GLOBAIS
# =========================================================
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
EMOJI_REGEX = re.compile(r'^[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]')

# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================
def _get_cat_hash(cat_name: str) -> str:
    return hashlib.md5(cat_name.encode()).hexdigest()[:8]

async def safe_edit(query, text: str, reply_markup=None, parse_mode="Markdown"):
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

def detect_icon(category: str) -> str:
    cat_lower = category.lower()
    return next((icon for key, icon in ICONS_MAP.items() if key in cat_lower), "🚀")

def normalize_category(category: str) -> str:
    category = category.strip()
    if EMOJI_REGEX.match(category):
        return category
    icon = detect_icon(category)
    return f"{icon} {category}"

def is_valid_category(category: str) -> bool:
    cat_lower = category.lower().strip()
    if not cat_lower or len(cat_lower) < 2:
        return False
    return True

def get_categories() -> List[str]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT category, provider
            FROM services
            WHERE rate > 0
            ORDER BY category, provider
        """)
        rows = cursor.fetchall()
        forbidden_keywords = ["privado para api", "privado para aplicativo", "não utilize"]
        result = []
        for cat, prov in rows:
            if not cat or len(cat.strip()) < 2:
                continue
            cat_lower = cat.lower()
            if any(keyword in cat_lower for keyword in forbidden_keywords):
                continue
            clean_cat = cat.strip()
            # Tenta extrair plataforma
            platform = "🚀"
            if "instagram" in cat_lower:
                platform = "📸"
            elif "tiktok" in cat_lower:
                platform = "🎵"
            elif "youtube" in cat_lower:
                platform = "▶️"
            elif "facebook" in cat_lower:
                platform = "👥"
            elif "kwai" in cat_lower:
                platform = "🎥"
            elif "telegram" in cat_lower:
                platform = "✈️"
            elif "twitter" in cat_lower or "x" in cat_lower:
                platform = "🐦"
            elif "whatsapp" in cat_lower:
                platform = "📞"
            elif "twitch" in cat_lower:
                platform = "🟣"
            elif "pinterest" in cat_lower:
                platform = "📌"
            elif "linkedin" in cat_lower:
                platform = "💼"
            elif "reddit" in cat_lower:
                platform = "🤖"
            elif "bluesky" in cat_lower:
                platform = "🦋"
            elif "threads" in cat_lower:
                platform = "💬"
            elif "discord" in cat_lower:
                platform = "🎮"
            display = f"{platform} {clean_cat} [C{prov}]".strip()
            result.append(display)
        return result
    except Exception as e:
        logger.error(f"Erro em get_categories: {e}")
        return []
    finally:
        conn.close()

def get_services_by_category_and_provider(category_name: str, provider: int, limit: int = 15) -> List[Tuple]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT service_id, name, rate, min, max
            FROM services
            WHERE category = %s AND provider = %s AND rate > 0
            ORDER BY rate ASC
            LIMIT %s
        """, (category_name, provider, limit))
        services = cursor.fetchall()
        return services
    except Exception as e:
        logger.error(f"Erro ao buscar serviços para {category_name} C{provider}: {e}")
        return []
    finally:
        conn.close()

def get_service_by_id(service_id: str) -> Optional[Tuple]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT service_id, name, rate, min, max, category, provider, description
            FROM services
            WHERE service_id = %s
        """, (service_id,))
        return cursor.fetchone()
    except Exception as e:
        logger.error(f"Erro ao buscar serviço {service_id}: {e}")
        return None
    finally:
        conn.close()

# =========================================================
# HANDLERS
# =========================================================
async def list_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    categories = get_categories()
    if not categories:
        if query:
            await safe_edit(query, "⚠️ Nenhuma categoria disponível no momento.", None)
        else:
            await update.message.reply_text("⚠️ Nenhum serviço disponível. Tente mais tarde.")
        return ConversationHandler.END

    if 'cat_hash_map' not in context.bot_data:
        context.bot_data['cat_hash_map'] = {}
    cat_hash_map = context.bot_data['cat_hash_map']

    PROVIDER_PATTERN = re.compile(r'\s*\[C(\d+)\]\s*$')
    keyboard = []
    for i in range(0, len(categories), 2):
        display_name = categories[i]
        match = PROVIDER_PATTERN.search(display_name)
        if not match:
            continue
        prov = int(match.group(1))
        real_cat = PROVIDER_PATTERN.sub('', display_name).strip()
        hash1 = _get_cat_hash(display_name)
        callback_data1 = f"cat_{hash1}"
        cat_hash_map[callback_data1] = (real_cat, prov)
        row = [InlineKeyboardButton(display_name, callback_data=callback_data1)]
        if i + 1 < len(categories):
            display_name2 = categories[i+1]
            match2 = PROVIDER_PATTERN.search(display_name2)
            if match2:
                prov2 = int(match2.group(1))
                real_cat2 = PROVIDER_PATTERN.sub('', display_name2).strip()
                hash2 = _get_cat_hash(display_name2)
                callback_data2 = f"cat_{hash2}"
                cat_hash_map[callback_data2] = (real_cat2, prov2)
                row.append(InlineKeyboardButton(display_name2, callback_data=callback_data2))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu Principal", callback_data="back_to_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📦 **ESCOLHA UMA CATEGORIA:**"

    if query:
        await safe_edit(query, text, reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_SERVICE

async def category_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    cat_hash_map = context.bot_data.get('cat_hash_map', {})
    info = cat_hash_map.get(query.data)
    if not info:
        await safe_edit(query, "❌ Categoria inválida. Use /comprar novamente.", None)
        return SELECTING_SERVICE

    real_category, provider = info
    services = get_services_by_category_and_provider(real_category, provider)
    if not services:
        await safe_edit(query, "❌ Nenhum serviço disponível nesta categoria.", None)
        return SELECTING_SERVICE

    keyboard = []
    for s in services:
        btn_text = f"{s[1]} - R$ {s[2]:.2f}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"serv_{s[0]}")])
    keyboard.append([InlineKeyboardButton("⬅️ Voltar para Categorias", callback_data="back_to_categories")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🚀 **SERVIÇOS: {real_category} [C{provider}]**"
    await safe_edit(query, text, reply_markup)
    return SELECTING_SERVICE

async def receive_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = query.data.replace("serv_", "")
    service = get_service_by_id(service_id)
    if not service:
        await safe_edit(query, "❌ Serviço não encontrado.", None)
        return SELECTING_SERVICE

    context.user_data["service_id"] = service[0]
    context.user_data["service_name"] = service[1]
    context.user_data["rate"] = float(service[2])
    context.user_data["min"] = int(service[3])
    context.user_data["max"] = int(service[4])
    context.user_data["provider_id"] = service[6]
    context.user_data["description"] = service[7] if len(service) > 7 else ""

    desc_text = context.user_data["description"]
    if not desc_text or desc_text.strip() == "":
        desc_text = "Sem descrição disponível."

    text = (
        f"📦 **{service[1]}**\n\n"
        f"💰 Preço por 1000: **R$ {service[2]:.2f}**\n"
        f"📉 Mínimo: `{service[3]}` | 📈 Máximo: `{service[4]}`\n"
        f"📝 **Descrição:** {desc_text}\n\n"
        f"❓ Deseja comprar este serviço?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Sim, escolher quantidade", callback_data="proceed_quantity"),
            InlineKeyboardButton("⬅️ Voltar", callback_data="back_to_categories")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data["service_category"] = service[5] if len(service) > 5 else ""
    await safe_edit(query, text, reply_markup)
    return WAIT_CONFIRM_PRICE

async def proceed_to_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        f"📦 **{context.user_data['service_name']}**\n\n"
        f"❓ **Quanto deseja comprar?**\n"
        f"_(Digite apenas o número, ex: 500)_"
    )
    await safe_edit(query, text, None)
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
            f"❌ **Quantidade Inválida!**\nMínimo: **{service_min}** | Máximo: **{service_max}**\nDigite um valor válido:"
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
    await safe_edit(query, "🔗 **Envie o link do Perfil ou Post:**\n_(Certifique-se que o perfil está público)_")
    return ASKING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
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
    from handlers.orders import confirm_order
    return await confirm_order(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Ação cancelada com sucesso.")
    return ConversationHandler.END

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        return await list_services(update, context)
    return ConversationHandler.END

async def cancel_to_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Pedido cancelado.")
    return await back_to_categories(update, context)
