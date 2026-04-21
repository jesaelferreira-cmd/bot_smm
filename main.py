#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import logging
import sys
import datetime
import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv()

startup_time = datetime.datetime.now()

# Adicionar caminho ao PYTHONPATH
sys.path.append(str(Path(__file__).parent))

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)

from config import TELEGRAM_TOKEN, LOG_PATH
from database.connection import init_database

# Importar handlers
from handlers import start, balance, services, orders, buttons, status, admin, affiliates, user
from handlers.services import (
    list_services,
    category_services,
    receive_service,
    proceed_to_quantity,
    receive_quantity,
    confirm_price_callback,
    receive_link,
    execute_order_callback,
    cancel,
    back_to_categories,
    cancel_to_services,
    category_page_nav,
    SELECTING_SERVICE,
    ASKING_QUANTITY,
    WAIT_CONFIRM_PRICE,
    ASKING_LINK,
    CONFIRMING
)
from handlers.admin import debug_categories, fix_order
from handlers.admin import limpar_fornecedor
# Configuração de logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    try:
        logger.info("Inicializando banco de dados...")
        init_database()

        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # =========================================================
        # 1. CONVERSATION HANDLER (FLUXO DE COMPRA)
        # =========================================================
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("comprar", list_services),
                CallbackQueryHandler(list_services, pattern="^back_to_categories$"),
            ],
            states={
                SELECTING_SERVICE: [
                    CallbackQueryHandler(category_services, pattern="^cat_"),
                    CallbackQueryHandler(receive_service, pattern="^serv_"),
                    CallbackQueryHandler(category_page_nav, pattern="^catpage_"),
                    CallbackQueryHandler(list_services, pattern="^back_to_categories$"),
                    CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
                ],
                WAIT_CONFIRM_PRICE: [
                    CallbackQueryHandler(proceed_to_quantity, pattern="^proceed_quantity$"),
                    CallbackQueryHandler(confirm_price_callback, pattern="^confirm_price$"),
                    CallbackQueryHandler(back_to_categories, pattern="^back_to_categories$"),
                    CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
                ],
                ASKING_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity),
                    CallbackQueryHandler(back_to_categories, pattern="^back_to_categories$"),
                    CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
                ],
                ASKING_LINK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link),
                    CallbackQueryHandler(back_to_categories, pattern="^back_to_categories$"),
                    CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
                ],
                CONFIRMING: [
                    CallbackQueryHandler(execute_order_callback, pattern="^execute_order$"),
                    CallbackQueryHandler(cancel_to_services, pattern="^cancel_order$"),
                    CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancelar", cancel),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
                CallbackQueryHandler(start.start_command, pattern="^back_to_start$"),
            ],
            allow_reentry=True,
            per_message=False
        )

        app.add_handler(conv_handler)

        # =========================================================
        # 2. COMANDOS GERAIS
        # =========================================================
        app.add_handler(CommandHandler("start", start.start_command))
        app.add_handler(CommandHandler("saldo", balance.show_balance))
        app.add_handler(CommandHandler("status", status.get_status))
        app.add_handler(CommandHandler("pedidos", status.my_orders))
        app.add_handler(CommandHandler("pix", balance.pix_command))
        app.add_handler(CommandHandler("admin", admin.admin_panel))
        app.add_handler(CommandHandler("setbalance", admin.set_balance))
        app.add_handler(CommandHandler("sync", admin.sync_services))
        app.add_handler(CommandHandler("painel", admin.admin_panel))
        app.add_handler(CommandHandler("margem", admin.set_margin))
        app.add_handler(CommandHandler("promo", admin.set_promo))
        app.add_handler(CommandHandler("atualizar", admin.update_command))
        app.add_handler(CommandHandler("bc", admin.broadcast))
        app.add_handler(CommandHandler("test_services", admin.test_services))
        app.add_handler(CommandHandler("test_api_fields", admin.test_api_fields))
        app.add_handler(CommandHandler("check_descriptions", admin.check_descriptions))
        app.add_handler(CommandHandler("list_providers", admin.list_providers))
        app.add_handler(CommandHandler("debug_cats", debug_categories))
        app.add_handler(CommandHandler("saldo_api", status.check_provider_balance))
        app.add_handler(CommandHandler("corrigir_pedido", fix_order))
        app.add_handler(CommandHandler("limpar_fornecedor", limpar_fornecedor))
        # =========================================================
        # 3. CALLBACKS GERAIS (FORA DO CONVERSATION)
        # =========================================================
        app.add_handler(CallbackQueryHandler(user.show_profile, pattern="^my_profile$"))
        app.add_handler(CallbackQueryHandler(status.my_orders, pattern="^my_history$"))
        app.add_handler(CallbackQueryHandler(affiliates.show_affiliates, pattern="^affiliates$"))
        app.add_handler(CallbackQueryHandler(affiliates.my_referrals, pattern="^aff_my_referrals$"))
        app.add_handler(CallbackQueryHandler(affiliates.withdraw_to_bot, pattern="^aff_withdraw_bot$"))
        app.add_handler(CallbackQueryHandler(balance.pix_command, pattern="^add_balance$"))
        app.add_handler(CallbackQueryHandler(start.start_command, pattern="^back_to_start$"))
        app.add_handler(CallbackQueryHandler(status.order_status_callback, pattern="^status_"))
        # =========================================================
        # 4. AFILIADOS - CONVERSATION HANDLER PARA SAQUE PIX
        # =========================================================
        app.add_handler(affiliates.pix_withdrawal_handler)

        # =========================================================
        # 5. BOTÕES GENÉRICOS (último para capturar qualquer padrão)
        # =========================================================
        app.add_handler(CallbackQueryHandler(buttons.button_handler))

        logger.info("LikesPlus está rodando! 🚀")
        app.run_polling()

    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
