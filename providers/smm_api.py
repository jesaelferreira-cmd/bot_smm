import requests
from config import SMM_API_URL_1, SMM_API_KEY_1, SMM_API_URL_2, SMM_API_KEY_2

def get_services(url, key):
    params = {
        "key": key,
        "action": "services"
    }

    r = requests.get(url, params=params)
    return r.json()


def get_all_services():
    s1 = get_services(SMM_API_URL_1, SMM_API_KEY_1)
    s2 = get_services(SMM_API_URL_2, SMM_API_KEY_2)

    return {
        "provider1": s1,
        "provider2": s2
    }


def get_categories(services):
    categories = set()

    for s in services:
        categories.add(s["category"])

    return sorted(categories)

def add_order(url, key, service_id, link, quantity):
    payload = {
        "key": key,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity
    }
    try:
        r = requests.post(url, data=payload)
        return r.json()
    except Exception as e:
        return {"error": f"Erro de conexão: {str(e)}"}

