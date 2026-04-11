from telegram import Update
from telegram.ext import ContextTypes

async def safe_edit(query, text: str, reply_markup=None, parse_mode="Markdown"):
    """Edita mensagem com texto ou legenda, com fallback para nova mensagem."""
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass
    
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception:
        pass
    
    await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
