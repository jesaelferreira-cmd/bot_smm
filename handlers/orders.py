import requests
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database.connection import get_connection  # caminho padronizado

logger = logging.getLogger(__name__)

def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_id = update.effective_user.id

    query = update.callback_query
    if query:
        await query.answer("Processando pedido...")
        message = query.message
    else:
        message = update.message

    if 'service_id' not in user_data:
        await message.reply_text("❌ Sessão expirada. Use /comprar novamente.")
        return ConversationHandler.END

    total_price_float = user_data['total_price']
    total_price_cents = float_to_cents(total_price_float)

    provider_id = user_data.get('provider_id', 1)
    if provider_id == 1:
        api_url = SMM_API_URL_1
        api_key = SMM_API_KEY_1
    else:
        api_url = SMM_API_URL_2
        api_key = SMM_API_KEY_2

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Débito em centavos na coluna balance
        cursor.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s AND balance >= %s",
            (total_price_cents, user_id, total_price_cents)
        )
        if cursor.rowcount == 0:
            keyboard = [[InlineKeyboardButton("💳 Adicionar Saldo (PIX)", callback_data="add_balance")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                f"❌ **Saldo Insuficiente!**\n\nO pedido custa R$ {total_price_float:.2f}. Deseja recarregar?",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            conn.close()
            return ConversationHandler.END

        payload = {
            'key': api_key,
            'action': 'add',
            'service': user_data['service_id'],
            'link': user_data['link'],
            'quantity': user_data['quantity']
        }
        res = requests.post(api_url, data=payload, timeout=20)
        response = res.json()

        if 'order' in response:
            order_id_api = response['order']
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
            cursor.execute(
                "INSERT INTO orders (user_id, service_name, quantity, price, order_id_api, status, date, provider_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, user_data['service_name'], user_data['quantity'], total_price_cents,
                 order_id_api, "Pendente", data_atual, provider_id)
            )
            conn.commit()
            keyboard = [
                [InlineKeyboardButton("📊 Status do Pedido", callback_data=f"status_{order_id_api}"),
                 InlineKeyboardButton("📜 Meus Pedidos", callback_data="my_orders")],
                [InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg_sucesso = (
                f"✅ **PEDIDO ENVIADO!**\n"
                f"🆔 ID: `{order_id_api}`\n"
                f"💰 R$ {total_price_float:.2f}\n"
                f"📅 {data_atual}"
            )
            if query:
                await query.edit_message_text(msg_sucesso, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await message.reply_text(msg_sucesso, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            # Estorna o saldo em centavos
            cursor.execute(
                "UPDATE users SET balance = balance + %s WHERE user_id = %s",
                (total_price_cents, user_id)
            )
            conn.commit()
            error_msg = response.get('error', 'Erro desconhecido')
            await message.reply_text(f"❌ Erro no provedor: {error_msg}\nSaldo estornado.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no pedido: {e}")
        await message.reply_text("⚠️ Erro interno. Tente novamente.")
    finally:
        conn.close()
    return ConversationHandler.END
