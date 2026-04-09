import requests
import sqlite3

# -----------------------------
# 1️⃣ Lista de fornecedores
# -----------------------------
# Adicione todos os fornecedores que você usa aqui
fornecedores = [
    {
        "nome": "Fornecedor1",
        "url": "https://provedorbrasil.com/api/v2",
        "key": "18e94d6b3e5693be84809d1ba3120898"
    },
    {
        "nome": "Fornecedor2",
        "url": "https://engajamais.com/api/v2",
        "key": "25e2c5d408188067f25314ebdc50e053"
    },
    # Adicione quantos quiser
]

# -----------------------------
# 2️⃣ Conectar no banco SQLite
# -----------------------------
conn = sqlite3.connect("database/bot_smm.db")
cursor = conn.cursor()

# Criar tabela de serviços (adicionando coluna fornecedor)
cursor.execute("""
CREATE TABLE IF NOT EXISTS services (
    service_id INTEGER,
    name TEXT,
    rate REAL,
    min INTEGER,
    max INTEGER,
    category TEXT,
    fornecedor TEXT,
    PRIMARY KEY (service_id, fornecedor)
)
""")

# -----------------------------
# 3️⃣ Limpar serviços antigos
# -----------------------------
cursor.execute("DELETE FROM services")
conn.commit()

# -----------------------------
# 4️⃣ Importar serviços de cada fornecedor
# -----------------------------
total = 0
for f in fornecedores:
    print(f"\nImportando serviços do fornecedor: {f['nome']} ...")
    data = {
        "key": f["key"],
        "action": "services"
    }

    try:
        response = requests.post(f["url"], data=data, timeout=20)
        response.raise_for_status()  # Garante que deu 200
        services = response.json()
    except Exception as e:
        print(f"Erro ao acessar {f['nome']}: {e}")
        continue

    # Salvar cada serviço no banco
    for s in services:
        cursor.execute("""
        INSERT OR REPLACE INTO services
        (service_id, name, rate, min, max, category, fornecedor)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            s["service"],
            s["name"],
            float(s["rate"]),
            int(s["min"]),
            int(s["max"]),
            s["category"],
            f["nome"]
        ))
        total += 1

# -----------------------------
# 5️⃣ Finalizar
# -----------------------------
conn.commit()
conn.close()
print(f"\n✅ Total de {total} serviços importados com sucesso!")
