import sqlite3
import re
import logging
from config import DB_PATH
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

logger = logging.getLogger(__name__)

# Estados da conversa
ASKING_LINK = 1

def extract_username(link: str):
    """Extrai a plataforma e o username de um link de perfil."""
    patterns = {
        'instagram': r'(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)',
        'tiktok': r'(?:https?://)?(?:www\.)?tiktok\.com/@([a-zA-Z0-9_.]+)',
        'youtube': r'(?:https?://)?(?:www\.)?youtube\.com/@([a-zA-Z0-9_.]+)',
    }
    for platform, pattern in patterns.items():
        match = re.search(pattern, link)
        if match:
            return platform, match.group(1)
    return None, None

def analyze_profile(conn, user_id, platform, username):
    """Realiza uma análise detalhada e realista do perfil."""
    cursor = conn.cursor()

    # 1. Histórico de pedidos para este perfil
    cursor.execute("""
        SELECT service_name, SUM(quantity), MAX(date)
        FROM orders
        WHERE user_id = ? AND link LIKE ?
        AND status NOT IN ('Cancelado', 'Estornado')
        GROUP BY service_name
    """, (user_id, f'%{username}%'))
    services_purchased = cursor.fetchall()

    # 2. Categorias de serviços disponíveis para a plataforma
    cursor.execute("""
        SELECT DISTINCT category FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    available_categories = [row[0] for row in cursor.fetchall()]

    # 3. Análise Realista
    total_items = sum(row[1] for row in services_purchased) if services_purchased else 0
    variety = len(services_purchased)
    used_categories = set()

    for row in services_purchased:
        name = row[0].lower()
        if 'seguidor' in name: used_categories.add('Seguidores')
        elif 'curtida' in name: used_categories.add('Curtidas')
        elif 'visualiza' in name: used_categories.add('Visualizações')
        elif 'comentári' in name: used_categories.add('Comentários')

    # Categorias que ele ainda não usou mas estão disponíveis
    all_engagement_types = ['Seguidores', 'Curtidas', 'Visualizações', 'Comentários']
    missing_categories = [
        cat for cat in all_engagement_types 
        if cat not in used_categories and any(cat.lower() in ac.lower() for ac in available_categories)
    ]

    # Geração de recomendações personalizadas
    recommendations = []
    if not services_purchased:
        recommendations.append("🔹 Para iniciar sua autoridade digital, o primeiro passo é construir uma base sólida com **seguidores de qualidade**.")
        if 'Curtidas' in missing_categories:
            recommendations.append("🔹 **Curtidas** são essenciais para dar credibilidade imediata ao seu perfil.")
    else:
        if 'Seguidores' in used_categories and total_items > 100:
            recommendations.append("🔹 Sua base de seguidores já está se consolidando. Para maximizar seu alcance, invista em **visualizações** para Reels e Stories.")
        if 'Curtidas' not in used_categories:
            recommendations.append("🔹 Perfis com um bom equilíbrio de **curtidas** geram mais confiança. Recomendo adquirir um pacote.")
        if 'Comentários' not in used_categories:
            recommendations.append("🔹 **Comentários** criam uma percepção de popularidade e engajamento genuíno, atraindo ainda mais visitantes.")

    if not recommendations:
        recommendations.append("✅ Seu perfil está com uma estratégia de engajamento muito equilibrada. Continue mantendo a regularidade dos serviços.")

    # Montagem do relatório final
    report = (
        f"📊 **RELATÓRIO DE AUTORIDADE DIGITAL**\n\n"
        f"👤 Plataforma: {platform.capitalize()}\n"
        f"🔗 Perfil: @{username}\n"
        f"{'─' * 20}\n"
    )

    if total_items > 0:
        report += (
            f"📦 **Seu histórico de entregas:**\n"
            f"   • Total de itens: {total_items}\n"
            f"   • Diferentes estratégias: {variety}\n"
            f"   • Última atividade: {services_purchased[0][2] if services_purchased else 'N/A'}\n\n"
        )
    else:
        report += "⚠️ Nenhum pedido encontrado para este perfil. Vamos construir sua presença!\n\n"

    report += "💡 **Recomendações Estratégicas:**\n"
    for rec in recommendations:
        report += f"   {rec}\n"

    report += f"\n🔒 _Análise baseada em dados reais. Próxima avaliação disponível em 24h._"
    return report

# --- Handlers do ConversationHandler ---

async def start_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback do botão 'Consultoria'."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🔍 **Vamos analisar a saúde do seu perfil!**\n\n"
        "Envie o link completo do perfil que deseja analisar (Instagram, TikTok, YouTube)."
    )
    return ASKING_LINK

async def receive_link_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o link e gera a análise estratégica."""
    link = update.message.text.strip()
    platform, username = extract_username(link)

    if not platform:
        await update.message.reply_text(
            "❌ Link inválido. Certifique-se de que é um perfil público do Instagram, TikTok ou YouTube.\n\n"
            "Ex: `https://instagram.com/nome_do_perfil`"
        )
        return ASKING_LINK

    conn = sqlite3.connect(DB_PATH)
    report = analyze_profile(conn, update.effective_user.id, platform, username)
    conn.close()

    keyboard = [
        [InlineKeyboardButton("🛒 Ir para Loja", callback_data="back_to_categories")],
        [InlineKeyboardButton("🏠 Menu Inicial", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(report, reply_markup=reply_markup, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_consultoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Consultoria cancelada.")
    return ConversationHandler.END

# Handler que será importado no main.py
consultoria_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_consultoria, pattern="^consultoria$")],
    states={
        ASKING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link_consultoria)],
    },
    fallbacks=[CallbackQueryHandler(cancel_consultoria, pattern="^cancel$")],
)
