import re
import sqlite3
import logging
from config import DB_PATH
from datetime import datetime

logger = logging.getLogger(__name__)

# Mapeamento inicial de palavras-chave por nicho (expansível)
NICHO_KEYWORDS = {
    'Beleza': ['makeup', 'beleza', 'cosméticos', 'skincare', 'cabelo', 'maquiagem'],
    'Jogos': ['game', 'gamer', 'jogo', 'streamer', 'live', 'gameplay'],
    'Culinária': ['receita', 'cozinha', 'chef', 'culinária', 'food', 'comida'],
    'Fitness': ['academia', 'fitness', 'musculação', 'treino', 'saúde', 'bem-estar'],
    'Música': ['música', 'cantor', 'banda', 'cover', 'instrumento', 'rap', 'trap'],
    'Tecnologia': ['tech', 'tecnologia', 'programação', 'dev', 'software', 'ia'],
    'Moda': ['moda', 'fashion', 'roupa', 'look', 'estilo', 'tendência'],
}

def detectar_nicho(username, platform, conn=None):
    """
    Detecta o nicho do perfil usando palavras-chave no username e, se possível,
    analisando o histórico de serviços comprados.
    Retorna o nicho mais provável.
    """
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1
    melhor_nicho = max(scores, key=scores.get) if any(scores.values()) else None

    # Refina com histórico de compras (se disponível)
    if conn:
        cursor = conn.cursor()
        # Tenta inferir pelo nome dos serviços já comprados para este perfil
        cursor.execute("""
            SELECT s.category FROM orders o
            JOIN services s ON o.service_id = s.service_id
            WHERE o.user_id = ? AND o.link LIKE ?
        """, (user_id, f'%{username}%'))
        categorias = [row[0] for row in cursor.fetchall()]
        # Ajusta scores com base nas categorias (palavras-chave nelas)
        for cat in categorias:
            cat_lower = cat.lower()
            for nicho, palavras in NICHO_KEYWORDS.items():
                for palavra in palavras:
                    if palavra in cat_lower:
                        scores[nicho] += 0.5
        melhor_nicho = max(scores, key=scores.get) if any(scores.values()) else 'Geral'

    return melhor_nicho or 'Geral'

def recomendar_servicos(nicho, platform, conn, user_id):
    """
    Retorna uma lista de recomendações de serviços baseada no nicho, plataforma
    e histórico de compras do usuário (aprendizado).
    """
    cursor = conn.cursor()

    # 1. Busca todos os serviços disponíveis para a plataforma
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category
        FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    servicos_plataforma = cursor.fetchall()

    # 2. Verifica o que o usuário já comprou para esta plataforma/nicho
    cursor.execute("""
        SELECT service_id FROM orders
        WHERE user_id = ? AND link = ?
    """, (user_id, f'%{platform}%'))
    ja_comprados = {row[0] for row in cursor.fetchall()}

    # 3. Consulta o log de consultoria para aprender recomendações passadas
    cursor.execute("""
        SELECT service_id, SUM(CASE WHEN comprou=1 THEN 1 ELSE 0 END) as compras,
               SUM(CASE WHEN avaliacao='positiva' THEN 1 ELSE 0 END) as positivas
        FROM consultoria_log
        WHERE nicho = ? AND platform = ?
        GROUP BY service_id
    """, (nicho, platform))
    performance = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

    # 4. Ordena serviços por uma pontuação que prioriza:
    #    - Serviços ainda não comprados pelo usuário
    #    - Alta taxa de conversão/avaliação positiva no histórico
    #    - Variedade de tipos (seguidores, curtidas, etc.)
    recommendations = []
    for s in servicos_plataforma:
        sid, name, rate, min_q, max_q, cat = s
        if sid in ja_comprados:
            continue  # já comprou, não recomenda de novo (ou recomenda upgrade?)
        score = 0.0
        if sid in performance:
            compras, positivas = performance[sid]
            if compras > 0:
                score = positivas / compras  # taxa de satisfação
        else:
            score = 0.1  # pequeno bônus para novidade
        recommendations.append((sid, name, rate, min_q, max_q, cat, score))

    recommendations.sort(key=lambda x: x[-1], reverse=True)
    return recommendations[:5]  # top 5

def registrar_compra(user_id, service_id, nicho, platform, username):
    """Registra que o usuário comprou um serviço recomendado."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO consultoria_log (user_id, service_id, nicho, platform, username, comprou, avaliacao)
        VALUES (?, ?, ?, ?, ?, 1, NULL)
    """, (user_id, service_id, nicho, platform, username))
    conn.commit()
    conn.close()

def avaliar_recomendacao(user_id, service_id, nota):
    """Atualiza a avaliação de uma recomendação (1=positiva, 0=negativa)."""
    avaliacao = 'positiva' if nota == '1' else 'negativa'
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE consultoria_log SET avaliacao = ?
        WHERE user_id = ? AND service_id = ? AND comprou = 1
    """, (avaliacao, user_id, service_id))
    conn.commit()
    conn.close()

def analisar_perfil(link, user_id):
    """Realiza a análise completa e retorna um relatório personalizado."""
    platform, username = extract_username(link)
    if not platform:
        return None, "Link inválido."

    conn = sqlite3.connect(DB_PATH)
    nicho = detectar_nicho(username, platform, conn)
    if not nicho:
        conn.close()
        return None, "Não foi possível identificar o nicho do perfil."

    recomendacoes = recomendar_servicos(nicho, platform, conn, user_id)
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
