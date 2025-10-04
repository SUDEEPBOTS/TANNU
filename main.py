import os
import re
import datetime as dt
from openai import OpenAI
from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.helpers import mention_html

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL", "https://example.com")
SITE_NAME = os.getenv("SITE_NAME", "DeepSeek TG Bot")
MODEL = os.getenv("MODEL", "deepseek/deepseek-chat-v3.1:free")
OWNER_NAME = os.getenv("OWNER_NAME", "Sudeep")
HOME_GROUP_LINK = os.getenv("HOME_GROUP_LINK", "https://t.me/+y_unsn_S2eNkNzg1")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY missing")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={"HTTP-Referer": SITE_URL, "X-Title": SITE_NAME}
)

chat_history = {}
user_names = {}

WELCOME = "Namaste! 😊"

def now_ist():
    return dt.datetime.now()

def is_bot_mentioned(msg, bot_username: str) -> bool:
    if not msg or not msg.entities:
        return False
    text = msg.text or msg.caption or ""
    for ent in msg.entities:
        if ent.type == MessageEntity.MENTION:
            mention_text = text[ent.offset: ent.offset + ent.length]
            if mention_text.lower() == f"@{bot_username.lower()}":
                return True
    return False

def text_matches_hello(text: str) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    return t in {"hi", "hello", "hlo", "hey", "yo", "namaste", "namaskar"}

def contains_profanity(text: str) -> bool:
    if not text:
        return False
    bad_words = ["bc","mc","bhosdi","madarchod","chod","gandu","chutiya","chut","lund","randi","haraami","harami"]
    t = text.lower()
    pattern = r"\b(" + "|".join(map(re.escape, bad_words)) + r")\b"
    return re.search(pattern, t) is not None

def append_history(chat_id, role, content):
    msgs = chat_history.get(chat_id)
    if not msgs:
        msgs = [{"role": "system", "content": "Respond concisely in Hinglish."}]
    msgs.append({"role": role, "content": content})
    chat_history[chat_id] = msgs[-48:]

async def send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

async def get_bot_profile(context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    return me.first_name, me.username

def resolve_user_display(user) -> str:
    if not user:
        return "User"
    uid = user.id
    if uid in user_names:
        return user_names[uid]
    return user.first_name or "User"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands: /start, /help, /whoami, /reset — Groups: mention @bot par reply karta hoon; 'hello/hi' par tag karke greet karta hoon; Apna naam set: 'mera naam <Name>'; 'ghar/home' pucho to home group link; Time/date pucho to exact time aur group title."
    )

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me_name, me_user = await get_bot_profile(context)
    await update.message.reply_text(f"Mera naam {me_name} hai (username: @{me_user}). Owner: {OWNER_NAME}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_history.pop(chat_id, None)
    await update.message.reply_text("Context reset ho gaya.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    txt = msg.text or ""
    low = txt.lower()

    m = re.search(r"\b(mera|my)s+naams+([A-Za-z0-9_.- ]{1,32})", txt, flags=re.IGNORECASE)
    if m:
        name = m.group(2).strip()
        user_names[msg.from_user.id] = name
        await msg.reply_text(f"Thik hai, yaad rakha: {name}")
        return

    if "mera username" in low or "my username" in low:
        u = msg.from_user
        if u.username:
            await msg.reply_text(f"Tumhara username: @{u.username}")
        else:
            await msg.reply_text("Tumhara username set nahin hai.")
        return

    if "mera naam" in low or "my name" in low:
        u = msg.from_user
        saved = user_names.get(u.id)
        display = saved or (u.first_name or "User")
        mention = mention_html(u.id, display)
        await msg.reply_html(f"Tumhara naam: {mention}")
        return

    if "tumhara naam" in low or "tera naam" in low or "what is your name" in low:
        me_name, me_user = await get_bot_profile(context)
        await msg.reply_text(f"Mera naam {me_name} hai (username: @{me_user}). Owner: {OWNER_NAME}")
        return
    if "owner" in low:
        await msg.reply_text(f"Owner: {OWNER_NAME}")
        return

    if any(k in low for k in ["ghar", "home", "group", "link"]) and any(q in low for q in ["konsa", "kaunsa", "kya"]):
        await msg.reply_text(f"Mera home group: {HOME_GROUP_LINK}")
        return

    if any(k in low for k in ["time", "date", "samay", "waqt"]):
        now = now_ist()
        chat = update.effective_chat
        title = chat.title or "Private chat"
        await msg.reply_text(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')} | Group: {title}")
        return

    if contains_profanity(txt):
        user = msg.from_user
        mention = mention_html(user.id, resolve_user_display(user))
        warn = f"{mention} Kripya gaali-galoch se bachen. Sabka respect karein."
        try:
            await msg.reply_html(warn)
        except Exception:
            await msg.reply_text("Language theek rakhein, kripya.")
        return

    chat = update.effective_chat
    me_name, me_user = await get_bot_profile(context)
    if chat.type in ("group", "supergroup"):
        if is_bot_mentioned(msg, me_user):
            pass
        elif text_matches_hello(txt):
            await send_typing(update, context)
            user = msg.from_user
            mention = mention_html(user.id, resolve_user_display(user))
            await msg.reply_html(f"Hello {mention}! Kaise ho?")
            return
        else:
            return

    await send_typing(update, context)
    chat_id = chat.id
    append_history(chat_id, "user", txt)
    try:
        completion = client.chat.completions.create(model=MODEL, messages=chat_history.get(chat_id))
        reply = completion.choices[0].message.content
        append_history(chat_id, "assistant", reply)
        await msg.reply_text(reply)
    except Exception:
        await msg.reply_text("OpenRouter/API error. Thodi der baad try karo.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    if msg.reply_to_message is not None:
        return
    st = msg.sticker
    if not st:
        return
    await send_typing(update, context)
    kind = "sticker"
    try:
        emoji = getattr(st, "emoji", None) or "🧩"
        if getattr(st, "is_animated", False):
            kind = "animated sticker"
        elif getattr(st, "is_video", False):
            kind = "video sticker"
        reply_text = f"Nice {kind} {emoji}!"
        await msg.reply_text(reply_text)
    except Exception:
        await msg.reply_text("Cool sticker!")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
