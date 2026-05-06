import asyncio
import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import MP_ACCESS_TOKEN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from providers.mp_api import create_pix_payment
import mercadopago
from database.connection import get_connection  # caminho padronizado

logger = logging.getLogger(__name__)

user_locks = {}

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

def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Upsert compatível com PostgreSQL (ON CONFLICT)
        cursor.execute(
            "INSERT INTO users (user_id, balance) VALUES (%s, 0) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id,)
        )
        conn.commit()

        cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        saldo_centavos = int(result[0]) if result else 0
        balance = saldo_centavos / 100.0

        await update.message.reply_text(
            f"💰 **SEU PAINEL FINANCEIRO**\n\n"
            f"👤 Usuário: `{user_id}`\n"
            f"💵 Saldo Disponível: **R$ {balance:.2f}**\n\n"
            f"🚀 _Precisa de mais? Use `/pix valor` para recarregar._",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Erro ao exibir saldo: {e}")
        await update.message.reply_text("❌ Erro interno ao buscar saldo.")
    finally:
        conn.close()

async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    target = query.message if query else update.message
    if query:
        await query.answer()

    if not context.args:
        text = (
            "💰 **RECARGA PIX**\n\n"
            "💵 Mínimo: **R$ 5,00**\n"
            "🚀 Máximo: **R$ 1.000,00**\n\n"
            "💡 Para recarregar agora, digite:\n`/pix VALOR` (Ex: `/pix 20`)"
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu Principal", callback_data="back_to_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            if query and (query.message.photo or query.message.caption):
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            elif query:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await target.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao editar menu pix: {e}")
        return

    raw_amount = context.args[0].replace(',', '.')
    if not re.match(r'^\d+(\.\d{1,2})?$', raw_amount):
        await target.reply_text("❌ **Formato inválido!** Use apenas números (ex: 50 ou 50.00)")
        return

    try:
        amount_float = float(raw_amount)
        if amount_float < 5.00 or amount_float > 1000.00:
            await target.reply_text("⚠️ **Valor fora do limite!**\nO PIX deve ser entre R$ 5,00 e R$ 1.000,00.")
            return
        amount_cents = float_to_cents(amount_float)
        amount_display = amount_cents / 100.0
    except ValueError:
        await target.reply_text("❌ **Valor Inválido!** Use números (ex: `/pix 50.50`).")
        return

    now = datetime.now()
    for uid in list(user_locks.keys()):
        if (now - user_locks[uid]).total_seconds() > 3600:
            del user_locks[uid]

    if user_id in user_locks:
        diff = (now - user_locks[user_id]).total_seconds()
        if diff < 10:
            await target.reply_text(f"⏳ Aguarde {10 - int(diff)}s para gerar um novo PIX.")
            return
    user_locks[user_id] = now

    status_msg = await target.reply_text("⏳ Gerando seu código PIX... Aguarde.")
    try:
        await target.reply_chat_action("typing")
        payment = create_pix_payment(amount_display, user_id)

        if payment and "qrcode" in payment:
            pix_id = payment["id"]
            qrcode = payment["qrcode"]
            msg = (
                f"💎 **PIX GERADO COM SUCESSO!**\n\n"
                f"💰 Valor: **R$ {amount_display:.2f}**\n"
                f"🔑 Chave Copia e Cola abaixo:\n\n"
                f"`{qrcode}`\n\n"
                f"⚠️ *O saldo cairá na hora após o pagamento.*"
            )
            await status_msg.delete()
            await target.reply_text(msg, parse_mode="Markdown")
            asyncio.create_task(check_payment_loop(context, user_id, pix_id, amount_cents))
        else:
            error_detail = payment.get("message", "sem detalhes") if payment else "resposta vazia"
            logger.error(f"API MP falhou para o usuário {user_id}: {error_detail}")
            await status_msg.edit_text("❌ Não foi possível gerar o PIX no Mercado Pago agora. Tente mais tarde.")
    except Exception as e:
        logger.critical(f"Erro fatal no processo de PIX: {e}")
        await status_msg.edit_text("⚠️ Erro interno no sistema de pagamentos.")

async def check_payment_loop(context: ContextTypes.DEFAULT_TYPE, user_id: int, pix_id: str, amount_cents: int):
    sdk = mercadopago.SDK(str(MP_ACCESS_TOKEN))
    amount_display = cents_to_float(amount_cents)

    for attempt in range(40):
        await asyncio.sleep(30)
        try:
            res = sdk.payment().get(pix_id)
            status = res["response"].get("status")

            if status == "approved":
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    # Garante existência do usuário
                    cursor.execute(
                        "INSERT INTO users (user_id, balance) VALUES (%s, 0) "
                        "ON CONFLICT (user_id) DO NOTHING",
                        (user_id,)
                    )
                    conn.commit()

                    # Atualiza saldo em centavos
                    cursor.execute(
                        "UPDATE users SET balance = balance + %s WHERE user_id = %s",
                        (amount_cents, user_id)
                    )
                    if cursor.rowcount > 0:
                        conn.commit()
                        logger.info(f"💰 Crédito de {amount_display:.2f} para {user_id}")
                        keyboard = [
                            [
                                InlineKeyboardButton("🛒 Ir para a Loja", callback_data="back_to_categories"),
                                InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ **PAGAMENTO CONFIRMADO!**\n\nSua recarga de **R$ {amount_display:.2f}** foi creditada!",
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                    else:
                        logger.warning(f"Falha ao atualizar saldo para {user_id}")
                except Exception as e:
                    logger.error(f"Erro SQL ao creditar: {e}")
                    conn.rollback()
                finally:
                    conn.close()
                return
            elif status in ["cancelled", "rejected"]:
                logger.info(f"Pagamento {pix_id} cancelado")
                return
        except Exception as e:
            logger.error(f"Erro no loop: {e}")
            await asyncio.sleep(10)
    logger.info(f"Loop expirado para PIX {pix_id}")
