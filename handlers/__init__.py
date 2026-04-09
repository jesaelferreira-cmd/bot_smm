# handlers/__init__.py
from . import start
from . import balance
from . import services
from . import orders
from . import buttons
from . import status
from . import admin
from . import affiliates
from . import user

# Exporta funções específicas se necessário
__all__ = [
    'start',
    'balance', 
    'services',
    'orders',
    'buttons',
    'status',
    'admin',
    'affiliates',
    'user'
]
