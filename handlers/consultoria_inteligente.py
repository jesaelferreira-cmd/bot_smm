import re
import sqlite3
import logging
from config import DB_PATH

logger = logging.getLogger(__name__)

# ------------------------------------------------
# EXTRAÇÃO DE USERNAME
# ------------------------------------------------
def extract_username(link: str):
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
# MAPEAMENTO DE NICHOS
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
    """Detecta o nicho com base no username e nas categorias dos serviços já comprados (via service_name)."""
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1

    # Tenta inferir pelo nome dos serviços comprados anteriormente
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT service_name FROM orders
            WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
        """, (user_id, f'%{username}%', f'%{username}%'))
        for row in cursor.fetchall():
            nome_servico = row[0].lower() if row[0] else ''
            for nicho, palavras in NICHO_KEYWORDS.items():
                for palavra in palavras:
                    if palavra in nome_servico:
                        scores[nicho] += 0.5
    except sqlite3.OperationalError:
        # Coluna link pode ainda não existir; ignora essa parte
        pass

    melhor = max(scores, key=scores.get)
    return melhor if scores[melhor] > 0 else 'Geral'

def recomendar_servicos(nicho, platform, conn, user_id):
    """Recomenda serviços ainda não comprados, priorizando os com bom feedback no consultoria_log."""
    cursor = conn.cursor()

    # 1. Serviços disponíveis para a plataforma
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category
        FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    todos_servicos = cursor.fetchall()

    # 2. Nomes de serviços já comprados para esta plataforma (evitar recomendar de novo)
    cursor.execute("""
        SELECT DISTINCT service_name FROM orders
        WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
    """, (user_id, f'%{platform}%', f'%{platform}%'))
    nomes_comprados = {row[0].strip().lower() for row in cursor.fetchall() if row[0]}

    # 3. Histórico de performance no consultoria_log (se a tabela existir)
    perf = {}
    try:
        cursor.execute("""
            SELECT service_id, SUM(comprou) as compras,
                   SUM(CASE WHEN avaliacao='positiva' THEN 1 ELSE 0 END) as positivas
            FROM consultoria_log
            WHERE nicho = ? AND platform = ?
            GROUP BY service_id
        """, (nicho, platform))
        for row in cursor.fetchall():
            sid, compras, positivas = row
            perf[sid] = positivas / compras if compras > 0 else 0.0
    except sqlite3.OperationalError:
        # Tabela consultoria_log ainda não existe
        pass

    # 4. Monta a lista de recomendações
    recomendacoes = []
    for s in todos_servicos:
        sid, name, rate, min_q, max_q, cat = s
        # Pula se o nome do serviço já foi comprado (comparação case‑insensitive)
        if name.strip().lower() in nomes_comprados:
            continue
        score = perf.get(sid, 0.0)
        if score == 0.0:
            score = 0.1  # pequeno bônus para novidade
        recomendacoes.append((sid, name, rate, min_q, max_q, cat, score))

    recomendacoes.sort(key=lambda x: x[-1], reverse=True)
    return recomendacoes[:5]

def analisar_perfil(link, user_id):
    """Retorna (lista_recomendacoes, texto_relatorio)."""
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
