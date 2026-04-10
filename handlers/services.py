import logging
import sqlite3
import re
import hashlib
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
    #if any(term in cat_lower for term in FORBIDDEN_TERMS):
        #return False
    return True

# =========================
# DATABASE LAYER (ATUALIZADO COM FALLBACK)
# =========================
def fetch_categories_from_db() -> List[str]:
    """Busca categorias diretamente da tabela services, sem depender de providers_status."""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category FROM services WHERE rate > 0")
            rows = cursor.fetchall()
            return [row[0] for row in rows if row and row[0]]
    except Exception as e:
        logger.error(f"Erro ao buscar categorias: {e}")
        return []

def get_categories() -> List[str]:
    """Retorna categorias reais do banco (sem normalização que altera o texto)."""
    try:
        raw = fetch_categories_from_db()
        # Filtro mínimo: apenas categorias não vazias e com pelo menos 2 caracteres
        filtered = [cat for cat in raw if cat and len(cat.strip()) >= 2]
        # Remove duplicatas mantendo ordem
        unique = list(dict.fromkeys(filtered))
        return unique  # sem ordenação por emoji (opcional, mas pode manter)
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

def _get_cat_hash(cat_name: str) -> str:
    """Gera um hash curto de 8 caracteres a partir do nome da categoria."""
    return hashlib.md5(cat_name.encode()).hexdigest()[:8]

# =========================
# HANDLERS (COM VALIDAÇÕES ADICIONAIS)
# =========================
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

    # Armazena a lista real de categorias (sem emojis)
    context.bot_data['categories_list'] = categories

    keyboard = []
    for i in range(0, len(categories), 2):
        cat_name = categories[i]
        # Adiciona emoji apenas para exibição (opcional)
        display_name = normalize_category(cat_name)  # apenas para o texto do botão
        callback_data = f"cat_{cat_name[:50]}"  # usa o nome real, mas truncado (ainda pode ser longo)
        # Mas para evitar problemas de tamanho, use hash do nome real
        cat_hash = hashlib.md5(cat_name.encode()).hexdigest()[:8]
        callback_data = f"cat_{cat_hash}"
        context.bot_data['cat_hash_map'][callback_data] = cat_name
        row = [InlineKeyboardButton(display_name, callback_data=callback_data)]
        if i + 1 < len(categories):
            cat_name2 = categories[i+1]
            display_name2 = normalize_category(cat_name2)
            hash2 = hashlib.md5(cat_name2.encode()).hexdigest()[:8]
            callback_data2 = f"cat_{hash2}"
            context.bot_data['cat_hash_map'][callback_data2] = cat_name2
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
    category_name = cat_hash_map.get(query.data)
    if not category_name:
        await safe_edit(query, "❌ Categoria inválida. Use /comprar novamente.", None)
        return SELECTING_SERVICE

    services = get_services(category_name)  # agora usa o nome real
    if not services:
        await safe_edit(query, "❌ Nenhum serviço disponível nesta categoria.", None)
        return SELECTING_SERVICE

    keyboard = []
    for s in services:
        btn_text = f"{s[1]} - R$ {s[2]:.2f}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"serv_{s[0]}")])

    keyboard.append([InlineKeyboardButton("⬅️ Voltar para Categorias", callback_data="back_to_categories")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🚀 **SERVIÇOS: {category_name}**"  # exibe o nome real

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

    text = (
        f"📦 **{service[1]}**\n\n"
        f"💰 Preço por 1000: **R$ {service[2]:.2f}**\n"
        f"📉 Mínimo: `{service[3]}` | 📈 Máximo: `{service[4]}`\n\n"
        f"❓ **Quanto deseja comprar?**\n"
        f"_(Digite apenas o número, ex: 500)_"
    )
    category_raw = service[5] if len(service) > 5 else "back"
    # Gera hash da categoria para o callback (seguro)
    back_hash = _get_cat_hash(category_raw)
    back_callback = f"cat_{back_hash}"
    # Armazena o nome da categoria no mapeamento global (caso não exista)
    if 'cat_hash_map' not in context.bot_data:
        context.bot_data['cat_hash_map'] = {}
    context.bot_data['cat_hash_map'][back_callback] = category_raw

    keyboard = [[InlineKeyboardButton("⬅️ Escolher outro Serviço", callback_data=back_callback)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Usa safe_edit para garantir que a edição funcione (texto ou legenda)
    await safe_edit(query, text, reply_markup)
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

