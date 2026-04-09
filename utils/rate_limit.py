import time
from collections import defaultdict
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

# Dicionário para armazenar timestamps de cada usuário
user_last_command = defaultdict(float)

def rate_limit(seconds: int = 3):
    """Decorator que limita um comando a no máximo 1 vez a cada 'seconds' segundos por usuário"""
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            now = time.time()
            if now - user_last_command[user_id] < seconds:
                await update.message.reply_text(f"⏳ Calma! Aguarde {seconds} segundos antes de usar este comando novamente.")
                return
            user_last_command[user_id] = now
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
