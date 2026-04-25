import re
import sqlite3
import logging
import requests
from config import DB_PATH

logger = logging.getLogger(__name__)

# ------------------------------------------------
# MAPEAMENTO EXPANDIDO DE NICHOS (+100 palavras-chave)
# ------------------------------------------------
NICHO_KEYWORDS = {
    'Beleza e Estética': [
        'makeup', 'beleza', 'cosméticos', 'skincare', 'cabelo', 'maquiagem',
        'make', 'beauty', 'hair', 'nails', 'unhas', 'sobrancelha', 'estética',
        'dermato', 'pele', 'glam', 'glow', 'lábios', ' delineado', 'base',
        'corretivo', 'blush', 'iluminador', 'sombras', 'batom', ' gloss'
    ],
    'Fitness e Saúde': [
        'academia', 'fitness', 'musculação', 'treino', 'saúde', 'bem-estar',
        'fit', 'gym', 'workout', 'bodybuilding', 'crossfit', 'maromba',
        'dieta', 'nutrição', 'nutri', 'emagrecimento', 'peso', 'shape',
        'cardio', 'hipertrofia', 'suplementos', 'whey', 'proteína'
    ],
    'Gastronomia e Culinária': [
        'receita', 'cozinha', 'chef', 'culinária', 'food', 'comida',
        'gastronomia', 'restaurante', 'sabor', 'prato', 'gourmet',
        'confeitaria', 'bolo', 'doce', 'salgado', 'bistrô', 'menu',
        'foodie', 'foodporn', 'caseiro', 'artesanal', 'brasileira'
    ],
    'Música e Entretenimento': [
        'música', 'cantor', 'banda', 'cover', 'instrumento', 'rap', 'trap',
        'funk', 'sertanejo', 'pop', 'rock', 'eletrônica', 'violão',
        'guitarra', 'bateria', 'vocal', 'show', 'live', 'palco',
        'artista', 'cantora', 'mc', 'dj', 'produtor', 'beatmaker'
    ],
    'Tecnologia e Desenvolvimento': [
        'tech', 'tecnologia', 'programação', 'dev', 'software', 'ia',
        'inteligência artificial', 'machine learning', 'dados', 'data',
        'python', 'javascript', 'react', 'node', 'fullstack', 'backend',
        'frontend', 'mobile', 'app', 'startup', 'inovação', 'digital'
    ],
    'Moda e Lifestyle': [
        'moda', 'fashion', 'roupa', 'look', 'estilo', 'tendência',
        'streetwear', 'vintage', 'luxo', 'acessórios', 'bolsa', 'sapato',
        'tênis', 'óculos', 'joia', 'relógio', 'desfile', 'coleção',
        'modelo', 'influencer', 'blogger', 'digital influencer'
    ],
    'Jogos e eSports': [
        'game', 'gamer', 'jogo', 'streamer', 'live', 'gameplay',
        'esports', 'valorant', 'lol', 'league of legends', 'csgo',
        'fortnite', 'minecraft', 'roblox', 'pubg', 'freefire',
        'twitch', 'youtube gaming', 'playstation', 'xbox', 'nintendo'
    ],
    'Negócios e Empreendedorismo': [
        'negócio', 'empreendedor', 'empresa', 'startup', 'marketing',
        'vendas', 'liderança', 'coach', 'mentor', 'consultor',
        'investimento', 'finanças', 'dinheiro', 'riqueza', 'sucesso',
        'produtividade', 'gestão', 'estratégia', 'crescimento', 'scale'
    ],
    'Arte e Design': [
        'arte', 'design', 'ilustração', 'pintura', 'desenho', 'gravura',
        'fotografia', 'foto', 'câmera', 'ensaio', 'retrato', 'paisagem',
        'artista visual', 'designer', 'gráfico', 'ux', 'ui', 'branding',
        'identidade visual', 'criatividade', 'criativo'
    ],
    'Viagem e Aventura': [
        'viagem', 'viajante', 'turismo', 'aventura', 'explorar', 'destino',
        'mochilão', 'natureza', 'trilha', 'montanha', 'praia', 'mar',
        'nomade', 'mundo', 'viajar', 'trip', 'travel', 'wanderlust'
    ],
    'Pets e Animais': [
        'pet', 'cachorro', 'gato', 'animal', 'dog', 'cat', 'veterinário',
        'adoção', 'raça', 'filhote', 'petlover', 'petstagram', 'doglife',
        'catlife', 'animais fofos', 'bichinho', ' estimação'
    ],
}

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
# EXTRAÇÃO DE DADOS PÚBLICOS DO PERFIL (via scraping)
# ------------------------------------------------
def extract_profile_data(platform, username):
    """Tenta extrair seguidores, posts e biografia de um perfil público."""
    try:
        if platform == 'instagram':
            url = f'https://www.instagram.com/{username}/'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                # Tenta extrair dados do JSON embutido na página
                pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?});</script>'
                match = re.search(pattern, r.text, re.DOTALL)
                if match:
                    import json
                    data = json.loads(match.group(1))
                    user_data = None
                    # Navega até os dados do perfil
                    for key in ['graphql', 'user']:
                        if 'graphql' in data:
                            user_data = data['graphql']['user']
                            break
                        if 'user' in data:
                            user_data = data['user']
                            break
                    if user_data:
                        followers = user_data.get('edge_followed_by', {}).get('count', 0)
                        following = user_data.get('edge_follow', {}).get('count', 0)
                        posts = user_data.get('edge_owner_to_timeline_media', {}).get('count', 0)
                        biography = user_data.get('biography', '')
                        full_name = user_data.get('full_name', username)
                        return {
                            'followers': followers,
                            'following': following,
                            'posts': posts,
                            'biography': biography,
                            'full_name': full_name
                        }
        return None
    except Exception as e:
        logger.warning(f"Não foi possível extrair dados de @{username}: {e}")
        return None

