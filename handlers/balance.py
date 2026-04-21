import sqlite3
import asyncio
import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import DB_PATH, MP_ACCESS_TOKEN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from providers.mp_api import create_pix_payment
import mercadopago

logger = logging.getLogger(__name__)

# Trava para evitar múltiplas requisições PIX simultâneas do mesmo usuário
user_locks = {}

# ------------------------------------------------------------
# FUNÇÃO AUXILIAR: converte centavos (int) para float com 2 casas
# ------------------------------------------------------------
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

def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

# ------------------------------------------------------------
# 1. EXIBIR SALDO (usa main_balance_cents)
# ------------------------------------------------------------
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        cursor = conn.cursor()

        # Garante que o usuário existe (com saldo 0 em centavos)
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, main_balance_cents) VALUES (?, ?)",
            (user_id, 0)
        )
        conn.commit()

        cursor.execute("SELECT main_balance_cents FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = (result[0] if result else 0) / 100.0

        await update.message.reply_text(
            f"💰 **SEU PAINEL FINANCEIRO**\n\n"
            f"👤 Usuário: `{user_id}`\n"
            f"💵 Saldo Disponível: **R$ {balance:.2f}**\n\n"
            f"🚀 _Precisa de mais? Use `/pix valor` para recarregar._",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Erro ao exibir saldo do usuário {user_id}: {e}")
        await update.message.reply_text("❌ Erro interno ao buscar saldo. Tente mais tarde.")
    finally:
        if conn:
            conn.close()

# ------------------------------------------------------------
# 2. COMANDO /pix (menu ou geração de pagamento)
# ------------------------------------------------------------
async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    target = query.message if query else update.message

    if query:
        await query.answer()

    # --- CASO 1: sem argumentos → mostra menu com limites ---
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

    # --- CASO 2: com argumento → processa o valor ---
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

    # --- FLOOD PROTECTION (evita spam de geração de PIX) ---
    now = datetime.now()
    # Limpeza periódica de locks antigos (mais de 1 hora)
    for uid in list(user_locks.keys()):
        if (now - user_locks[uid]).total_seconds() > 3600:
            del user_locks[uid]

    if user_id in user_locks:
        diff = (now - user_locks[user_id]).total_seconds()
        if diff < 10:
            await target.reply_text(f"⏳ Aguarde {10 - int(diff)}s para gerar um novo PIX.")
            return
    user_locks[user_id] = now

    # --- GERAÇÃO DO PAGAMENTO ---
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

# ------------------------------------------------------------
# 3. LOOP DE VERIFICAÇÃO DE PAGAMENTO (agora com centavos)
# ------------------------------------------------------------
async def check_payment_loop(context: ContextTypes.DEFAULT_TYPE, user_id: int, pix_id: str, amount_cents: int):
    """
    Verifica a cada 30s se o PIX foi aprovado.
    Quando aprovado, adiciona amount_cents ao main_balance_cents do usuário.
    """
    sdk = mercadopago.SDK(str(MP_ACCESS_TOKEN))
    amount_display = cents_to_float(amount_cents)

    for attempt in range(40):  # 40 * 30s = 20 minutos
        await asyncio.sleep(30)
        try:
            res = sdk.payment().get(pix_id)
            status = res["response"].get("status")

            if status == "approved":
                conn = sqlite3.connect(DB_PATH, timeout=15)
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
                    if not cursor.fetchone():
                        cursor.execute(
                            "INSERT INTO users (user_id, main_balance_cents) VALUES (?, ?)",
                            (user_id, 0)
                        )
                        conn.commit()

                    cursor.execute("""
                        UPDATE users
                        SET main_balance_cents = main_balance_cents + ?
                        WHERE user_id = ?
                    """, (amount_cents, user_id))

                    if cursor.rowcount > 0:
                        conn.commit()
                        logger.info(f"💰 Crédito de {amount_display:.2f} (centavos: {amount_cents}) para usuário {user_id}")

                        keyboard = [
                            [
                                InlineKeyboardButton("🛒 Ir para a Loja", callback_data="back_to_categories"),
                                InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)

                        await context.bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
                                f"Sua recarga de **R$ {amount_display:.2f}** foi creditada com sucesso!\n"
                                f"O seu novo saldo já está disponível para uso. Aproveite!"
                            ),
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                    else:
                        logger.warning(f"Falha ao atualizar saldo para usuário {user_id} (linhas não afetadas)")
                except sqlite3.Error as e:
                    logger.error(f"Erro SQL ao creditar saldo: {e}")
                    conn.rollback()
                finally:
                    conn.close()
                return

            elif status in ["cancelled", "rejected"]:
                logger.info(f"Pagamento {pix_id} cancelado/rejeitado para usuário {user_id}")
                return

        except Exception as e:
            logger.error(f"Erro no loop de verificação (tentativa {attempt+1}): {e}")
            await asyncio.sleep(10)

    logger.info(f"⏰ Loop expirado para PIX {pix_id} (usuário {user_id}) - não confirmado em 20min")

