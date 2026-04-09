import requests
import sqlite3
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

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

    # Suporte para callback_query (botão) ou mensagem direta
    query = update.callback_query
    if query:
        await query.answer("Processando pedido...")
        message = query.message
    else:
        message = update.message

    if 'service_id' not in user_data:
        return ConversationHandler.END

    total_price_float = user_data['total_price']          # float (ex: 12.50)
    total_price_cents = float_to_cents(total_price_float) # inteiro (ex: 1250)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    try:
        # 1. DEBITAR SALDO (em centavos, com verificação de saldo suficiente)
        cursor.execute("""
            UPDATE users 
            SET main_balance_cents = main_balance_cents - ?
            WHERE user_id = ? AND main_balance_cents >= ?
        """, (total_price_cents, user_id, total_price_cents))

        if cursor.rowcount == 0:
            # Saldo insuficiente → oferece botão de recarga
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

        conn.commit()  # debita o saldo antes de chamar a API

        # 2. DEFINIR PROVEDOR (pode ser dinâmico no futuro)
        url, key = SMM_API_URL_1, SMM_API_KEY_1  # padrão

        payload = {
            'key': key,
            'action': 'add',
            'service': user_data['service_id'],
            'link': user_data['link'],
            'quantity': user_data['quantity']
        }

        # 3. CHAMADA À API DO FORNECEDOR
        res = requests.post(url, data=payload, timeout=20)
        response = res.json()

        # 4. TRATAR RESPOSTA
        if 'order' in response:
            order_id_api = response['order']
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")

            # Verifica se a tabela orders tem a coluna amount_cents (recomendado)
            # Se não tiver, usamos amount (FLOAT) para compatibilidade
            cursor.execute("PRAGMA table_info(orders)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'amount_cents' in columns:
                cursor.execute("""
                    INSERT INTO orders (user_id, service_name, quantity, amount_cents, order_id_api, status, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, user_data['service_name'], user_data['quantity'], total_price_cents, order_id_api, "Pendente", data_atual))
            else:
                # Fallback para coluna antiga (FLOAT)
                cursor.execute("""
                    INSERT INTO orders (user_id, service_name, quantity, amount, order_id_api, status, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, user_data['service_name'], user_data['quantity'], total_price_float, order_id_api, "Pendente", data_atual))

            conn.commit()

            # Botões de navegação
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
            # Se a API do fornecedor falhar, estorna o saldo (reverte o débito)
            cursor.execute("""
                UPDATE users 
                SET main_balance_cents = main_balance_cents + ?
                WHERE user_id = ?
            """, (total_price_cents, user_id))
            conn.commit()

            error_msg = response.get('error', 'Erro desconhecido')
            await message.reply_text(f"❌ Erro no provedor: {error_msg}\nSeu saldo foi estornado.")

    except Exception as e:
        # Em caso de qualquer exceção (rede, timeout, etc), estorna o saldo
        conn.rollback()
        print(f"❌ ERRO NO PEDIDO: {e}")
        await message.reply_text("⚠️ Erro interno ao processar. Tente novamente.")
    finally:
        conn.close()

    return ConversationHandler.END
