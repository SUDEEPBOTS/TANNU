import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL", "https://example.com")
SITE_NAME = os.getenv("SITE_NAME", "DeepSeek TG Bot")
MODEL = os.getenv("MODEL", "deepseek/deepseek-chat-v3.1:free")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY missing (set in Heroku Config Vars).")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing (set in Heroku Config Vars).")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": SITE_URL,
        "X-Title": SITE_NAME
    }
)

history = {}
WELCOME = "Namaste! Hinglish me baat karo, main DeepSeek se reply dunga 😊"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # FIX: close the string properly (single line or triple quotes)
    await update.message.reply_text(
        "Bas message bhejo; main AI reply de dunga. /reset se context clear hoga."
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    history.pop(chat_id, None)
    await update.message.reply_text("Context reset ho gaya.")

def get_context(chat_id: int):
    msgs = history.get(chat_id)
    if not msgs:
        msgs = [{"role": "system", "content": "Respond concisely in Hinglish."}]
    return msgs

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    msgs = get_context(chat_id)
    msgs.append({"role": "user", "content": user_text})

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=msgs
        )
        reply = completion.choices[0].message.content
        msgs.append({"role": "assistant", "content": reply})
        history[chat_id] = msgs[-48:]
        await update.message.reply_text(reply)
    except Exception:
        await update.message.reply_text("OpenRouter/API error. Thodi der baad try karo.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
