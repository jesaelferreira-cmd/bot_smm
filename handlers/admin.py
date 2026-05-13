import asyncio
import requests
import time
import subprocess
import os
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from config import SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2, ADMIN_ID, is_admin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.connection import get_connection  # apenas esta importação

logger = logging.getLogger(__name__)
START_TIME = time.time()

# =========================================================
# FUNÇÕES AUXILIARES (centavos)
# =========================================================
def cents_to_float(cents: int) -> float:
    return round(cents / 100.0, 2)

def float_to_cents(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)

def get_admin_stats():
    """Retorna (usuários, vendas, faturamento) usando PostgreSQL."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        # Soma de pedidos não cancelados; a coluna de valor é price (centavos)
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(price), 0)
            FROM orders
            WHERE status NOT IN ('Cancelado', 'Estornado', 'Canceled', 'Cancelled')
        """)
        sales, total_cents = cursor.fetchone()
        money = total_cents / 100.0 if total_cents else 0.0
        return users, sales, money
    finally:
        conn.close()

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        logger.warning(f"Acesso negado ao painel para {user_id}")
        return

    users, sales, money = get_admin_stats()

    def get_bal(url, key):
        if not url or not key:
            return "Offline ❌"
        try:
            r = requests.post(url, data={'key': key, 'action': 'balance'}, timeout=10)
            data = r.json()
            return f"{data.get('balance', '0')} {data.get('currency', 'BRL')}"
        except Exception as e:
            logger.error(f"Erro ao obter saldo do fornecedor: {e}")
            return "Offline ❌"

    bal1 = get_bal(SMM_API_URL_1, SMM_API_KEY_1)
    bal2 = get_bal(SMM_API_URL_2, SMM_API_KEY_2)

    uptime_seconds = int(time.time() - START_TIME)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"

    msg = (
        f"👑 **PAINEL ADMINISTRATIVO - LIKESPLUS**\n\n"
        f"⏱ **Uptime:** `{uptime_str}`\n"
        f"👥 **Usuários:** `{users}`\n"
        f"🛒 **Vendas:** `{sales}`\n"
        f"💰 **Faturamento:** `R$ {money:.2f}`\n\n"
        f"🏦 **Saldo Fornecedor 1:** `{bal1}`\n"
        f"🏦 **Saldo Fornecedor 2:** `{bal2}`\n\n"
        f"⚙️ **Comandos Rápidos:**\n"
        f"📈 `/margem 1.5` (Define 50% de lucro)\n"
        f"📢 `/promo 0.20` (Dá 20% de desconto temporário)\n"
        f"🔄 `/atualizar` (Sincroniza serviços)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# =========================================================
# 2. MARGEM
# =========================================================
async def set_margin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        valor = float(context.args[0])
        if valor <= 0:
            raise ValueError
        context.bot_data['margin'] = valor

        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('margem', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (valor,)
            )
            conn.commit()
            await update.message.reply_text(f"🚀 **Margem alterada para {valor}x.**\nRode `/atualizar` para sincronizar.")
        finally:
            conn.close()
    except:
        await update.message.reply_text("❌ Use: `/margem 2.0` (ex: 2.0 = 100% de lucro)")

# =========================================================
# 3. PROMOÇÃO
# =========================================================
async def set_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        valor = float(context.args[0])
        if not (0 <= valor <= 1):
            raise ValueError
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value REAL)")
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('promo', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (valor,)
            )
            conn.commit()
            await update.message.reply_text(f"🎁 Promoção de {valor*100:.0f}% gravada! Rode `/atualizar`.")
        finally:
            conn.close()
    except:
        await update.message.reply_text("❌ Use: `/promo 0.15` (para 15% de desconto)")

