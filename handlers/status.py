import sqlite3
import requests
from datetime import datetime
from config import DB_PATH, SMM_API_URL_1, SMM_API_KEY_1
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os últimos pedidos tratando corretamente mensagens com ou sem foto"""
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

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
        if not cursor.fetchone():
            text = "📭 **Você ainda não tem pedidos realizados.**"
        else:
            # Selecionando order_id_api para garantir que não apareça 'None'
            cursor.execute("""
                SELECT order_id_api, service_name, amount, date, status
                FROM orders WHERE user_id = ?
                ORDER BY id DESC LIMIT 5
            """, (user_id,))
            orders_list = cursor.fetchall()

            if not orders_list:
                text = "📭 **Histórico vazio.**\nFaça sua primeira compra em /comprar!"
            else:
                text = "📋 **SEUS ÚLTIMOS PEDIDOS**\n\n"
                for o in orders_list:
                    # Melhoria no emoji de status para o histórico
                    s = str(o[4])
                    status_emoji = "✅" if "Conclu" in s else "❌" if "Cancel" in s else "⏳"
                    text += f"{status_emoji} ID: `{o[0]}` | {o[1]}\n💰 R$ {o[2]:.2f} - 📅 {o[3]}\n\n"

        if query:
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        print(f"❌ Erro ao buscar pedidos: {e}")
        error_msg = "⚠️ Houve um erro ao buscar seu histórico."
        if query:
            await query.message.reply_text(error_msg)
        else:
            await message.reply_text(error_msg)
    finally:
        if conn: conn.close()

async def get_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta status e realiza estorno automático se cancelado"""
    if not context.args:
        await update.message.reply_text("❓ Digite `/status ID_DO_PEDIDO`.")
        return

    order_id = context.args[0]
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    try:
        # 1. BUSCA O VALOR E STATUS ATUAL NO BANCO
        cursor.execute("SELECT amount, status FROM orders WHERE order_id_api = ? AND user_id = ?", (order_id, user_id))
        order_db = cursor.fetchone()

        if not order_db:
            await update.message.reply_text("❌ Pedido não encontrado no seu histórico.")
            return

        amount_paid, status_no_banco = order_db

        # 2. CONSULTA API
        payload = {'key': SMM_API_KEY_1, 'action': 'status', 'order': order_id}
        response = requests.post(SMM_API_URL_1, data=payload, timeout=20).json()

        if 'status' in response:
            raw_status = str(response.get('status', '')).title()
            
            # --- LÓGICA DE ESTORNO ---
            # Se a API diz que cancelou, mas no seu banco ainda não está como cancelado:
            if raw_status in ['Canceled', 'Partial', 'Cancelled'] and status_no_banco not in ['Cancelado', 'Estornado']:
                cursor.execute("UPDATE users SET balance = ROUND(balance + ?, 2) WHERE user_id = ?", (amount_paid, user_id))
                cursor.execute("UPDATE orders SET status = 'Cancelado' WHERE order_id_api = ?", (order_id,))
                conn.commit()
                
                await update.message.reply_text(
                    f"❌ **PEDIDO CANCELADO**\n\n"
                    f"💰 O valor de **R$ {amount_paid:.2f}** foi devolvido ao seu saldo.\n"
                    f"⚠️ *Motivo:* Geralmente perfil privado ou link inválido.",
                    parse_mode="Markdown"
                )
                return

            # --- EXIBIÇÃO NORMAL ---
            status_map = {
                'Pending': '⏳ Pendente',
                'In Progress': '🔄 Em andamento',
                'Completed': '✅ Concluído',
                'Partial': '⚠️ Parcial (Estornado)',
                'Canceled': '❌ Cancelado (Estornado)',
                'Processing': '⚙️ Processando'
            }
            s_display = status_map.get(raw_status, raw_status)

            inicio = response.get('start_count', 'Aguardando...')
            restante = response.get('remains', '0')

            msg = (
                f"📊 **DETALHES DO PEDIDO**\n\n"
                f"🆔 **ID:** `{order_id}`\n"
                f"📌 **Status:** {s_display}\n"
                f"📦 **Restante:** {restante}\n"
                f"💰 **Início:** {inicio}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ **Erro no Provedor:** {response.get('error', 'ID Inválido')}")

    except Exception as e:
        print(f"Erro Status: {e}")
        await update.message.reply_text("⚠️ Erro na consulta. Tente novamente.")
    finally:
        conn.close()

async def check_provider_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica saldo no fornecedor (Admin Only)"""
    try:
        payload = {'key': SMM_API_KEY_1, 'action': 'balance'}
        res = requests.post(SMM_API_URL_1, data=payload).json()
        await update.message.reply_text(f"💳 **Saldo SMM:** {res.get('balance', '0.00')} {res.get('currency', 'USD')}")
    except:
        await update.message.reply_text("❌ Erro ao checar saldo da API.")

