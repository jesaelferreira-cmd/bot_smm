from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from handlers.services import get_categories, get_services, get_service_by_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # 1. Clicar na categoria
    if data.startswith("cat|"):
        category = data.split("|")[1]
        services = get_services(category)
        
        if not services:
            await query.edit_message_text("⚠️ NENHUM SERVIÇO ENCONTRADO NESTA CATEGORIA.")
            return

        buttons = []
        for s in services:
            # Layout mantido: Nome | Min | Max | Preço
            buttons.append([
                InlineKeyboardButton(
                    f"{s[1]} | Min:{s[3]} Max:{s[4]} | R${s[2]:.2f}",
                    callback_data=f"service|{s[0]}"
                )
            ])

        buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="back")])
        await query.edit_message_text(
            f"📦 **CATEGORIA:** {category.upper()}",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )

    # 2. Clicar no serviço
    elif data.startswith("service|"):
        service_id = data.split("|")[1]
        service = get_service_by_id(service_id)

        # Proteção contra erro de 'NoneType' no banco de dados
        if not service:
            await query.edit_message_text("❌ ERRO: SERVIÇO NÃO ENCONTRADO NO BANCO DE DADOS.")
            return

        context.user_data['service_id'] = service_id
        context.user_data['service_name'] = service[1]
        context.user_data['service_rate'] = service[2] # Adicionado Preço
        context.user_data['service_min'] = service[3]
        context.user_data['service_max'] = service[4]

        await query.edit_message_text(
            f"✅ **SERVIÇO ESCOLHIDO:**\n\n"
            f"📌 **Nome:** {service[1]}\n"
            f"💰 **Preço (1k):** R$ {service[2]:.2f}\n"
            f"📉 **Mínimo:** {service[3]}\n"
            f"📈 **Máximo:** {service[4]}\n\n"
            f"✍️ **DIGITE A QUANTIDADE DESEJADA:**",
            parse_mode="Markdown"
        )
        return "WAIT_QUANTITY"

    # 3. Voltar para categorias
    elif data == "back":
        categories = get_categories()
        buttons = [[InlineKeyboardButton(cat, callback_data=f"cat|{cat}")] for cat in categories]
        # Layout UX: Botão de voltar ao início
        buttons.append([InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")])

        await query.edit_message_text(
            "📂 **ESCOLHA UMA CATEGORIA:**",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )

