import re
import sqlite3
import logging
import requests
import json
from config import DB_PATH

logger = logging.getLogger(__name__)

# ------------------------------------------------
# MAPEAMENTO EXPANDIDO DE NICHOS (+100 palavras-chave)
# ------------------------------------------------
NICHO_KEYWORDS = {
    'Beleza e Estética': [
        'makeup', 'beleza', 'cosméticos', 'skincare', 'cabelo', 'maquiagem',
        'make', 'beauty', 'hair', 'nails', 'unhas', 'sobrancelha', 'estética',
        'dermato', 'pele', 'glam', 'glow', 'lábios', 'delineado', 'base',
        'corretivo', 'blush', 'iluminador', 'sombras', 'batom', 'gloss'
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
        'catlife', 'animais fofos', 'bichinho', 'estimação'
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
# VERIFICAÇÃO DE COLUNA (proteção contra ausência)
# ------------------------------------------------
def _coluna_existe(conn, tabela, coluna):
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {coluna} FROM {tabela} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False

# ------------------------------------------------
# SCRAPING DE DADOS PÚBLICOS (Instagram)
# ------------------------------------------------
def extract_profile_data(platform, username):
    try:
        if platform == 'instagram':
            url = f'https://www.instagram.com/{username}/'
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?});</script>'
                match = re.search(pattern, r.text, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    user_data = None
                    if 'graphql' in data:
                        user_data = data['graphql']['user']
                    elif 'user' in data:
                        user_data = data['user']
                    if user_data:
                        followers = user_data.get('edge_followed_by', {}).get('count', 0)
                        following = user_data.get('edge_follow', {}).get('count', 0)
                        posts = user_data.get('edge_owner_to_timeline_media', {}).get('count', 0)
                        biography = user_data.get('biography', '')
                        full_name = user_data.get('full_name', username)
                        return {'followers': followers, 'following': following, 'posts': posts,
                                'biography': biography, 'full_name': full_name}
        return None
    except Exception as e:
        logger.warning(f"Não foi possível extrair dados de @{username}: {e}")
        return None

# ------------------------------------------------
# DETECÇÃO DE NICHO
# ------------------------------------------------
def detectar_nicho(username, platform, conn, user_id):
    username_lower = username.lower()
    scores = {nicho: 0 for nicho in NICHO_KEYWORDS}
    for nicho, palavras in NICHO_KEYWORDS.items():
        for palavra in palavras:
            if palavra in username_lower:
                scores[nicho] += 1

    profile_data = extract_profile_data(platform, username)
    if profile_data and profile_data.get('biography'):
        bio_lower = profile_data['biography'].lower()
        for nicho, palavras in NICHO_KEYWORDS.items():
            for palavra in palavras:
                if palavra in bio_lower:
                    scores[nicho] += 2

    cursor = conn.cursor()
    try:
        if _coluna_existe(conn, 'orders', 'link'):
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
    except Exception:
        pass

    melhor = max(scores, key=scores.get)
    return melhor if scores[melhor] > 0 else 'Geral'

# ------------------------------------------------
# CÁLCULO DE MATURIDADE
# ------------------------------------------------
def calcular_maturidade(platform, username, conn, user_id):
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
        else:
            nivel = 'Avançado'
            descricao = 'Grande audiência. Foco em monetização e retenção.'
        return {'nivel': nivel, 'descricao': descricao, 'seguidores_reais': followers, 'posts': posts}

    cursor = conn.cursor()
    try:
        if _coluna_existe(conn, 'orders', 'link'):
            cursor.execute("""
                SELECT SUM(quantity) FROM orders
                WHERE user_id = ? AND (link LIKE ? OR service_name LIKE ?)
                AND status NOT IN ('Cancelado', 'Estornado')
            """, (user_id, f'%{username}%', f'%{username}%'))
        else:
            cursor.execute("""
                SELECT SUM(quantity) FROM orders
                WHERE user_id = ? AND service_name LIKE ?
                AND status NOT IN ('Cancelado', 'Estornado')
            """, (user_id, f'%{platform}%'))
        total = cursor.fetchone()[0] or 0
    except Exception:
        total = 0

    if total < 100:
        nivel = 'Iniciante (estimado)'
    elif total < 1000:
        nivel = 'Em crescimento (estimado)'
    else:
        nivel = 'Intermediário (estimado)'
    return {'nivel': nivel, 'descricao': 'Estimativa baseada no seu histórico de entregas.', 'seguidores_reais': None, 'posts': None}

# ------------------------------------------------
# BUSCA DE SERVIÇOS POR TIPO (regex) – usada pela estratégia
# ------------------------------------------------
def _buscar_servicos_por_tipo(conn, platform, tipo_regex, user_id, limit=2):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT service_id, name, rate, min, max, category FROM services
        WHERE category LIKE ? AND rate > 0
    """, (f'%{platform}%',))
    todos = cursor.fetchall()
    comprados = set()
    try:
        cursor.execute("SELECT DISTINCT service_name FROM orders WHERE user_id = ?", (user_id,))
        comprados = {r[0].strip().lower() for r in cursor.fetchall() if r[0]}
    except Exception:
        pass
    resultado = []
    for s in todos:
        sid, name, rate, min_q, max_q, cat = s
        if name.strip().lower() in comprados:
            continue
        if re.search(tipo_regex, name, re.IGNORECASE):
            resultado.append((sid, name, rate, min_q, max_q, cat))
            if len(resultado) >= limit:
                break
    return resultado

# ------------------------------------------------
# GERAÇÃO DE ESTRATÉGIA
# ------------------------------------------------
def gerar_estrategia(nicho, maturidade, platform, conn, user_id):
    nivel = maturidade['nivel']
    estrategia = {}
    if 'Iniciante' in nivel:
        estrategia['fase1'] = {
            'nome': '🏗️ Construção de Base',
            'descricao': 'Comece com seguidores para transmitir credibilidade.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'seguidor', user_id, limit=2)
        }
        estrategia['fase2'] = {
            'nome': '📊 Prova Social',
            'descricao': 'Adicione curtidas e visualizações para mostrar atividade.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'curtida|visualiza', user_id, limit=2)
        }
    else:
        estrategia['fase1'] = {
            'nome': '📈 Aceleração de Engajamento',
            'descricao': 'Intensifique curtidas e comentários para aumentar interação.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'curtida|comentári', user_id, limit=2)
        }
        estrategia['fase2'] = {
            'nome': '🎯 Expansão de Alcance',
            'descricao': 'Invista em visualizações para Reels/Stories.',
            'servicos': _buscar_servicos_por_tipo(conn, platform, 'visualiza', user_id, limit=2)
        }
    return estrategia

# ------------------------------------------------
# ANÁLISE PRINCIPAL
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

    report = "📊 **RELATÓRIO DE CONSULTORIA ESTRATÉGICA**\n\n"
    report += f"👤 **Perfil:** @{username}\n"
    report += f"📱 **Plataforma:** {platform.capitalize()}\n"
    report += f"🏷️ **Nicho detectado:** {nicho}\n"
    report += f"📈 **Nível de maturidade:** {maturidade['nivel']}\n"
    if maturidade.get('seguidores_reais'):
        report += f"👥 Seguidores reais: {maturidade['seguidores_reais']:,}\n"
    if maturidade.get('posts'):
        report += f"📝 Posts: {maturidade['posts']}\n"
    report += f"\n📋 **Diagnóstico:** {maturidade['descricao']}\n\n"
    report += "=" * 30 + "\n\n🎯 **PLANO ESTRATÉGICO**\n\n"

    todas_recomendacoes = []
    for fase_key, fase in estrategia.items():
        report += f"{fase['nome']}\n_{fase['descricao']}_\n"
        if fase['servicos']:
            report += "🔹 **Serviços recomendados:**\n"
            for i, (sid, name, rate, min_q, max_q, cat) in enumerate(fase['servicos']):
                report += f"   {i+1}. {name} — R$ {rate:.2f} (mín {min_q})\n"
                todas_recomendacoes.append((sid, name, rate, min_q, max_q, cat, 0.9))
        else:
            report += "   (Nenhum disponível no momento)\n"
        report += "\n"
    report += "💡 *Siga as fases e reavalie após 48h.*"
    return todas_recomendacoes, report

# ------------------------------------------------
# FUNÇÕES DE APRENDIZADO (mantidas)
# ------------------------------------------------
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
