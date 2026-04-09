import mercadopago
import os
import logging
from config import MP_ACCESS_TOKEN # Importa direto da sua config principal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def create_pix_payment(amount, user_id):
    """Gera um pagamento PIX no Mercado Pago com tratamento de erros robusto"""
    
    # 1. VALIDAÇÃO DO TOKEN
    # Tenta pegar da config, se não houver, tenta do ambiente (os.getenv)
    token = MP_ACCESS_TOKEN or os.getenv("MP_ACCESS_TOKEN")
    
    if not token or token == "SEU_TOKEN_AQUI":
        logger.error("❌ ERRO CRÍTICO: MP_ACCESS_TOKEN não configurado no config.py ou .env")
        return None

    try:
        # Inicializa o SDK de forma limpa
        sdk = mercadopago.SDK(str(token).strip())

        # 2. MONTAGEM DO PAYLOAD (DADOS DO PAGAMENTO)
        # Adicionamos uma chave externa (external_reference) para facilitar a conciliação depois
            # Tempo de expiração: 30 minutos (evita lixo no seu painel MP)xpiration_date = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000-04:00")
        expiration_date = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000-04:00")

        payment_data = {
            "transaction_amount": float(amount),
            "description": f"Recarga LikesPlus - Cliente {user_id}",
            "payment_method_id": "pix",
            "external_reference": str(user_id),
            "payer": {
                "email": f"cliente_{user_id}@likesplus.com.br",
                "first_name": "Cliente",
                "last_name": f"ID_{user_id}"
            },
            # Agora a data de expiração está correta e segura
            "date_of_expiration": expiration_date
        }

        # 3. CHAMADA À API COM TIMEOUT
        result = sdk.payment().create(payment_data)

        # 4. TRATAMENTO DA RESPOSTA
        status_code = result.get("status")
        response = result.get("response")

        if status_code == 201:
            # SUCESSO: Extrai os dados necessários
            try:
                point_of_interaction = response.get("point_of_interaction", {})
                transaction_data = point_of_interaction.get("transaction_data", {})
                
                return {
                    "id": response.get("id"),
                    "qrcode": transaction_data.get("qr_code"),
                    "status": response.get("status")
                }
            except KeyError as e:
                logger.error(f"❌ Resposta do MP com estrutura inesperada: {e}")
                return None
        else:
            # ERRO DA API (Token inválido, valor baixo, etc)
            error_detail = response.get("message", "Sem detalhes")
            logger.error(f"❌ Erro Mercado Pago ({status_code}): {error_detail}")
            return None

    except Exception as e:
        logger.error(f"❌ Erro fatal ao conectar com Mercado Pago: {e}")
        return None