# =========================================================
# 4. ATUALIZAR SERVIÇOS (chama update_db.py)
# =========================================================
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text("⏳ Atualizando serviços e verificando banco de dados...")
    try:
        script_path = os.path.join(os.path.dirname(__file__), '..', 'update_db.py')
        result = subprocess.run(["python", script_path], capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            await update.message.reply_text("✅ Banco de dados e serviços atualizados com sucesso!")
            logger.info(f"Update DB output: {result.stdout}")
        else:
            await update.message.reply_text(f"❌ Erro na atualização. Verifique logs.\n{result.stderr[:200]}")
    except Exception as e:
        logger.error(f"Falha ao executar update_db: {e}")
        await update.message.reply_text(f"❌ Erro ao atualizar: {str(e)}")

# =========================================================
# 5. BROADCAST
# =========================================================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return

    text_content = None
    photo_file_id = None
    message = update.message

    if context.args:
        text_content = " ".join(context.args)

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        if not text_content and message.reply_to_message.caption:
            text_content = message.reply_to_message.caption
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        if message.caption and not text_content:
            text_content = message.caption

    if not text_content and not photo_file_id:
        await update.message.reply_text(
            "⚠️ Use: `/bc Sua mensagem aqui`\nOu responda a uma foto com `/bc` (legenda opcional).",
            parse_mode="Markdown"
        )
        return

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        usuarios = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao acessar banco para broadcast: {e}")
        await update.message.reply_text("❌ Erro ao buscar lista de usuários.")
        return

    total = len(usuarios)
    if total == 0:
        await update.message.reply_text("📭 Nenhum usuário cadastrado.")
        return

    sucesso = 0
    falha = 0
    aviso = await update.message.reply_text(f"📢 Iniciando transmissão para {total} usuários...")

    for user in usuarios:
        user_id = user[0]
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_file_id,
                    caption=text_content if text_content else None,
                    parse_mode="Markdown" if text_content else None
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text_content,
                    parse_mode="Markdown"
                )
            sucesso += 1
        except Exception as e:
            falha += 1
            logger.debug(f"Falha ao enviar para {user_id}: {e}")
        await asyncio.sleep(0.05)

    await aviso.edit_text(
        f"✅ **Transmissão Finalizada!**\n\n🟢 Sucesso: {sucesso}\n🔴 Falhas: {falha}",
        parse_mode="Markdown"
    )

# =========================================================
# 6. SET BALANCE (centavos)
# =========================================================
async def set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Use: `/setbalance ID VALOR` (ex: `/setbalance 123456 50.00`)", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
        valor_float = float(context.args[1].replace(',', '.'))
        if valor_float < 0:
            raise ValueError
        valor_cents = float_to_cents(valor_float)

        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Garante que o usuário existe
            cursor.execute(
                "INSERT INTO users (user_id, balance, first_name) VALUES (%s, 0, %s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (target_id, f"User_{target_id}")
            )
            conn.commit()

            cursor.execute(
                "UPDATE users SET balance = %s WHERE user_id = %s",
                (valor_cents, target_id)
            )
            conn.commit()

            await update.message.reply_text(
                f"✅ Saldo de `{target_id}` atualizado para **R$ {cents_to_float(valor_cents):.2f}**",
                parse_mode="Markdown"
            )

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"💰 Seu saldo foi alterado pelo administrador para: **R$ {cents_to_float(valor_cents):.2f}**",
                    parse_mode="Markdown"
                )
            except:
                pass
        finally:
            conn.close()

    except ValueError:
        await update.message.reply_text("❌ Formato inválido. Use números para ID e valor (ex: 10.50).")
    except Exception as e:
        logger.error(f"Erro em set_balance: {e}")
        await update.message.reply_text("❌ Erro interno ao atualizar saldo.")

