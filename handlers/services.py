import logging
import sqlite3
import re
import hashlib
from typing import List, Tuple, Optional
from config import DB_PATH
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

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
    """Gera hash curto para identificação única da categoria + provedor."""
    return hashlib.md5(cat_name.encode()).hexdigest()[:8]

async def safe_edit(query, text: str, reply_markup=None, parse_mode="Markdown"):
    """Edita mensagem com segurança, mesmo se original for foto/caption."""
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
    """Apenas para exibição (adiciona emoji), não altera o nome real."""
    category = category.strip()
    if EMOJI_REGEX.match(category):
        return category
    icon = detect_icon(category)
    return f"{icon} {category}"

def is_valid_category(category: str) -> bool:
    cat_lower = category.lower().strip()
    if not cat_lower or len(cat_lower) < 2:
        return False
    # if any(term in cat_lower for term in FORBIDDEN_TERMS):
    #     return False
    return True

def get_categories() -> List[str]:
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category, provider FROM services WHERE rate > 0")
            rows = cursor.fetchall()
        result = []
        for cat, prov in rows:
            if cat and len(cat.strip()) >= 2:
                clean_cat = cat.strip()
                # Tenta extrair plataforma do primeiro serviço dessa categoria
                cursor.execute("SELECT name FROM services WHERE category = ? AND provider = ? LIMIT 1", (cat, prov))
                serv = cursor.fetchone()
                platform_hint = ""
                if serv:
                    name_lower = serv[0].lower()
                    if "instagram" in name_lower: platform_hint = "📸"
                    elif "tiktok" in name_lower: platform_hint = "🎵"
                    elif "youtube" in name_lower: platform_hint = "▶️"
                    elif "facebook" in name_lower: platform_hint = "👥"
                    elif "kwai" in name_lower: platform_hint = "🎥"
                    elif "telegram" in name_lower: platform_hint = "✈️"
                    # Adicione outros mapeamentos
                display = f"{platform_hint} {clean_cat} [C{prov}]".strip()
                result.append(display)
        return result
    except Exception as e:
        logger.error(f"Erro em get_categories: {e}")
        return []

def get_services(category_name: str, limit: int = 15) -> List[Tuple]:
    """
    Busca serviços de uma categoria em TODOS os provedores.
    Mantida para compatibilidade com buttons.py e outras partes antigas.
    """
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_id, name, rate, min, max, provider
                FROM services
                WHERE category = ? AND rate > 0
                ORDER BY rate ASC
                LIMIT ?
            """, (category_name, limit))
            services = cursor.fetchall()
        logger.info(f"[get_services] Categoria '{category_name}': {len(services)} serviços (todos provedores)")
        return services
    except Exception as e:
        logger.error(f"Erro em get_services para {category_name}: {e}")
        return []

def get_services_by_category_and_provider(category_name: str, provider: int, limit: int = 15) -> List[Tuple]:
    """
    Busca serviços de uma categoria específica de UM provedor.
    """
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_id, name, rate, min, max
                FROM services
                WHERE category = ? AND provider = ? AND rate > 0
                ORDER BY rate ASC
                LIMIT ?
            """, (category_name, provider, limit))
            services = cursor.fetchall()
        logger.info(f"Serviços encontrados para '{category_name}' (C{provider}): {len(services)}")
        return services
    except Exception as e:
        logger.error(f"Erro ao buscar serviços para {category_name} C{provider}: {e}")
        return []

