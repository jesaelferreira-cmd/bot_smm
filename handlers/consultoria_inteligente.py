import re
import sqlite3
import logging
from config import DB_PATH

# Configura o logger do módulo
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

def _coluna_existe(conn, tabela, coluna):
    """Verifica se uma coluna existe na tabela sem lançar exceção."""
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {coluna} FROM {tabela} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False

def detectar_nicho(username, platform, conn, user_id):
    """Detecta o nicho do perfil usando username e histórico de compras."""
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1

    # Reforço com histórico de compras (sem quebrar se link não existir)
    try:
        cursor = conn.cursor()
        link_existe = _coluna_existe(conn, 'orders', 'link')
        if link_existe:
            cursor.execute("""
                SELECT DISTINCT service_name FROM orders
                WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
            """, (user_id, f'%{username}%', f'%{username}%'))
        else:
            cursor.execute("""
                SELECT DISTINCT service_name FROM orders
                WHERE user_id = ? AND service_name LIKE ?
            """, (user_id, f'%{platform}%'))
        for row in cursor.fetchall():
            nome_servico = (row[0] or '').lower()
            for nicho, palavras in NICHO_KEYWORDS.items():
                for palavra in palavras:
                    if palavra in nome_servico:
                        scores[nicho] += 0.5
    except Exception as e:
        logger.warning(f"Erro ao analisar histórico de compras: {e}")

    melhor = max(scores, key=scores.get)
    return melhor if scores[melhor] > 0 else 'Geral'

def recomendar_servicos(nicho, platform, conn, user_id):
    """Recomenda até 5 serviços ainda não comprados, priorizando feedback."""
    cursor = conn.cursor()

    # 1. Todos os serviços disponíveis para a plataforma
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category
        FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    todos = cursor.fetchall()

    # 2. Serviços já comprados (nomes), com fallback se link não existir
    try:
        link_existe = _coluna_existe(conn, 'orders', 'link')
        if link_existe:
            cursor.execute("""
                SELECT DISTINCT service_name FROM orders
                WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
            """, (user_id, f'%{platform}%', f'%{platform}%'))
        else:
            cursor.execute("""
                SELECT DISTINCT service_name FROM orders
                WHERE user_id = ? AND service_name LIKE ?
            """, (user_id, f'%{platform}%'))
        comprados = {r[0].strip().lower() for r in cursor.fetchall() if r[0]}
    except Exception as e:
        logger.warning(f"Erro ao consultar pedidos anteriores: {e}")
        comprados = set()

    # 3. Feedback do consultoria_log (se a tabela existir)
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
            perf[sid] = (positivas / compras) if compras > 0 else 0.0
    except sqlite3.OperationalError:
        pass

    # 4. Monta lista de recomendações
    recomendacoes = []
    for s in todos:
        sid, name, rate, min_q, max_q, cat = s
        if name.strip().lower() in comprados:
            continue
        score = perf.get(sid, 0.0)
        if score == 0.0:
            score = 0.1  # pequeno bônus de novidade
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

    # Monta relatório
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
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO consultoria_log (user_id, service_id, nicho, platform, username, comprou, avaliacao)
            VALUES (?, ?, ?, ?, ?, 1, NULL)
        """, (user_id, service_id, nicho, platform, username))
        conn.commit()
    except Exception as e:
        logger.error(f"Erro ao registrar compra: {e}")
    finally:
        conn.close()

def avaliar_recomendacao(user_id, service_id, nota):
    avaliacao = 'positiva' if nota == '1' else 'negativa'
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE consultoria_log SET avaliacao = ?
            WHERE user_id = ? AND service_id = ? AND comprou = 1
        """, (avaliacao, user_id, service_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Erro ao avaliar recomendação: {e}")
    finally:
        conn.close()