# =========================================================
# (Opcional) Migração - Adaptada para PostgreSQL, se necessário
# =========================================================
async def migrate_balance_column(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Não mais necessária; mantida para compatibilidade."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("✅ Migração de colunas não é necessária no PostgreSQL atual.")

async def sync_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para sincronizar serviços do fornecedor (apenas admin)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador pode usar este comando.")
        return

    await update.message.reply_text("⏳ Sincronizando serviços com o fornecedor...")
    try:
        script_path = os.path.join(os.path.dirname(__file__), '..', 'update_db.py')
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM services")
                count = cursor.fetchone()[0]
            finally:
                conn.close()
            await update.message.reply_text(
                f"✅ **Sincronização concluída!**\n\n"
                f"📊 Total de serviços no banco: `{count}`\n"
                f"📡 Fornecedor: API atualizada\n\n"
                f"Use `/comprar` para ver os novos serviços."
            )
        else:
            await update.message.reply_text(f"❌ Erro na sincronização:\n```\n{result.stderr[:500]}\n```")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao executar: `{str(e)}`")

async def test_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe uma amostra dos serviços no banco (apenas admin)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas o administrador.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM services")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT DISTINCT category FROM services ORDER BY category LIMIT 15")
        categorias = [row[0] for row in cursor.fetchall()]

        cursor.execute("SELECT service_id, name, rate, category FROM services LIMIT 5")
        servicos = cursor.fetchall()
    finally:
        conn.close()

    msg = f"📊 **Total de serviços:** `{total}`\n\n"
    msg += "📂 **Categorias (amostra):**\n"
    for cat in categorias:
        msg += f"• `{cat}`\n"

    msg += "\n🛒 **Primeiros serviços:**\n"
    for s in servicos:
        msg += f"• ID `{s[0]}` – {s[1]} (R$ {float(s[2]):.2f}) – *{s[3]}*\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def debug_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas administrador.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM services")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT DISTINCT category FROM services WHERE rate > 0 LIMIT 10")
        raw_cats = [row[0] for row in cursor.fetchall()]

        cursor.execute("SELECT service_id, name, category FROM services LIMIT 5")
        sample_services = cursor.fetchall()

        from handlers.services import get_categories
        final_cats = get_categories()
    finally:
        conn.close()

    msg = f"=== DIAGNÓSTICO ===\n\n"
    msg += f"Total de serviços: {total}\n\n"
    msg += "Categorias cruas (banco, primeiras 10):\n"
    for cat in raw_cats:
        msg += f"- {cat}\n"
    msg += "\nCategorias processadas (get_categories):\n"
    for cat in final_cats[:10]:
        msg += f"- {cat}\n"
    msg += "\nAmostra de serviços (ID, nome, categoria):\n"
    for s in sample_services:
        msg += f"- {s[0]} – {s[1][:50]} – {s[2]}\n"

    await update.message.reply_text(msg)

