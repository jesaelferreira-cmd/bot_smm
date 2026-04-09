import requests


def criar_pedido(fornecedor, service_id, link, quantidade):
    """
    Envia pedido para o fornecedor escolhido
    """

    payload = {
        "key": fornecedor["api_key"],
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantidade
    }

    try:
        response = requests.post(fornecedor["api_url"], data=payload, timeout=15)
        return response.json()

    except Exception as e:
        return {"error": str(e)}


def status_pedido(fornecedor, order_id):
    """
    Consulta status do pedido
    """

    payload = {
        "key": fornecedor["api_key"],
        "action": "status",
        "order": order_id
    }

    try:
        response = requests.post(fornecedor["api_url"], data=payload, timeout=15)
        return response.json()

    except Exception as e:
        return {"error": str(e)}


def listar_servicos(fornecedor):
    """
    Lista serviços disponíveis no fornecedor
    """

    payload = {
        "key": fornecedor["api_key"],
        "action": "services"
    }

    try:
        response = requests.post(fornecedor["api_url"], data=payload, timeout=15)
        return response.json()

    except Exception as e:
        return {"error": str(e)}
