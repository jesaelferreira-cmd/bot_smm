import sqlite3
from config import DB_PATH
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from handlers.consultoria_inteligente import analisar_perfil, registrar_compra, avaliar_recomendacao

ASKING_LINK, FEEDBACK = range(2)

async def start_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🔍 Envie o link do perfil que deseja analisar (Instagram, TikTok, YouTube).")
    return ASKING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id
    recomendacoes, report = analisar_perfil(link, user_id)
    if recomendacoes is None:
        await update.message.reply_text(report)
        return ConversationHandler.END

    # Armazena recomendações para possível feedback
    context.user_data['consultoria_recomendacoes'] = recomendacoes
    context.user_data['consultoria_link'] = link

    keyboard = []
    for sid, name, rate, min_q, max_q, cat, score in recomendacoes:
        keyboard.append([InlineKeyboardButton(f"🛒 {name}", callback_data=f"buyrec_{sid}")])
    keyboard.append([InlineKeyboardButton("✅ Finalizar", callback_data="end_consultoria")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(report + "\n\nEscolha um serviço para comprar agora:", reply_markup=reply_markup, parse_mode="Markdown")
    return FEEDBACK

async def buy_recommendation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = int(query.data.split('_')[1])
    user_id = update.effective_user.id
    link = context.user_data.get('consultoria_link')

    # Aqui você pode iniciar o fluxo de compra (similar ao /comprar) passando o service_id
    # Por simplicidade, apenas registra a compra e pede feedback
    registrar_compra(user_id, service_id, nicho='detectado', platform='instagram', username='teste')  # Ajustar para obter dados reais
    await query.message.reply_text("✅ Compra simulada! (Em produção, iniciaria o fluxo de compra real.)")

    # Pergunta avaliação
    keyboard = [
        [InlineKeyboardButton("👍 Recomendo", callback_data=f"avaliar_{service_id}_1"),
         InlineKeyboardButton("👎 Não recomendo", callback_data=f"avaliar_{service_id}_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Como você avalia essa recomendação?", reply_markup=reply_markup)
    return FEEDBACK

async def avaliar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, service_id, nota = query.data.split('_')
    user_id = update.effective_user.id
    avaliar_recomendacao(user_id, int(service_id), nota)
    await query.message.reply_text("Obrigado pelo feedback! Isso ajuda a melhorar as próximas recomendações.")
    return ConversationHandler.END

async def end_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Consultoria encerrada. Volte sempre!")
    return ConversationHandler.END

consultoria_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_consultoria, pattern="^consultoria$")],
    states={
        ASKING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        FEEDBACK: [
            CallbackQueryHandler(buy_recommendation, pattern="^buyrec_"),
            CallbackQueryHandler(avaliar, pattern="^avaliar_"),
            CallbackQueryHandler(end_consultoria, pattern="^end_consultoria")
        ]
    },
    fallbacks=[]
)