async def test_api_fields(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    url = os.getenv("SMM_API_URL_1")
    key = os.getenv("SMM_API_KEY_1")
    try:
        r = requests.post(url, data={'key': key, 'action': 'services'}, timeout=30)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            primeiro = data[0]
            campos = list(primeiro.keys())
            await update.message.reply_text(f"Campos do primeiro serviço:\n{', '.join(campos)}")
        else:
            await update.message.reply_text("Resposta inesperada.")
    except Exception as e:
        await update.message.reply_text(f"Erro: {e}")

async def check_descriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Apenas administrador.")
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT service_id, name, description FROM services WHERE description IS NOT NULL AND description != '' LIMIT 5"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    if rows:
        msg = "📝 **Serviços com descrição (até 5):**\n\n"
        for r in rows:
            msg += f"🆔 `{r[0]}` – {r[1][:40]}\n📄 {r[2][:100]}\n\n"
    else:
        msg = "❌ Nenhum serviço possui descrição no banco."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_providers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT provider, COUNT(*) FROM services GROUP BY provider")
        counts = cursor.fetchall()
        msg = "📊 Serviços por fornecedor:\n"
        for prov, count in counts:
            msg += f"  Fornecedor {prov}: {count}\n"

        cursor.execute("SELECT DISTINCT category FROM services WHERE provider = 2 LIMIT 10")
        cats2 = cursor.fetchall()
        msg += "\n📂 Categorias do Fornecedor 2 (amostra):\n"
        for cat in cats2:
            msg += f"  - {cat[0]}\n"

        cursor.execute("SELECT DISTINCT category FROM services WHERE provider = 1 LIMIT 10")
        cats1 = cursor.fetchall()
        msg += "\n📂 Categorias do Fornecedor 1 (amostra):\n"
        for cat in cats1:
            msg += f"  - {cat[0]}\n"
    finally:
        conn.close()
    await update.message.reply_text(msg)

async def debug_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.services import get_categories

    cats = get_categories()
    if not cats:
        await update.message.reply_text("⚠️ Nenhuma categoria retornada.")
        return

    c1 = [c for c in cats if '[C1]' in c]
    c2 = [c for c in cats if '[C2]' in c]

    msg = (
        f"📊 **Total de categorias:** {len(cats)}\n"
        f"🔵 Fornecedor 1: {len(c1)}\n"
        f"🟢 Fornecedor 2: {len(c2)}\n\n"
    )
    if c2:
        preview = "\n".join(c2[:15])
        msg += f"**Exemplos C2:**\n{preview}"
    else:
        msg += "❌ **Nenhuma categoria do Fornecedor 2 foi retornada!**"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def fix_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /corrigir_pedido para inserir pedido manualmente e debitar saldo."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "Uso: /corrigir_pedido <user_id> <order_id_api> <amount_float> <provider_id> <service_name> <quantity>\n"
            "Exemplo: /corrigir_pedido 8250294969 874907 1.50 2 \"Seguidores Instagram\" 100"
        )
        return

    try:
        user_id = int(args[0])
        order_id_api = int(args[1])
        amount_float = float(args[2])
        provider_id = int(args[3])
        service_name = ' '.join(args[4:-1])
        quantity = int(args[-1])
    except ValueError:
        await update.message.reply_text("❌ Parâmetros inválidos. Verifique os tipos (números onde esperado).")

    amount_cents = int(amount_float * 100)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orders (user_id, service_name, quantity, price, order_id_api, status, date, provider_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, service_name, quantity, amount_cents, order_id_api, "Pendente",
             datetime.now().strftime("%d/%m/%Y %H:%M"), provider_id)
        )
        cursor.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (amount_cents, user_id)
        )
        conn.commit()
        await update.message.reply_text(
            f"✅ Pedido `{order_id_api}` corrigido.\n"
            f"👤 Usuário: `{user_id}`\n"
            f"💰 Valor debitado: R$ {amount_float:.2f}"
        )
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def limpar_fornecedor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /limpar_fornecedor 1 ou 2"""
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        prov = int(context.args[0])
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM services WHERE provider = %s", (prov,))
            conn.commit()
            await update.message.reply_text(f"✅ Serviços do Fornecedor {prov} removidos.")
        finally:
            conn.close()
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")

async def add_link_column(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /addlink – adiciona a coluna 'link' na tabela orders, se não existir (PostgreSQL)."""
    if not is_admin(update.effective_user.id):
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'orders' AND column_name = 'link'
                ) THEN
                    ALTER TABLE orders ADD COLUMN link TEXT;
                END IF;
            END;
            $$
        """)
        conn.commit()
        await update.message.reply_text("✅ Coluna 'link' verificada/adicionada com sucesso!")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Corrige estrutura do banco de forma segura, validando cada coluna antes de agir."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        messages = []

        # Função auxiliar segura: verifica se coluna existe e retorna seu tipo
        def get_column_type(table, column):
            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s;
            """, (table, column))
            row = cursor.fetchone()
            return row[0] if row else None

        # Função auxiliar segura: verifica se coluna existe
        def column_exists(table, column):
            return get_column_type(table, column) is not None

        # ================================================================
        # REMOVER FKs TEMPORARIAMENTE
        # ================================================================
        try:
            cursor.execute("""
                SELECT constraint_name, table_name
                FROM information_schema.table_constraints
                WHERE constraint_type = 'FOREIGN KEY'
                  AND table_name IN ('orders', 'commissions', 'consultoria_log')
                  AND constraint_schema = current_schema();
            """)
            fks = cursor.fetchall()
            for fk_name, fk_table in fks:
                try:
                    cursor.execute(f"ALTER TABLE {fk_table} DROP CONSTRAINT IF EXISTS {fk_name};")
                    messages.append(f"🔓 FK {fk_name} removida temporariamente")
                except Exception as e:
                    messages.append(f"⚠️ Não foi possível remover FK {fk_name}: {e}")
        except Exception as e:
            messages.append(f"⚠️ Erro ao consultar FKs: {e}")

        # ================================================================
        # USERS: user_id
        # ================================================================
        uid_type = get_column_type('users', 'user_id')
        if uid_type is None:
            # A coluna pode nem existir; tentar criar uma tabela mínima
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    balance BIGINT DEFAULT 0,
                    affiliate_balance BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            messages.append("✅ Tabela users criada (não existia)")
        else:
            if uid_type != 'bigint':
                cursor.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_pkey CASCADE;")
                cursor.execute("ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING (user_id::BIGINT);")
                cursor.execute("ALTER TABLE users ADD PRIMARY KEY (user_id);")
                messages.append("✅ user_id → BIGINT + PK")
            else:
                # Mesmo sendo bigint, garante que a PK existe
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.table_constraints
                    WHERE table_name = 'users' AND constraint_type = 'PRIMARY KEY';
                """)
                if cursor.fetchone()[0] == 0:
                    cursor.execute("ALTER TABLE users ADD PRIMARY KEY (user_id);")
                    messages.append("✅ PK adicionada em users")
                else:
                    messages.append("ℹ️ user_id já está correto")

        # ================================================================
        # USERS: balance
        # ================================================================
        if column_exists('users', 'balance'):
            bal_type = get_column_type('users', 'balance')
            if bal_type != 'bigint':
                cursor.execute("""
                    ALTER TABLE users
                    ALTER COLUMN balance TYPE BIGINT USING
                        (COALESCE(ROUND(balance::numeric * 100), 0))::BIGINT;
                """)
                messages.append("✅ balance → BIGINT (centavos)")
            else:
                messages.append("ℹ️ balance já está BIGINT")
        else:
            cursor.execute("ALTER TABLE users ADD COLUMN balance BIGINT DEFAULT 0;")
            messages.append("✅ balance criada (BIGINT)")

        # ================================================================
        # USERS: affiliate_balance
        # ================================================================
        if not column_exists('users', 'affiliate_balance'):
            cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance BIGINT DEFAULT 0;")
            messages.append("✅ affiliate_balance criada (BIGINT)")
        else:
            aff_type = get_column_type('users', 'affiliate_balance')
            if aff_type != 'bigint':
                cursor.execute("""
                    ALTER TABLE users
                    ALTER COLUMN affiliate_balance TYPE BIGINT USING
                        (COALESCE(ROUND(affiliate_balance::numeric * 100), 0))::BIGINT;
                """)
                messages.append("✅ affiliate_balance → BIGINT (centavos)")
            else:
                messages.append("ℹ️ affiliate_balance já está BIGINT")

        # ================================================================
        # USERS: colunas essenciais (first_name, username, created_at)
        # ================================================================
        for col, col_type in [('first_name', 'TEXT'), ('username', 'TEXT'), ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')]:
            if not column_exists('users', col):
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type};")
                messages.append(f"✅ Coluna {col} adicionada em users")

        # ================================================================
        # ORDERS: user_id
        # ================================================================
        if column_exists('orders', 'user_id'):
            o_uid_type = get_column_type('orders', 'user_id')
            if o_uid_type != 'bigint':
                cursor.execute("ALTER TABLE orders ALTER COLUMN user_id TYPE BIGINT USING (user_id::BIGINT);")
                messages.append("✅ orders.user_id → BIGINT")

        # ================================================================
        # ORDERS: price
        # ================================================================
        if column_exists('orders', 'price'):
            price_type = get_column_type('orders', 'price')
            if price_type != 'bigint':
                cursor.execute("""
                    ALTER TABLE orders
                    ALTER COLUMN price TYPE BIGINT USING
                        (COALESCE(ROUND(price::numeric * 100), 0))::BIGINT;
                """)
                messages.append("✅ orders.price → BIGINT (centavos)")
            else:
                messages.append("ℹ️ orders.price já está BIGINT")
        else:
            cursor.execute("ALTER TABLE orders ADD COLUMN price BIGINT DEFAULT 0;")
            messages.append("✅ orders.price criada (BIGINT)")

        conn.commit()
        await update.message.reply_text("\n".join(messages) + "\n\n✅ Correção estrutural concluída!")
    except Exception as e:
        conn.rollback()
        logger.exception("Erro no fix_all")
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_services_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Corrige a tabela services: converte rate para DECIMAL e ajusta tipos."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        messages = []

        # 1. Verificar e converter rate
        cursor.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'services' AND column_name = 'rate';
        """)
        row = cursor.fetchone()
        if row:
            rate_type = row[0]
            if rate_type != 'numeric':
                # Substitui vírgula por ponto, remove caracteres não numéricos e converte
                cursor.execute("""
                    ALTER TABLE services
                    ALTER COLUMN rate TYPE DECIMAL(10,2) USING
                        (COALESCE(
                            NULLIF(REGEXP_REPLACE(rate, '[^0-9.]', '', 'g'), '')::DECIMAL(10,2),
                            0
                        ));
                """)
                messages.append("✅ rate → DECIMAL(10,2)")
            else:
                messages.append("ℹ️ rate já está DECIMAL")

        # 2. Garantir que outras colunas numéricas existam e tenham tipo correto
        for col in ['min', 'max']:
            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'services' AND column_name = %s;
            """, (col,))
            col_row = cursor.fetchone()
            if col_row:
                if col_row[0] != 'integer':
                    cursor.execute(f"ALTER TABLE services ALTER COLUMN {col} TYPE INTEGER USING ({col}::INTEGER);")
                    messages.append(f"✅ services.{col} → INTEGER")
            else:
                cursor.execute(f"ALTER TABLE services ADD COLUMN {col} INTEGER DEFAULT 0;")
                messages.append(f"✅ services.{col} criada (INTEGER)")

        conn.commit()
        await update.message.reply_text("\n".join(messages) + "\n\n✅ Correção da tabela services concluída!")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_services_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Corrige tipos de todas as colunas numéricas da tabela services (rate, provider, min, max)."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        messages = []

        # ============================================================
        # 1. RATE → DECIMAL(10,2)
        # ============================================================
        cursor.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'services' AND column_name = 'rate';
        """)
        row = cursor.fetchone()
        if row:
            if row[0] != 'numeric':
                cursor.execute("""
                    ALTER TABLE services
                    ALTER COLUMN rate TYPE DECIMAL(10,2) USING
                        (COALESCE(
                            NULLIF(REGEXP_REPLACE(rate, '[^0-9.]', '', 'g'), '')::DECIMAL(10,2),
                            0
                        ));
                """)
                messages.append("✅ rate → DECIMAL(10,2)")
            else:
                messages.append("ℹ️ rate já está DECIMAL")
        else:
            cursor.execute("ALTER TABLE services ADD COLUMN rate DECIMAL(10,2) DEFAULT 0;")
            messages.append("✅ rate criada (DECIMAL)")

        # ============================================================
        # 2. PROVIDER → INTEGER
        # ============================================================
        cursor.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'services' AND column_name = 'provider';
        """)
        row = cursor.fetchone()
        if row:
            if row[0] != 'integer':
                # Remove caracteres não numéricos e converte
                cursor.execute("""
                    ALTER TABLE services
                    ALTER COLUMN provider TYPE INTEGER USING
                        (COALESCE(
                            NULLIF(REGEXP_REPLACE(provider, '[^0-9]', '', 'g'), '')::INTEGER,
                            0
                        ));
                """)
                messages.append("✅ provider → INTEGER")
            else:
                messages.append("ℹ️ provider já está INTEGER")
        else:
            cursor.execute("ALTER TABLE services ADD COLUMN provider INTEGER DEFAULT 0;")
            messages.append("✅ provider criada (INTEGER)")

        # ============================================================
        # 3. MIN e MAX → INTEGER
        # ============================================================
        for col in ['min', 'max']:
            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'services' AND column_name = %s;
            """, (col,))
            row = cursor.fetchone()
            if row:
                if row[0] != 'integer':
                    cursor.execute(f"""
                        ALTER TABLE services
                        ALTER COLUMN {col} TYPE INTEGER USING
                            (COALESCE(
                                NULLIF(REGEXP_REPLACE({col}, '[^0-9]', '', 'g'), '')::INTEGER,
                                0
                            ));
                    """)
                    messages.append(f"✅ {col} → INTEGER")
                else:
                    messages.append(f"ℹ️ {col} já está INTEGER")
            else:
                cursor.execute(f"ALTER TABLE services ADD COLUMN {col} INTEGER DEFAULT 0;")
                messages.append(f"✅ {col} criada (INTEGER)")

        conn.commit()
        await update.message.reply_text("\n".join(messages) + "\n\n✅ Correção completa da tabela services!")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_all_tables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cria/ajusta todas as tabelas do banco com tipos corretos."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        messages = []

        # ------------------------------------------------------------
        # Funções auxiliares seguras
        # ------------------------------------------------------------
        def col_exists(table, col):
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s;
            """, (table, col))
            return cursor.fetchone()[0] > 0

        def get_col_type(table, col):
            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s;
            """, (table, col))
            row = cursor.fetchone()
            return row[0] if row else None

        def ensure_col(table, col, col_def, conversion_sql=None):
            """Garante que a coluna existe com o tipo correto."""
            if not col_exists(table, col):
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def};")
                messages.append(f"✅ {table}.{col} criada ({col_def})")
            else:
                current = get_col_type(table, col)
                # Se tipo não bate e temos conversão, alteramos
                if conversion_sql and current != conversion_sql.split(' ')[0]:
                    cursor.execute(conversion_sql)
                    messages.append(f"✅ {table}.{col} convertida para {conversion_sql.split(' ')[0]}")
                else:
                    messages.append(f"ℹ️ {table}.{col} OK")

        # ------------------------------------------------------------
        # 1. Tabela USERS
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                balance BIGINT DEFAULT 0,
                affiliate_balance BIGINT DEFAULT 0,
                referred_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        messages.append("✅ Tabela 'users' pronta")

        # Ajustes manuais para colunas que podem estar com tipo errado
        # user_id
        if get_col_type('users', 'user_id') != 'bigint':
            cursor.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_pkey CASCADE;")
            cursor.execute("""
                ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING (user_id::BIGINT);
            """)
            cursor.execute("ALTER TABLE users ADD PRIMARY KEY (user_id);")
            messages.append("✅ users.user_id → BIGINT + PK")

        # balance
        if get_col_type('users', 'balance') != 'bigint':
            cursor.execute("""
                ALTER TABLE users ALTER COLUMN balance TYPE BIGINT
                USING (COALESCE(ROUND(balance::numeric * 100), 0));
            """)
            messages.append("✅ users.balance → BIGINT (centavos)")

        # affiliate_balance
        if not col_exists('users', 'affiliate_balance'):
            cursor.execute("ALTER TABLE users ADD COLUMN affiliate_balance BIGINT DEFAULT 0;")
            messages.append("✅ users.affiliate_balance criada (BIGINT)")
        elif get_col_type('users', 'affiliate_balance') != 'bigint':
            cursor.execute("""
                ALTER TABLE users ALTER COLUMN affiliate_balance TYPE BIGINT
                USING (COALESCE(ROUND(affiliate_balance::numeric * 100), 0));
            """)
            messages.append("✅ users.affiliate_balance → BIGINT (centavos)")

        # referred_by
        if not col_exists('users', 'referred_by'):
            cursor.execute("ALTER TABLE users ADD COLUMN referred_by BIGINT;")
            messages.append("✅ users.referred_by criada")

        # first_name, username, created_at
        for col, defn in [('first_name', 'TEXT'), ('username', 'TEXT'), ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')]:
            if not col_exists('users', col):
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn};")
                messages.append(f"✅ users.{col} criada")

        # ------------------------------------------------------------
        # 2. Tabela ORDERS
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                service_id TEXT,
                service_name TEXT,
                quantity INTEGER,
                link TEXT,
                price BIGINT DEFAULT 0,
                order_id_api TEXT,
                status TEXT DEFAULT 'pending',
                date TEXT,
                provider_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        messages.append("✅ Tabela 'orders' pronta")

        # Ajustar tipos principais
        if get_col_type('orders', 'user_id') != 'bigint':
            cursor.execute("ALTER TABLE orders ALTER COLUMN user_id TYPE BIGINT USING (user_id::BIGINT);")
            messages.append("✅ orders.user_id → BIGINT")
        if get_col_type('orders', 'price') != 'bigint':
            cursor.execute("""
                ALTER TABLE orders ALTER COLUMN price TYPE BIGINT
                USING (COALESCE(ROUND(price::numeric * 100), 0));
            """)
            messages.append("✅ orders.price → BIGINT (centavos)")
        for col in ['quantity', 'provider_id']:
            if get_col_type('orders', col) != 'integer':
                try:
                    cursor.execute(f"ALTER TABLE orders ALTER COLUMN {col} TYPE INTEGER USING ({col}::INTEGER);")
                    messages.append(f"✅ orders.{col} → INTEGER")
                except:
                    pass

        # Adicionar colunas faltantes comuns
        for col, defn in [('order_id_api', 'TEXT'), ('service_name', 'TEXT'),
                          ('link', 'TEXT'), ('status', "TEXT DEFAULT 'pending'"),
                          ('date', 'TEXT'), ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')]:
            if not col_exists('orders', col):
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {defn};")
                messages.append(f"✅ orders.{col} criada")

        # ------------------------------------------------------------
        # 3. Tabela SERVICES
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id SERIAL PRIMARY KEY,
                service_id TEXT UNIQUE,
                name TEXT,
                category TEXT,
                provider INTEGER,
                rate DECIMAL(10,2),
                min INTEGER,
                max INTEGER,
                description TEXT,
                status TEXT DEFAULT 'active'
            );
        """)
        messages.append("✅ Tabela 'services' pronta")

        # Ajustar provider
        if get_col_type('services', 'provider') != 'integer':
            cursor.execute("""
                ALTER TABLE services ALTER COLUMN provider TYPE INTEGER
                USING (COALESCE(NULLIF(REGEXP_REPLACE(provider, '[^0-9]', '', 'g'), '')::INTEGER, 0));
            """)
            messages.append("✅ services.provider → INTEGER")
        # Ajustar rate
        if get_col_type('services', 'rate') != 'numeric':
            cursor.execute("""
                ALTER TABLE services ALTER COLUMN rate TYPE DECIMAL(10,2)
                USING (COALESCE(NULLIF(REGEXP_REPLACE(rate, '[^0-9.]', '', 'g'), '')::DECIMAL(10,2), 0));
            """)
            messages.append("✅ services.rate → DECIMAL(10,2)")
        # min e max
        for col in ['min', 'max']:
            if get_col_type('services', col) != 'integer':
                cursor.execute(f"""
                    ALTER TABLE services ALTER COLUMN {col} TYPE INTEGER
                    USING (COALESCE(NULLIF(REGEXP_REPLACE({col}, '[^0-9]', '', 'g'), '')::INTEGER, 0));
                """)
                messages.append(f"✅ services.{col} → INTEGER")
        # description
        if not col_exists('services', 'description'):
            cursor.execute("ALTER TABLE services ADD COLUMN description TEXT;")
            messages.append("✅ services.description criada")

        # ------------------------------------------------------------
        # 4. Tabela SETTINGS
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        messages.append("✅ Tabela 'settings' pronta")

        # ------------------------------------------------------------
        # 5. Tabela COMMISSIONS
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commissions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount_cents BIGINT,
                referred_user_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        messages.append("✅ Tabela 'commissions' pronta")
        for col, defn in [('amount_cents', 'BIGINT'), ('referred_user_id', 'BIGINT')]:
            if get_col_type('commissions', col) and get_col_type('commissions', col) != 'bigint':
                cursor.execute(f"ALTER TABLE commissions ALTER COLUMN {col} TYPE BIGINT USING ({col}::BIGINT);")
                messages.append(f"✅ commissions.{col} → BIGINT")

        # ------------------------------------------------------------
        # 6. Tabela PROVIDERS_STATUS
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS providers_status (
                id SERIAL PRIMARY KEY,
                provider_id INTEGER,
                status TEXT,
                last_check TIMESTAMP
            );
        """)
        messages.append("✅ Tabela 'providers_status' pronta")

        # ------------------------------------------------------------
        # 7. Tabela CONSULTORIA_LOG
        # ------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consultoria_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                query TEXT,
                response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        messages.append("✅ Tabela 'consultoria_log' pronta")

        # ------------------------------------------------------------
        # Recriar foreign keys (caso existam tabelas filhas)
        # ------------------------------------------------------------
        # Tenta adicionar FK em orders
        try:
            cursor.execute("""
                ALTER TABLE orders ADD CONSTRAINT fk_orders_user
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE;
            """)
            messages.append("✅ FK orders → users criada")
        except:
            pass
        # commissions
        try:
            cursor.execute("""
                ALTER TABLE commissions ADD CONSTRAINT fk_commissions_user
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE;
            """)
            messages.append("✅ FK commissions → users criada")
        except:
            pass
        # consultoria_log
        try:
            cursor.execute("""
                ALTER TABLE consultoria_log ADD CONSTRAINT fk_consultoria_user
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE;
            """)
            messages.append("✅ FK consultoria_log → users criada")
        except:
            pass

        conn.commit()
        await update.message.reply_text("\n".join(messages) + "\n\n✅ Todas as tabelas verificadas e corrigidas!")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_provider_column(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Força a coluna provider de services para INTEGER."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Acesso negado.")
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            ALTER TABLE services
            ALTER COLUMN provider TYPE INTEGER USING
                (COALESCE(NULLIF(REGEXP_REPLACE(provider, '[^0-9]', '', 'g'), '')::INTEGER, 0));
        """)
        conn.commit()
        await update.message.reply_text("✅ provider → INTEGER")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def clean_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove caracteres especiais das categorias no banco."""
    if update.effective_user.id != ADMIN_ID:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Remove emojis e espaços extras no início/fim
        cursor.execute("""
            UPDATE services 
            SET category = TRIM(REGEXP_REPLACE(category, r'[^\w\s\[\]]+', '', 'g'))
            WHERE category IS NOT NULL;
        """)
        conn.commit()
        await update.message.reply_text("✅ Categorias limpas (emojis removidos).")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()

async def fix_referred_by(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Converte referred_by para BIGINT."""
    if update.effective_user.id != ADMIN_ID:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            ALTER TABLE users ALTER COLUMN referred_by TYPE BIGINT
            USING (referred_by::BIGINT);
        """)
        conn.commit()
        await update.message.reply_text("✅ referred_by → BIGINT")
    except Exception as e:
        conn.rollback()
        await update.message.reply_text(f"❌ Erro: {e}")
    finally:
        conn.close()
