import asyncio
import aiohttp
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
    from config import SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2
    if provider_id == 1:
        return SMM_API_URL_1, SMM_API_KEY_1
    elif provider_id == 2:
        return SMM_API_URL_2, SMM_API_KEY_2
    else:
        logger.warning(f"Provedor desconhecido: {provider_id}")
        return None, None

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os últimos pedidos com status atualizado via API."""
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    # Mensagem de carregamento
    if query:
        try:
            await query.edit_message_text("⏳ Consultando status dos seus pedidos...")
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Busca os últimos 10 pedidos
    cursor.execute("""
        SELECT order_id_api, service_name, amount_cents, date, status, COALESCE(provider_id, 1) as provider_id
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,))
    orders = cursor.fetchall()

    if not orders:
        text = "📭 **Nenhum pedido encontrado.**"
        keyboard = [[InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if query:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        conn.close()
        return

    updated_orders = []
    async with aiohttp.ClientSession() as session:
        for order in orders:
            order_id, service_name, amount_cents, date_str, current_status, provider_id = order
            amount_float = amount_cents / 100.0 if amount_cents else 0.0

            # Determina se precisa consultar a API (status que podem mudar)
            should_check = current_status in ["Pendente", "Em andamento", "Processing", "In Progress", None]
            new_status = current_status if current_status else "Pendente"

            if should_check and provider_id and order_id:
                api_url, api_key = get_provider_credentials(provider_id)
                if api_url and api_key:
                    logger.info(f"🔍 Consultando status do pedido {order_id} (provedor {provider_id})")
                    payload = {'key': api_key, 'action': 'status', 'order': order_id}
                    try:
                        async with session.post(api_url, data=payload, timeout=15) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                logger.info(f"📦 Resposta API pedido {order_id}: {data}")
                                if 'status' in data:
                                    raw_status = str(data['status']).title()
                                    status_map = {
                                        'Pending': 'Pendente',
                                        'In Progress': 'Em andamento',
                                        'Completed': 'Concluído',
                                        'Partial': 'Parcial',
                                        'Canceled': 'Cancelado',
                                        'Cancelled': 'Cancelado',
                                        'Processing': 'Processando'
                                    }
                                    new_status = status_map.get(raw_status, raw_status)

                                    # Atualiza no banco se o status mudou
                                    if new_status != current_status:
                                        cursor.execute(
                                            "UPDATE orders SET status = ? WHERE order_id_api = ?",
                                            (new_status, order_id)
                                        )
                                        conn.commit()
                                        logger.info(f"✅ Status do pedido {order_id} atualizado para '{new_status}'")
                            else:
                                logger.warning(f"⚠️ HTTP {resp.status} ao consultar pedido {order_id}")
                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout ao consultar pedido {order_id}")
                    except Exception as e:
                        logger.error(f"❌ Erro ao consultar pedido {order_id}: {e}")
                else:
                    logger.warning(f"🔑 Credenciais ausentes para provedor {provider_id} (pedido {order_id})")

            # Emoji conforme o status final
            status_emoji = {
                'Concluído': '✅',
                'Cancelado': '❌',
                'Estornado': '❌',
                'Pendente': '⏳',
                'Em andamento': '🔄',
                'Processando': '⚙️',
                'Parcial': '⚠️'
            }.get(new_status, '⏳')

            updated_orders.append({
                'order_id': order_id,
                'service_name': service_name,
                'amount': amount_float,
                'date': date_str,
                'status': new_status,
                'emoji': status_emoji,
                'provider': provider_id
            })

    conn.close()

    # Monta a mensagem
    text = "📋 **SEUS ÚLTIMOS PEDIDOS**\n\n"
    for o in updated_orders:
        order_id_display = o['order_id'] if o['order_id'] else "N/A"
        text += (
            f"{o['emoji']} **ID:** `{order_id_display}` (C{o['provider']})\n"
            f"📦 {o['service_name']}\n"
            f"💰 R$ {o['amount']:.2f} | 📅 {o['date']}\n"
            f"📌 Status: **{o['status']}**\n\n"
        )

    keyboard = [
        [InlineKeyboardButton("🔄 Atualizar", callback_data="my_history")],
        [InlineKeyboardButton("🛍️ Ir para Loja", callback_data="back_to_categories")],
        [InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao editar mensagem do histórico: {e}")
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
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

            # ========== CÁLCULO DE PROGRESSO ==========
            progress_text = ""
            status_hint = ""
            try:
                remains_int = int(remains) if remains != 'N/A' else None
                start_int = int(start_count) if start_count != 'N/A' else None
            except (ValueError, TypeError):
                remains_int = None
                start_int = None

            if raw_status == 'Pending':
                status_hint = " (aguardando início)"
            elif raw_status == 'In Progress':
                status_hint = " (entrega em andamento)"
            elif raw_status == 'Completed':
                status_hint = " (pedido finalizado)"
            elif raw_status in ['Canceled', 'Cancelled']:
                status_hint = " (reembolsado)"
            elif raw_status == 'Partial':
                status_hint = " (parcialmente concluído)"

            if remains_int is not None and start_int is not None and start_int > 0:
                delivered = start_int - remains_int
                percent = (delivered / start_int) * 100 if start_int > 0 else 0
                filled = int(percent / 10)
                empty = 10 - filled
                bar = "█" * filled + "▒" * empty
                progress_text = (
                    f"📈 **Progresso:** {bar} {percent:.1f}%\n"
                    f"✅ **Entregue:** {delivered} / {start_int}\n"
                )
            elif remains_int is not None:
                progress_text = f"⏳ **Restante:** {remains_int}\n"
            else:
                progress_text = f"📦 **Restante:** {remains}\n"

            # Monta a mensagem final
            msg = (
                f"📊 **STATUS DO PEDIDO**\n\n"
                f"🆔 `{order_id}` | {service_name}\n"
                f"📌 **Status:** {display_status}{status_hint}\n"
                f"{progress_text}"
                f"🚀 **Início:** {start_count if start_count != 'N/A' else 'Aguardando'}\n"
                f"💰 **Valor:** R$ {amount_float:.2f}"
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
