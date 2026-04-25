import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from handlers.consultoria_inteligente import analisar_perfil, registrar_compra, avaliar_recomendacao

logger = logging.getLogger(__name__)

ASKING_LINK, FEEDBACK = range(2)

async def start_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback do botão 'Consultoria'."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🔍 **Vamos analisar a saúde do seu perfil!**\n\n"
        "Envie o link completo do perfil que deseja analisar (Instagram, TikTok, YouTube)."
    )
    return ASKING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o link, gera análise e exibe recomendações."""
    link = update.message.text.strip()
    user_id = update.effective_user.id

    try:
        recomendacoes, report = analisar_perfil(link, user_id)
    except Exception as e:
        logger.error(f"Erro em analisar_perfil: {e}")
        await update.message.reply_text("⚠️ Ocorreu um erro ao analisar seu perfil. Tente novamente mais tarde.")
        return await go_to_main_menu(update, context)

    if recomendacoes is None:
        try:
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(report)
        return await go_to_main_menu(update, context)

    # Armazena recomendações para possível feedback
    context.user_data['consultoria_recomendacoes'] = recomendacoes
    context.user_data['consultoria_link'] = link

    keyboard = []
    for sid, name, rate, min_q, max_q, cat, score in recomendacoes:
        short_name = (name[:40] + '…') if len(name) > 40 else name
        button_text = f"🛒 {short_name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"buyrec_{sid}")])

    keyboard.append([InlineKeyboardButton("✅ Finalizar", callback_data="end_consultoria")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    mensagem_final = report + "\n\nEscolha um serviço para comprar agora:"
    try:
        await update.message.reply_text(mensagem_final, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Falha ao enviar relatório: {e}")
        await update.message.reply_text(mensagem_final, reply_markup=reply_markup)
    return FEEDBACK

async def buy_recommendation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback de compra simulada (futuro: iniciar fluxo real)."""
    query = update.callback_query
    await query.answer()
    service_id = int(query.data.split('_')[1])
    user_id = update.effective_user.id
    link = context.user_data.get('consultoria_link')

    # Simula compra – aqui você pode integrar o fluxo de compra real futuramente
    await query.message.reply_text("✅ Compra simulada! (Em breve, iniciará o fluxo de compra real.)")

    # Pergunta avaliação
    keyboard = [
        [InlineKeyboardButton("👍 Recomendo", callback_data=f"avaliar_{service_id}_1"),
         InlineKeyboardButton("👎 Não recomendo", callback_data=f"avaliar_{service_id}_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Como você avalia essa recomendação?", reply_markup=reply_markup)
    return FEEDBACK

async def avaliar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra avaliação e volta ao menu principal."""
    query = update.callback_query
    await query.answer()
    _, service_id, nota = query.data.split('_')
    user_id = update.effective_user.id
    avaliar_recomendacao(user_id, int(service_id), nota)
    await query.message.reply_text("Obrigado pelo feedback! Isso ajuda a melhorar as próximas recomendações.")
    return await go_to_main_menu(update, context)

async def end_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finaliza a consultoria e retorna ao menu principal."""
    query = update.callback_query
    if query:
        await query.answer()
    return await go_to_main_menu(update, context)

async def cancel_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela a consultoria e volta ao menu."""
    # Se a chamada veio de um comando ou callback, tratamos adequadamente
    if update.callback_query:
        await update.callback_query.answer()
    return await go_to_main_menu(update, context)

async def go_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redireciona para o menu principal (simula o /start)."""
    # Importa aqui para evitar dependência circular
    from handlers.start import start_command
    await start_command(update, context)
    return ConversationHandler.END

# Handler que será importado no main.py
consultoria_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_consultoria, pattern="^consultoria$")],
    states={
        ASKING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        FEEDBACK: [
            CallbackQueryHandler(buy_recommendation, pattern="^buyrec_"),
            CallbackQueryHandler(avaliar, pattern="^avaliar_"),
            CallbackQueryHandler(end_consultoria, pattern="^end_consultoria"),
        ],
    },
    fallbacks=[CallbackQueryHandler(cancel_consultoria, pattern="^cancel$")],
)