# ------------------------------------------------
# DETECÇÃO DE NICHO (agora usando biografia se disponível)
# ------------------------------------------------
def detectar_nicho(username, platform, conn, user_id):
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}

    # Analisa o username
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1

    # Tenta extrair biografia e usa para refinar
    profile_data = extract_profile_data(platform, username)
    if profile_data and profile_data.get('biography'):
        bio_lower = profile_data['biography'].lower()
        for nicho, palavras in NICHO_KEYWORDS.items():
            for palavra in palavras:
                if palavra in bio_lower:
                    scores[nicho] += 2  # biografia tem peso maior

    # Reforço com histórico de compras
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT service_name FROM orders
            WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
        """, (user_id, f'%{username}%', f'%{username}%'))
        for row in cursor.fetchall():
            nome_servico = (row[0] or '').lower()
            for nicho, palavras in NICHO_KEYWORDS.items():
                for palavra in palavras:
                    if palavra in nome_servico:
                        scores[nicho] += 0.5
    except Exception:
        pass

    melhor = max(scores, key=scores.get)
    return melhor if scores[melhor] > 0 else 'Geral'

# ------------------------------------------------
# ANÁLISE DE MATURIDADE DO PERFIL
# ------------------------------------------------
def calcular_maturidade(platform, username, conn, user_id):
    """Calcula nível de maturidade baseado em dados reais ou histórico."""
    profile_data = extract_profile_data(platform, username)

    if profile_data and profile_data.get('followers', 0) > 0:
        followers = profile_data.get('followers', 0)
        posts = profile_data.get('posts', 0)

        if followers < 500:
            nivel = 'Iniciante'
            descricao = 'Perfil em fase inicial. Foco em construir autoridade.'
        elif followers < 5000:
            nivel = 'Em crescimento'
            descricao = 'Já possui uma base. Hora de impulsionar engajamento.'
        elif followers < 50000:
            nivel = 'Intermediário'
            descricao = 'Perfil estabelecido. Trabalhe consistência e conversão.'
        else:
            nivel = 'Avançado'
            descricao = 'Grande audiência. Foco em monetização e retenção.'

        return {
            'nivel': nivel,
            'descricao': descricao,
            'seguidores_reais': followers,
            'posts': posts
        }

    # Fallback: estima pelo histórico de compras
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(quantity) FROM orders
        WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
        AND status NOT IN ('Cancelado', 'Estornado')
    """, (user_id, f'%{username}%', f'%{username}%'))
    total = cursor.fetchone()[0] or 0

    if total < 100:
        nivel = 'Iniciante (estimado)'
    elif total < 1000:
        nivel = 'Em crescimento (estimado)'
    else:
        nivel = 'Intermediário (estimado)'

    return {
        'nivel': nivel,
        'descricao': 'Estimativa baseada no seu histórico de entregas no LikesPlus.',
        'seguidores_reais': None,
        'posts': None
    }

