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
from handlers.services import list_services, category_services

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
        # 1. CONVERSATION HANDLER (FLUXO DE COMPRA COM BOTÕES)
        # =========================================================
        conv_handler = ConversationHandler(
            # 1. ENTRADA: Como a conversa começa? (Comando ou clique inicial)
            entry_points=[
                CommandHandler("comprar", services.list_services),
                CallbackQueryHandler(services.category_services, pattern="^cat_"),
                CallbackQueryHandler(services.receive_service, pattern="^serv_"),
                CallbackQueryHandler(services.list_services, pattern="^back_to_categories$")
            ],

            # 2. ESTADOS: O "Passo a Passo". O bot só escuta o que está no estado atual.
            states={
                services.SELECTING_SERVICE: [
                    CallbackQueryHandler(services.receive_service, pattern="^serv_")
                ],
                services.ASKING_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, services.receive_quantity)
                ],
                services.WAIT_CONFIRM_PRICE: [
                    CallbackQueryHandler(services.proceed_to_quantity, pattern="^proceed_quantity$"),
                    CallbackQueryHandler(services.list_services, pattern="^back_to_categories$")
                ],
                services.ASKING_LINK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, services.receive_link)
                ],
                services.CONFIRMING: [
                    CallbackQueryHandler(orders.confirm_order, pattern="^execute_order$"),
                    CallbackQueryHandler(services.cancel, pattern="^cancel_order$")
                ]
            },

            # 3. SAÍDA DE EMERGÊNCIA: Se o usuário quiser desistir.
            fallbacks=[CommandHandler("cancelar", services.cancel)],

            # 4. CONFIGURAÇÕES: Regras do jogo.
            allow_reentry=True, # Permite reiniciar a compra a qualquer momento
            per_message=False   # Importante para botões inline funcionarem bem
        )

        # 2. ADICIONAR HANDLERS NA ORDEM CORRETA
        app.add_handler(conv_handler)

        # uComandos Gerais
        app.add_handler(CommandHandler("start", start.start_command))
        app.add_handler(CommandHandler("saldo", balance.show_balance))
        app.add_handler(CommandHandler("status", status.get_status))
        app.add_handler(CommandHandler("admin", admin.admin_panel))
        app.add_handler(CommandHandler("setbalance", admin.set_balance))
        app.add_handler(CommandHandler("pedidos", status.my_orders))
        app.add_handler(CommandHandler("pix", balance.pix_command))
        app.add_handler(CommandHandler("sync", admin.sync_services))
        app.add_handler(CommandHandler("painel", admin.admin_panel))
        app.add_handler(CommandHandler("margem", admin.set_margin))
        app.add_handler(CommandHandler("promo", admin.set_promo))
        app.add_handler(CommandHandler("atualizar", admin.update_command))
        app.add_handler(CommandHandler("bc", admin.broadcast))
        app.add_handler(CommandHandler("setbalance", admin.set_balance))
        app.add_handler(CommandHandler("test_services", admin.test_services))

        # Callbacks Gerais (Menu Principal e Perfil)
        app.add_handler(CallbackQueryHandler(user.show_profile, pattern="^my_profile$"))
        app.add_handler(CallbackQueryHandler(status.my_orders, pattern="^my_history$"))
        app.add_handler(CallbackQueryHandler(affiliates.my_referrals, pattern="^aff_my_referrals$"))
        app.add_handler(CallbackQueryHandler(start.start_command, pattern="^back_to_start$"))
        app.add_handler(CallbackQueryHandler(balance.pix_command, pattern="^add_balance$"))
        
        # Afiliados
# ==================== AFILIADOS ====================
# Central de afiliados (menu principal)
        app.add_handler(CallbackQueryHandler(affiliates.show_affiliates, pattern="^affiliates$"))

# Saque para saldo do bot (resgate interno)
        app.add_handler(CallbackQueryHandler(affiliates.withdraw_to_bot, pattern="^aff_withdraw_bot$"))

# ConversationHandler para saque via PIX (com solicitação da chave)
        app.add_handler(affiliates.pix_withdrawal_handler)

# Opcional: se você ainda tiver um botão "aff_withdraw" antigo, remova ou adapte.
        # 3. BOTÕES GERAIS (Sempre por último)
        app.add_handler(CallbackQueryHandler(buttons.button_handler))

        logger.info("LikesPlus está rodando! 🚀")
        app.run_polling()

    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
   main()
