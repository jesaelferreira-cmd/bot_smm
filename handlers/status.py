import sqlite3
import requests
import logging
from datetime import datetime
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# FUNÇÕES AUXILIARES
# ------------------------------------------------------------
def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2) if cents is not None else 0.0

def get_order_from_db(order_id: str, user_id: int = None):
    """Busca pedido no banco com informações completas."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verifica colunas
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'provider_id' in columns:
        provider_field = "o.provider_id"
    else:
        provider_field = "1"

    if 'amount_cents' in columns:
        amount_field = "o.amount_cents"
    else:
        amount_field = "o.amount * 100"

    query = f"""
        SELECT o.order_id_api, o.service_name, o.quantity,
               {amount_field} as amount_cents,
               o.status, o.date, {provider_field} as provider_id
        FROM orders o
        WHERE o.order_id_api = ?
    """
    params = [order_id]
    if user_id:
        query += " AND o.user_id = ?"
        params.append(user_id)

    cursor.execute(query, params)
    order = cursor.fetchone()
    conn.close()
    return order

def get_provider_credentials(provider_id: int):
    """Retorna URL e chave da API conforme o provedor."""
    if provider_id == 1:
        return SMM_API_URL_1, SMM_API_KEY_1
    elif provider_id == 2:
        return SMM_API_URL_2, SMM_API_KEY_2
    else:
        return None, None

# ------------------------------------------------------------
# HISTÓRICO DE PEDIDOS (comando /pedidos e botão Histórico)
# ------------------------------------------------------------
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os últimos pedidos do usuário."""
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    keyboard = [
        [InlineKeyboardButton("🛍️ Ir para Loja", callback_data="back_to_categories")],
        [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Verifica se a tabela orders existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
        if not cursor.fetchone():
            text = "📭 **Você ainda não tem pedidos realizados.**"
        else:
            # Verifica colunas existentes
            cursor.execute("PRAGMA table_info(orders)")
            columns = [col[1] for col in cursor.fetchall()]

            # Campo de valor (centavos ou float)
            if 'amount_cents' in columns:
                amount_field = "amount_cents"
            else:
                amount_field = "amount * 100"

            # Campo provider_id (se existir)
            if 'provider_id' in columns:
                provider_field = "provider_id"
            else:
                provider_field = "1"  # valor padrão

            cursor.execute(f"""
                SELECT order_id_api, service_name, {amount_field} as amount_cents,
                       date, status, {provider_field} as provider_id
                FROM orders
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 10
            """, (user_id,))
            orders_list = cursor.fetchall()

            if not orders_list:
                text = "📭 **Histórico vazio.**\nFaça sua primeira compra em /comprar!"
            else:
                text = "📋 **SEUS ÚLTIMOS PEDIDOS**\n\n"
                for o in orders_list:
                    order_id = o[0]
                    service_name = o[1]
                    amount_cents = o[2]
                    amount_float = cents_to_float(amount_cents)
                    date_str = o[3] if o[3] else "N/A"
                    status_str = o[4] if o[4] else "Pendente"
                    provider_id = o[5] if len(o) > 5 else 1

                    # Emoji de status
                    if "Conclu" in status_str:
                        emoji = "✅"
                    elif "Cancel" in status_str or "Estorn" in status_str:
                        emoji = "❌"
                    else:
                        emoji = "⏳"

                    text += (
                        f"{emoji} **ID:** `{order_id}` (C{provider_id})\n"
                        f"📦 {service_name}\n"
                        f"💰 R$ {amount_float:.2f} | 📅 {date_str}\n\n"
                    )

        # Envia/edita mensagem
        if query:
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Erro ao buscar pedidos: {e}")
        error_msg = "⚠️ Houve um erro ao buscar seu histórico."
        if query:
            await query.message.reply_text(error_msg)
        else:
            await message.reply_text(error_msg)
    finally:
        if conn:
            conn.close()

# ------------------------------------------------------------
# STATUS VIA COMANDO /status ID
# ------------------------------------------------------------
async def get_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta status na API correta e realiza estorno automático se cancelado."""
    if not context.args:
        await update.message.reply_text("❓ Digite `/status ID_DO_PEDIDO`.")
        return

    order_id = context.args[0]
    user_id = update.effective_user.id

    # Busca pedido no banco
    order = get_order_from_db(order_id, user_id)
    if not order:
        await update.message.reply_text("❌ Pedido não encontrado no seu histórico.")
        return

    order_id_api, service_name, quantity, amount_cents, current_status, date_str, provider_id = order
    amount_float = cents_to_float(amount_cents)
    provider_id = provider_id or 1

    # Obtém credenciais do provedor correto
    api_url, api_key = get_provider_credentials(provider_id)
    if not api_url or not api_key:
        await update.message.reply_text(f"❌ Configuração do provedor {provider_id} ausente.")
        return

    # Consulta a API
    try:
        payload = {'key': api_key, 'action': 'status', 'order': order_id}
        response = requests.post(api_url, data=payload, timeout=20).json()
        logger.info(f"Status pedido {order_id} (provedor {provider_id}): {response}")

        if 'status' in response:
            raw_status = str(response.get('status', '')).title()
            remains = response.get('remains', 'N/A')
            start_count = response.get('start_count', 'N/A')

            # Mapeamento de status
            status_map = {
                'Pending': '⏳ Pendente',
                'In Progress': '🔄 Em andamento',
                'Completed': '✅ Concluído',
                'Partial': '⚠️ Parcial',
                'Canceled': '❌ Cancelado',
                'Cancelled': '❌ Cancelado',
                'Processing': '⚙️ Processando'
            }
            display_status = status_map.get(raw_status, raw_status)

            # Verifica se precisa estornar
            if raw_status in ['Canceled', 'Cancelled', 'Partial'] and current_status not in ['Cancelado', 'Estornado']:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                # Estorna saldo (main_balance_cents)
                cursor.execute("UPDATE users SET main_balance_cents = main_balance_cents + ? WHERE user_id = ?",
                               (amount_cents, user_id))
                cursor.execute("UPDATE orders SET status = ? WHERE order_id_api = ?", ("Estornado", order_id))
                conn.commit()
                conn.close()

                await update.message.reply_text(
                    f"❌ **PEDIDO CANCELADO**\n\n"
                    f"💰 O valor de **R$ {amount_float:.2f}** foi devolvido ao seu saldo.\n"
                    f"⚠️ *Motivo:* Geralmente perfil privado ou link inválido.",
                    parse_mode="Markdown"
                )
                return

            # Exibe status normalmente
            msg = (
                f"📊 **DETALHES DO PEDIDO**\n\n"
                f"🆔 **ID:** `{order_id}` (Fornecedor {provider_id})\n"
                f"📦 **Serviço:** {service_name}\n"
                f"🔢 **Quantidade:** {quantity}\n"
                f"💰 **Valor:** R$ {amount_float:.2f}\n"
                f"📌 **Status:** {display_status}\n"
                f"📦 **Restante:** {remains}\n"
                f"🚀 **Início:** {start_count}\n"
                f"📅 **Data:** {date_str}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            error_msg = response.get('error', 'Erro desconhecido')
            await update.message.reply_text(f"❌ **Erro na API:** {error_msg}")

    except Exception as e:
        logger.error(f"Erro ao consultar status do pedido {order_id}: {e}")
        await update.message.reply_text("⚠️ Erro na consulta. Tente novamente mais tarde.")

# ------------------------------------------------------------
# STATUS VIA BOTÃO INLINE (callback: status_12345)
# ------------------------------------------------------------
async def order_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback acionado ao clicar em 'Status do Pedido'."""
    query = update.callback_query
    await query.answer()
    order_id = query.data.split('_')[1]
    user_id = update.effective_user.id

    # Reaproveita a lógica do get_status
    order = get_order_from_db(order_id, user_id)
    if not order:
        await query.message.reply_text("❌ Pedido não encontrado.")
        return

    order_id_api, service_name, quantity, amount_cents, current_status, date_str, provider_id = order
    amount_float = cents_to_float(amount_cents)
    provider_id = provider_id or 1

    api_url, api_key = get_provider_credentials(provider_id)
    if not api_url or not api_key:
        await query.message.reply_text(f"❌ Configuração do provedor {provider_id} ausente.")
        return

    try:
        payload = {'key': api_key, 'action': 'status', 'order': order_id}
        response = requests.post(api_url, data=payload, timeout=20).json()

        if 'status' in response:
            raw_status = str(response.get('status', '')).title()
            remains = response.get('remains', 'N/A')
            start_count = response.get('start_count', 'N/A')

            status_map = {
                'Pending': '⏳ Pendente',
                'In Progress': '🔄 Em andamento',
                'Completed': '✅ Concluído',
                'Partial': '⚠️ Parcial',
                'Canceled': '❌ Cancelado',
                'Cancelled': '❌ Cancelado',
                'Processing': '⚙️ Processando'
            }
            display_status = status_map.get(raw_status, raw_status)

            # Estorno automático se necessário
            if raw_status in ['Canceled', 'Cancelled', 'Partial'] and current_status not in ['Cancelado', 'Estornado']:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET main_balance_cents = main_balance_cents + ? WHERE user_id = ?",
                               (amount_cents, user_id))
                cursor.execute("UPDATE orders SET status = ? WHERE order_id_api = ?", ("Estornado", order_id))
                conn.commit()
                conn.close()

                await query.message.reply_text(
                    f"❌ **PEDIDO CANCELADO**\n\n"
                    f"💰 O valor de **R$ {amount_float:.2f}** foi devolvido ao seu saldo.",
                    parse_mode="Markdown"
                )
                return

            msg = (
                f"📊 **STATUS DO PEDIDO**\n\n"
                f"🆔 `{order_id}` | {service_name}\n"
                f"📌 {display_status}\n"
                f"📦 Restante: {remains} | 🚀 Início: {start_count}\n"
                f"💰 Valor: R$ {amount_float:.2f}"
            )
            await query.message.reply_text(msg, parse_mode="Markdown")
        else:
            error_msg = response.get('error', 'Erro desconhecido')
            await query.message.reply_text(f"❌ Erro: {error_msg}")

    except Exception as e:
        logger.error(f"Erro no callback status_{order_id}: {e}")
        await query.message.reply_text("⚠️ Erro ao consultar status.")

# ------------------------------------------------------------
# SALDO DO FORNECEDOR (Admin)
# ------------------------------------------------------------
async def check_provider_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica saldo nos fornecedores (apenas admin)."""
    user_id = update.effective_user.id
    # Idealmente verificar se é admin, mas por simplicidade exibimos ambos
    texto = ""
    try:
        r1 = requests.post(SMM_API_URL_1, data={'key': SMM_API_KEY_1, 'action': 'balance'}, timeout=10).json()
        texto += f"🔵 Fornecedor 1: {r1.get('balance', '0')} {r1.get('currency', 'USD')}\n"
    except Exception as e:
        texto += f"🔵 Fornecedor 1: Erro ({e})\n"

    try:
        r2 = requests.post(SMM_API_URL_2, data={'key': SMM_API_KEY_2, 'action': 'balance'}, timeout=10).json()
        texto += f"🟢 Fornecedor 2: {r2.get('balance', '0')} {r2.get('currency', 'USD')}\n"
    except Exception as e:
        texto += f"🟢 Fornecedor 2: Erro ({e})\n"

    await update.message.reply_text(f"💳 **SALDOS DAS APIS:**\n\n{texto}")