def get_service_by_id(service_id: str) -> Optional[Tuple]:
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_id, name, rate, min, max, category, provider, description
                FROM services
                WHERE service_id = ?
            """, (service_id,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Erro ao buscar serviço {service_id}: {e}")
        return None

# =========================================================
# HANDLERS
# =========================================================
async def list_services(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """
    Exibe o menu de categorias com paginação.
    """
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

    # Configuração da paginação
    ITEMS_PER_PAGE = 20  # 10 linhas de 2 categorias
    total_pages = (len(categories) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(categories))
    page_categories = categories[start_idx:end_idx]

    # Inicializa o mapa de hashes no bot_data
    if 'cat_hash_map' not in context.bot_data:
        context.bot_data['cat_hash_map'] = {}
    cat_hash_map = context.bot_data['cat_hash_map']

    PROVIDER_PATTERN = re.compile(r'\s*\[C(\d+)\]\s*$')

    keyboard = []
    for i in range(0, len(page_categories), 2):
        display_name = page_categories[i]

        match = PROVIDER_PATTERN.search(display_name)
        if not match:
            logger.warning(f"⚠️ Categoria ignorada (regex não casou): '{display_name}'")
            continue

        prov = int(match.group(1))
        real_cat = PROVIDER_PATTERN.sub('', display_name).strip()

        logger.info(f"✅ Processando categoria: '{display_name}' -> real='{real_cat}' prov={prov}")

        hash1 = _get_cat_hash(display_name)
        callback_data1 = f"cat_{hash1}"
        cat_hash_map[callback_data1] = (real_cat, prov)
        row = [InlineKeyboardButton(display_name, callback_data=callback_data1)]

        # Segunda categoria da linha
        if i + 1 < len(page_categories):
            display_name2 = page_categories[i+1]

            match2 = PROVIDER_PATTERN.search(display_name2)
            if not match2:
                logger.warning(f"⚠️ Categoria ignorada (regex não casou): '{display_name2}'")
                continue

            prov2 = int(match2.group(1))
            real_cat2 = PROVIDER_PATTERN.sub('', display_name2).strip()

            logger.info(f"✅ Processando categoria: '{display_name2}' -> real='{real_cat2}' prov={prov2}")

            hash2 = _get_cat_hash(display_name2)
            callback_data2 = f"cat_{hash2}"
            cat_hash_map[callback_data2] = (real_cat2, prov2)
            row.append(InlineKeyboardButton(display_name2, callback_data=callback_data2))

        keyboard.append(row)

    # Botões de navegação
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("« Anterior", callback_data=f"catpage_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Próximo »", callback_data=f"catpage_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu Principal", callback_data="back_to_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f"📦 **ESCOLHA UMA CATEGORIA:**\n_(Página {page+1}/{total_pages})_"

    # Armazena a página atual no user_data para possível retorno
    context.user_data['current_category_page'] = page

    if query:
        await safe_edit(query, text, reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_SERVICE

async def category_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe os serviços disponíveis para a categoria + provedor selecionados."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    cat_hash_map = context.bot_data.get('cat_hash_map', {})
    info = cat_hash_map.get(query.data)
    if not info:
        logger.warning(f"Callback {query.data} não encontrado no cat_hash_map")
        await safe_edit(query, "❌ Categoria inválida. Use /comprar novamente.", None)
        return SELECTING_SERVICE

    real_category, provider = info
    logger.info(f"Categoria selecionada: '{real_category}' (C{provider})")

    services = get_services_by_category_and_provider(real_category, provider)

    if not services:
        logger.warning(f"Nenhum serviço encontrado para {real_category} C{provider}")
        await safe_edit(query, f"❌ Nenhum serviço disponível em **{real_category} [C{provider}]** no momento.", None)
        return SELECTING_SERVICE

    keyboard = []
    for s in services:
        # s[1] = name, s[2] = rate
        btn_text = f"{s[1]} - R$ {s[2]:.2f}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"serv_{s[0]}")])

    keyboard.append([InlineKeyboardButton("⬅️ Voltar para Categorias", callback_data="back_to_categories")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🚀 **SERVIÇOS: {real_category} [C{provider}]**"

    await safe_edit(query, text, reply_markup)
    return SELECTING_SERVICE

async def category_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Navegação entre páginas de categorias."""
    query = update.callback_query
    await query.answer()
    page = int(query.data.split('_')[1])
    return await list_services(update, context, page=page)

async def receive_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a escolha de um serviço específico e mostra detalhes."""
    query = update.callback_query
    await query.answer()
    service_id = query.data.replace("serv_", "")
    service = get_service_by_id(service_id)
    if not service:
        await safe_edit(query, "❌ Serviço não encontrado.", None)
        return SELECTING_SERVICE

    # Armazena dados do serviço no user_data
    context.user_data["service_id"] = service[0]
    context.user_data["service_name"] = service[1]
    context.user_data["rate"] = float(service[2])
    context.user_data["min"] = int(service[3])
    context.user_data["max"] = int(service[4])
    context.user_data["provider_id"] = service[6]  # índice 6 = provider
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

    # Salva a categoria original para possível volta
    context.user_data["service_category"] = service[5] if len(service) > 5 else ""

    await safe_edit(query, text, reply_markup)
    return WAIT_CONFIRM_PRICE

async def proceed_to_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita ao usuário a quantidade desejada."""
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
    """Valida a quantidade digitada e calcula o preço total."""
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
    """Avança para solicitação do link."""
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "🔗 **Envie o link do Perfil ou Post:**\n_(Certifique-se que o perfil está público)_")
    return ASKING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o link e pede confirmação final."""
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
    """Encaminha para a função de finalização do pedido."""
    query = update.callback_query
    await query.answer("Processando pedido...")
    # Importação local para evitar circularidade
    from handlers.orders import confirm_order
    return await confirm_order(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela a operação atual."""
    await update.message.reply_text("❌ Ação cancelada com sucesso.")
    return ConversationHandler.END

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retorna ao menu de categorias, lembrando a última página."""
    query = update.callback_query
    if query:
        await query.answer()
        page = context.user_data.get('current_category_page', 0)
        return await list_services(update, context, page=page)
    return ConversationHandler.END

async def cancel_to_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela pedido e volta às categorias."""
    query = update.callback_query
    await query.answer("Pedido cancelado.")
    return await back_to_categories(update, context)
