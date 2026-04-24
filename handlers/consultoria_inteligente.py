import re
import sqlite3
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)

# ------------------------------------------------
# EXTRAÇÃO DE USERNAME
# ------------------------------------------------
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

# ------------------------------------------------
# MAPEAMENTO DE NICHOS (expansível)
# ------------------------------------------------
NICHO_KEYWORDS = {
    'Beleza': ['makeup', 'beleza', 'cosméticos', 'skincare', 'cabelo', 'maquiagem'],
    'Jogos': ['game', 'gamer', 'jogo', 'streamer', 'live', 'gameplay'],
    'Culinária': ['receita', 'cozinha', 'chef', 'culinária', 'food', 'comida'],
    'Fitness': ['academia', 'fitness', 'musculação', 'treino', 'saúde', 'bem-estar'],
    'Música': ['música', 'cantor', 'banda', 'cover', 'instrumento', 'rap', 'trap'],
    'Tecnologia': ['tech', 'tecnologia', 'programação', 'dev', 'software', 'ia'],
    'Moda': ['moda', 'fashion', 'roupa', 'look', 'estilo', 'tendência'],
}

def detectar_nicho(username, platform, conn, user_id):
    """
    Detecta o nicho mais provável com base no username e no histórico de compras.
    """
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1

    # Refina com histórico de compras
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT s.category FROM orders o
            JOIN services s ON o.service_id = s.service_id
            WHERE o.user_id = ? AND o.link LIKE ?
        """, (user_id, f'%{username}%'))
        for row in cursor.fetchall():
            cat_lower = row[0].lower()
            for nicho, palavras in NICHO_KEYWORDS.items():
                for palavra in palavras:
                    if palavra in cat_lower:
                        scores[nicho] += 0.5
    except sqlite3.OperationalError as e:
        logger.warning(f"Erro ao consultar histórico (provavelmente coluna 'link' ausente): {e}")
        # Fallback: ignora essa parte se a estrutura não existir
        pass

    melhor = max(scores, key=scores.get)
    return melhor if scores[melhor] > 0 else 'Geral'

def recomendar_servicos(nicho, platform, conn, user_id):
    """
    Retorna até 5 serviços recomendados, evitando os já comprados e priorizando
    aqueles com melhor avaliação no histórico de consultoria.
    """
    cursor = conn.cursor()

    # Serviços disponíveis para a plataforma
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category
        FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    todos = cursor.fetchall()

    # Serviços já comprados pelo usuário (usando link ou nome do perfil)
    cursor.execute("""
        SELECT DISTINCT service_id FROM orders
        WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
    """, (user_id, f'%{platform}%', f'%{platform}%'))
    comprados = {row[0] for row in cursor.fetchall()}

    # Histórico de performance (consultoria_log)
    cursor.execute("""
        SELECT service_id, SUM(comprou) as compras, SUM(CASE WHEN avaliacao='positiva' THEN 1 ELSE 0 END) as positivas
        FROM consultoria_log
        WHERE nicho = ? AND platform = ?
        GROUP BY service_id
    """, (nicho, platform))
    perf = {}
    for row in cursor.fetchall():
        sid, compras, positivas = row
        perf[sid] = positivas / compras if compras > 0 else 0.0

    recomendacoes = []
    for s in todos:
        sid, name, rate, min_q, max_q, cat = s
        if sid in comprados:
            continue
        score = perf.get(sid, 0.1)  # se nunca foi recomendado, dá um pequeno bônus
        recomendacoes.append((sid, name, rate, min_q, max_q, cat, score))

    recomendacoes.sort(key=lambda x: x[-1], reverse=True)
    return recomendacoes[:5]

def analisar_perfil(link, user_id):
    """Realiza a análise completa e retorna (recomendacoes, relatorio)."""
    platform, username = extract_username(link)
    if not platform:
        return None, "❌ Link inválido. Certifique-se de que é um perfil público do Instagram, TikTok ou YouTube."

    conn = sqlite3.connect(DB_PATH)
    try:
        nicho = detectar_nicho(username, platform, conn, user_id)
        recomendacoes = recomendar_servicos(nicho, platform, conn, user_id)
    finally:
        conn.close()

    # Monta o relatório
    report = f"📊 **RELATÓRIO DE CONSULTORIA ESTRATÉGICA**\n\n"
    report += f"👤 Perfil: @{username} ({platform.capitalize()})\n"
    report += f"🏷️ Nicho detectado: **{nicho}**\n\n"

    if not recomendacoes:
        report += "✅ Todos os serviços disponíveis já foram adquiridos. Seu perfil está completo!"
    else:
        report += "💡 **Recomendações personalizadas:**\n"
        for i, (sid, name, rate, min_q, max_q, cat, score) in enumerate(recomendacoes):
            report += (
                f"{i+1}. *{name}*\n"
                f"   💰 R$ {rate:.2f} por 1000 | Mín: {min_q} | Máx: {max_q}\n"
                f"   📈 Potencial de impacto: {score*100:.0f}%\n\n"
            )
        report += "🔍 Essas sugestões são baseadas no seu nicho e no que funcionou para perfis semelhantes.\n"

    report += "\n📌 _Você pode avaliar cada recomendação após a compra para melhorar futuras consultorias._"
    return recomendacoes, report


def registrar_compra(user_id, service_id, nicho, platform, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO consultoria_log (user_id, service_id, nicho, platform, username, comprou, avaliacao)
        VALUES (?, ?, ?, ?, ?, 1, NULL)
    """, (user_id, service_id, nicho, platform, username))
    conn.commit()
    conn.close()

def avaliar_recomendacao(user_id, service_id, nota):
    avaliacao = 'positiva' if nota == '1' else 'negativa'
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE consultoria_log SET avaliacao = ?
        WHERE user_id = ? AND service_id = ? AND comprou = 1
    """, (avaliacao, user_id, service_id))
    conn.commit()
    conn.close()
