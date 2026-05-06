import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.start import start_command
from handlers.balance import show_balance, pix_command
from handlers.services import list_services, category_services, receive_service, back_to_categories
from handlers.orders import confirm_order
from handlers.status import my_orders, order_status_callback
from handlers.affiliates import show_affiliates, my_referrals, withdraw_to_bot
from handlers.admin import admin_panel
from database import get_connection

logger = logging.getLogger(__name__)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # ========== NAVEGAÇÃO PRINCIPAL ==========
    if data == "back_to_start":
        await start_command(update, context)
    elif data == "back_to_categories":
        await list_services(update, context)
    elif data == "show_balance":
        await show_balance(update, context)
    elif data == "my_history":
        await my_orders(update, context)
    elif data == "affiliates":
        await show_affiliates(update, context)
    elif data == "aff_my_referrals":
        await my_referrals(update, context)
    elif data == "aff_withdraw_bot":
        await withdraw_to_bot(update, context)
    elif data == "add_balance":
        await pix_command(update, context)
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data.startswith("status_"):
        await order_status_callback(update, context)

    # ========== COMPRA (callbacks do services.py) ==========
    elif data.startswith("cat_"):
        await category_services(update, context)
    elif data.startswith("serv_"):
        await receive_service(update, context)
    elif data == "confirm_price":
        from handlers.services import confirm_price_callback
        await confirm_price_callback(update, context)
    elif data == "proceed_quantity":
        from handlers.services import proceed_to_quantity
        await proceed_to_quantity(update, context)
    elif data == "execute_order":
        await confirm_order(update, context)
    elif data == "cancel_order":
        from handlers.services import cancel_to_services
        await cancel_to_services(update, context)

    # ========== PAGINAÇÃO ==========
    elif data.startswith("catpage_"):
        from handlers.services import category_page_nav
        await category_page_nav(update, context)

    # ========== SAQUE PIX (afiliados) ==========
    elif data.startswith("confirm_payment_"):
        from handlers.affiliates import confirm_payment
        await confirm_payment(update, context)
    elif data.startswith("cancel_payment_"):
        from handlers.affiliates import cancel_payment
        await cancel_payment(update, context)
    elif data == "cancel_pix":
        from handlers.affiliates import cancel_pix
        await cancel_pix(update, context)

    else:
        logger.warning(f"Callback não tratado: {data}")
        await query.message.reply_text("⚠️ Função não implementada ainda.")