# ------------------------------------------------
# GERAÇÃO DE ESTRATÉGIA PERSONALIZADA
# ------------------------------------------------
def gerar_estrategia(nicho, maturidade, platform, conn, user_id):
    """Cria um plano estratégico em 3 fases com recomendações específicas."""
    nivel = maturidade['nivel']
    estrategia = {}

    if 'Iniciante' in nivel:
        estrategia['fase1'] = {
            'nome': '🏗️ Construção de Base',
            'descricao': 'Comece com uma base sólida de seguidores reais para passar credibilidade.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'seguidor', user_id, limit=2)
        }
        estrategia['fase2'] = {
            'nome': '📊 Geração de Prova Social',
            'descricao': 'Adicione curtidas e visualizações para mostrar atividade no perfil.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'curtida|visualiza', user_id, limit=2)
        }
    elif 'crescimento' in nivel:
        estrategia['fase1'] = {
            'nome': '📈 Aceleração de Engajamento',
            'descricao': 'Intensifique curtidas e comentários para aumentar a taxa de interação.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'curtida|comentári', user_id, limit=2)
        }
        estrategia['fase2'] = {
            'nome': '🎯 Expansão de Alcance',
            'descricao': 'Invista em visualizações para Reels e Stories para atingir novos públicos.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'visualiza', user_id, limit=2)
        }
    else:
        estrategia['fase1'] = {
            'nome': '💎 Manutenção de Autoridade',
            'descricao': 'Reforce sua posição com serviços premium e comentários personalizados.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'comentári|premium', user_id, limit=2)
        }
        estrategia['fase2'] = {
            'nome': '🚀 Escala e Monetização',
            'descricao': 'Maximize o retorno com pacotes de alto volume e segmentação.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'seguidor|curtida', user_id, limit=2)
        }

    return estrategia

def _buscar_servicos_por_tipo(conn, platform, tipo_regex, user_id, limit=2):
    """Busca serviços por tipo (regex no nome), evitando já comprados."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category
        FROM services
        WHERE category LIKE ? AND rate > 0 AND name REGEXP ?
        LIMIT ?
    """, (f'%{platform}%', tipo_regex, limit * 2))
    candidatos = cursor.fetchall()

    # Filtra já comprados (se coluna link existir)
    comprados = set()
    try:
        cursor.execute("""
            SELECT DISTINCT service_name FROM orders WHERE user_id = ?
        """, (user_id,))
        comprados = {r[0].strip().lower() for r in cursor.fetchall() if r[0]}
    except Exception:
        pass

    resultado = []
    for s in candidatos:
        sid, name, rate, min_q, max_q, cat = s
        if name.strip().lower() not in comprados:
            resultado.append((sid, name, rate, min_q, max_q, cat))
            if len(resultado) >= limit:
                break
    return resultado

# ------------------------------------------------
# ANALISE COMPLETA DO PERFIL
# ------------------------------------------------
def analisar_perfil(link, user_id):
    platform, username = extract_username(link)
    if not platform:
        return None, "❌ Link inválido. Certifique-se de que é um perfil público do Instagram, TikTok ou YouTube."

    conn = sqlite3.connect(DB_PATH)
    try:
        nicho = detectar_nicho(username, platform, conn, user_id)
        maturidade = calcular_maturidade(platform, username, conn, user_id)
        estrategia = gerar_estrategia(nicho, maturidade, platform, conn, user_id)
    finally:
        conn.close()

    # Monta o relatório profissional
    report = "📊 **RELATÓRIO DE CONSULTORIA ESTRATÉGICA**\n\n"
    report += f"👤 **Perfil:** @{username}\n"
    report += f"📱 **Plataforma:** {platform.capitalize()}\n"
    report += f"🏷️ **Nicho detectado:** {nicho}\n"
    report += f"📈 **Nível de maturidade:** {maturidade['nivel']}\n\n"

    if maturidade.get('seguidores_reais'):
        report += f"👥 Seguidores reais: {maturidade['seguidores_reais']:,}\n"
    if maturidade.get('posts'):
        report += f"📝 Posts: {maturidade['posts']}\n"

    report += f"\n📋 **Diagnóstico:** {maturidade['descricao']}\n\n"

    report += "=" * 30 + "\n\n"
    report += "🎯 **PLANO ESTRATÉGICO PERSONALIZADO**\n\n"

    todas_recomendacoes = []
    for fase_key, fase in estrategia.items():
        report += f"{fase['nome']}\n"
        report += f"_{fase['descricao']}_\n\n"
        if fase['servicos']:
            report += "🔹 **Serviços recomendados:**\n"
            for i, (sid, name, rate, min_q, max_q, cat) in enumerate(fase['servicos']):
                report += (
                    f"   {i+1}. {name}\n"
                    f"      💰 R$ {rate:.2f} por 1000 | Mín: {min_q}\n"
                )
                todas_recomendacoes.append((sid, name, rate, min_q, max_q, cat, 0.8))
        else:
            report += "   (Nenhum serviço disponível no momento)\n"
        report += "\n"

    report += "=" * 30 + "\n\n"
    report += "💡 **Próximos passos:**\n"
    report += "• Comece pela Fase 1 para construir uma base sólida.\n"
    report += "• Após 48h, avalie os resultados e prossiga para a Fase 2.\n"
    report += "• Use o comando `/consultoria` novamente para reavaliar seu perfil.\n\n"

    report += "📌 _Este relatório é baseado em dados reais do seu perfil e histórico de compras._"

    return todas_recomendacoes, report
