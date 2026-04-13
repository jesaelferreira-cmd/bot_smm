import requests
import sqlite3
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# FUNÇÕES AUXILIARES (centavos)
# ------------------------------------------------------------
def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

# ------------------------------------------------------------
# CONFIRMAÇÃO DO PEDIDO (com débito em centavos)
# ------------------------------------------------------------
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_id = update.effective_user.id

    query = update.callback_query
    if query:
        await query.answer("Processando pedido...")
        message = query.message
    else:
        message = update.message

    # Verificações básicas
    if 'service_id' not in user_data:
        logger.error("service_id não encontrado no user_data")
        await message.reply_text("❌ Sessão expirada. Use /comprar novamente.")
        return ConversationHandler.END

    total_price_float = user_data['total_price']
    total_price_cents = float_to_cents(total_price_float)

    # Recupera o ID do provedor (padrão 1 se não existir)
    provider_id = user_data.get('provider_id', 1)
    logger.info(f"Processando pedido para provedor {provider_id}")

    # Define URL, chave e campo do serviço conforme o provedor
    if provider_id == 1:
        api_url = SMM_API_URL_1
        api_key = SMM_API_KEY_1
        service_field = 'service'
    elif provider_id == 2:
        api_url = SMM_API_URL_2
        api_key = SMM_API_KEY_2
        service_field = 'service'
    else:
        logger.error(f"Provedor desconhecido: {provider_id}")
        await message.reply_text("❌ Provedor desconhecido. Contate o suporte.")
        return ConversationHandler.END

    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    try:
        # 1. DEBITAR SALDO (com verificação de saldo suficiente)
        cursor.execute("""
            UPDATE users
            SET main_balance_cents = main_balance_cents - ?
            WHERE user_id = ? AND main_balance_cents >= ?
        """, (total_price_cents, user_id, total_price_cents))

        if cursor.rowcount == 0:
            keyboard = [[InlineKeyboardButton("💳 Adicionar Saldo (PIX)", callback_data="add_balance")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                f"❌ **Saldo Insuficiente!**\n\n"
                f"O pedido custa **R$ {total_price_float:.2f}**, mas seu saldo atual não cobre este valor.\n"
                f"Deseja recarregar agora?",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            conn.close()
            return ConversationHandler.END

        conn.commit()
        logger.info(f"Saldo debitado: user={user_id}, valor={total_price_cents} centavos")

        # 2. MONTAR PAYLOAD DINAMICAMENTE
        payload = {
            'key': api_key,
            'action': 'add',
            service_field: user_data['service_id'],
            'link': user_data['link'],
            'quantity': user_data['quantity']
        }

        logger.info(f"Enviando pedido para provedor {provider_id}: URL={api_url}, payload={payload}")

        # 3. CHAMADA À API
        res = requests.post(api_url, data=payload, timeout=20)
        response = res.json()
        logger.info(f"Resposta da API provedor {provider_id}: {response}")

        # 4. TRATAR RESPOSTA
        if 'order' in response:
            order_id_api = response['order']
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")

            # Verifica a estrutura atual da tabela orders
            cursor.execute("PRAGMA table_info(orders)")
            columns = [col[1] for col in cursor.fetchall()]
            has_amount_cents = 'amount_cents' in columns
            has_provider = 'provider_id' in columns

            # Campos base
            fields = ['user_id', 'service_name', 'quantity', 'order_id_api', 'status', 'date']
            values = [user_id, user_data['service_name'], user_data['quantity'], order_id_api, "Pendente", data_atual]

            # Adiciona campo de valor (centavos ou float)
            if has_amount_cents:
                fields.append('amount_cents')
                values.append(total_price_cents)
            else:
                fields.append('amount')
                values.append(total_price_float)

            # Adiciona provider_id se a coluna existir
            if has_provider:
                fields.append('provider_id')
                values.append(provider_id)

            placeholders = ', '.join(['?' for _ in fields])
            sql = f"INSERT INTO orders ({', '.join(fields)}) VALUES ({placeholders})"

            logger.info(f"Inserindo pedido no banco: SQL={sql}, valores={values}")

            try:
                cursor.execute(sql, values)
                conn.commit()
                logger.info(f"✅ Pedido {order_id_api} inserido com sucesso. user_id={user_id}, provider_id={provider_id}")
            except Exception as insert_error:
                logger.error(f"❌ Falha ao inserir pedido {order_id_api}: {insert_error}")
                conn.rollback()
                # Estorna o saldo debitado
                cursor.execute("UPDATE users SET main_balance_cents = main_balance_cents + ? WHERE user_id = ?", (total_price_cents, user_id))
                conn.commit()
                await message.reply_text("❌ Erro interno ao registrar pedido. Seu saldo foi estornado. Contate o suporte.")
                return ConversationHandler.END

            # Mensagem de sucesso
            keyboard = [
                [
                    InlineKeyboardButton("📊 Status do Pedido", callback_data=f"status_{order_id_api}"),
                    InlineKeyboardButton("📜 Meus Pedidos", callback_data="my_orders")
                ],
                [InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg_sucesso = (
                f"✅ **PEDIDO ENVIADO COM SUCESSO!**\n\n"
                f"🆔 ID: `{order_id_api}`\n"
                f"💰 Valor: R$ {total_price_float:.2f}\n"
                f"📅 Data: {data_atual}\n\n"
                f"Clique abaixo para acompanhar em tempo real:"
            )

            if query:
                await query.edit_message_text(msg_sucesso, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await message.reply_text(msg_sucesso, reply_markup=reply_markup, parse_mode="Markdown")

        else:
            # Estornar saldo
            cursor.execute("""
                UPDATE users
                SET main_balance_cents = main_balance_cents + ?
                WHERE user_id = ?
            """, (total_price_cents, user_id))
            conn.commit()

            error_msg = response.get('error', 'Erro desconhecido')
            logger.error(f"Erro da API provedor {provider_id}: {error_msg}")
            await message.reply_text(f"❌ Erro no provedor: {error_msg}\nSeu saldo foi estornado.")

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ ERRO NO PEDIDO: {e}")
        await message.reply_text("⚠️ Erro interno ao processar. Tente novamente.")
    finally:
        conn.close()

    return ConversationHandler.END
