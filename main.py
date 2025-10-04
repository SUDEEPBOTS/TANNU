import os
import re
import datetime as dt
from time import monotonic
from openai import OpenAI
from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.helpers import mention_html

# ========= Config / Constants =========
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SITE_URL = os.getenv("SITE_URL", "https://example.com")  # OpenRouter attribution
SITE_NAME = os.getenv("SITE_NAME", "DeepSeek TG Bot")

MODEL = os.getenv("MODEL", "deepseek/deepseek-chat-v3.1:free")

# Owner + AI persona
OWNER_NAME = os.getenv("OWNER_NAME", "Sudeep")
AI_NAME = os.getenv("AI_NAME", "Sudeep")  # AI ka naam bhi Sudeep

HOME_GROUP_LINK = os.getenv("HOME_GROUP_LINK", "https://t.me/+y_unsn_S2eNkNzg1")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY missing")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

# ========= OpenRouter client =========
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={"HTTP-Referer": SITE_URL, "X-Title": SITE_NAME}
)

# ========= In-memory stores =========
chat_history = {}       # per-chat AI context
user_names = {}         # {user_id: preferred display name}
nick_map = {}           # {chat_id: {lower_nick: user_id}} for "hello tannu"

def get_chat_nicks(chat_id: int):
    return nick_map.setdefault(chat_id, {})

WELCOME = "Namaste! Hinglish me baat karo, main DeepSeek se reply dunga 😊"

# Greeting control
greet_cooldown_user = {}   # {(chat_id, user_id): ts}
greet_cooldown_chat = {}   # {chat_id: ts}
GREET_USER_COOLDOWN = 60.0
GREET_CHAT_DEBOUNCE = 20.0
hello_set = {"hi", "hello", "hlo", "hey", "yo", "namaste", "namaskar"}

# ========= Helpers =========
def now_ist():
    # Add zoneinfo for strict IST if needed
    return dt.datetime.now()

def norm_token(s: str) -> str:
    return re.sub(r"[^w]+", "", (s or "").strip().lower())

def is_bot_mentioned(msg, bot_username: str) -> bool:
    if not msg or not msg.entities:
        return False
    text = msg.text or msg.caption or ""
    for ent in msg.entities:
        if ent.type == MessageEntity.MENTION:
            seg = text[ent.offset: ent.offset + ent.length]
            if seg.lower() == f"@{bot_username.lower()}":
                return True
    return False

def extract_hello_target(msg):
    """
    Returns tuple: (is_hello, target_user_id, target_username_str)
    - If text starts with a hello-token and contains TEXT_MENTION -> user_id returned.
    - If contains @username MENTION -> username string returned.
    - Else if just 'hello' without target -> (True, None, None)
    """
    text = msg.text or ""
    first = norm_token(text.split()[0] if text.split() else "")
    if first not in hello_set:
        return (False, None, None)
    if msg.entities:
        for ent in msg.entities:
            if ent.type == MessageEntity.TEXT_MENTION and ent.user:
                return (True, ent.user.id, None)
            if ent.type == MessageEntity.MENTION:
                seg = text[ent.offset: ent.offset + ent.length]  # like @tannu
                return (True, None, seg)
    return (True, None, None)

def extract_plain_target_word(text: str):
    parts = (text or "").strip().split(None, 2)
    if len(parts) >= 2 and norm_token(parts[0]) in hello_set:
        return parts[1].strip().lower()
    return None

def contains_profanity(text: str) -> bool:
    if not text:
        return False
    bad_words = [
        "bc", "mc", "bhosdi", "madarchod", "chod", "gandu", "chutiya", "chut", "lund",
        "randi", "haraami", "harami"
    ]
    t = text.lower()
    pattern = r"\b(" + "|".join(map(re.escape, bad_words)) + r")\b"
    return re.search(pattern, t) is not None

def append_history(chat_id, role, content):
    msgs = chat_history.get(chat_id)
    if not msgs:
        msgs = [{"role": "system", "content": f"Your name is {AI_NAME}. Respond concisely in Hinglish."}]
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

# ========= Commands =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands: /start, /help, /whoami, /reset, /setnick
"
        "- Groups: mention @bot par reply; 'hello/hi' par limited greet (cooldown).
"
        "- Reply to bot to continue chat without mention.
"
        "- Apna naam set: 'mera naam <Name>'.
"
        "- /setnick @user <nick> to map 'hello nick' → tag that user.
"
        "- 'ghar/home' par home link, 'time/date' par exact time + group title."
    )

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me_name, me_user = await get_bot_profile(context)
    await update.message.reply_text(f"Mera naam {me_name} ({AI_NAME}) hai (username: @{me_user}). Owner: {OWNER_NAME}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_history.pop(chat_id, None)
    await update.message.reply_text("Context reset ho gaya.")

async def setnick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # usage: /setnick @user nickname (suggest: reply to user's message for reliable mapping)
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Use: /setnick @user nickname (or reply to user's msg with /setnick nickname)")
        return
    target_user = None
    nick = None
    if update.message.reply_to_message and len(context.args) >= 1:
        # Reply-based: /setnick nickname
        target_user = update.message.reply_to_message.from_user
        nick = " ".join(context.args).strip().lower()
    else:
        # Handle + nickname
        if len(context.args) < 2:
            await update.message.reply_text("Use: /setnick @user nickname")
            return
        handle = context.args[0]
        nick = " ".join(context.args[1:]).strip().lower()
        # Try TEXT_MENTION first
        if update.message.entities:
            text = update.message.text
            for e in update.message.entities:
                if e.type == MessageEntity.TEXT_MENTION and e.user:
                    target_user = e.user
                    break
        # If only @username MENTION given, we can’t resolve id reliably without extra API; require reply/TextMention
        if not target_user:
            await update.message.reply_text("User ko reply karke /setnick nickname bhejo, ya TEXT_MENTION use karo.")
            return
    if not nick or not target_user:
        await update.message.reply_text("Nickname ya user missing.")
        return
    get_chat_nicks(update.effective_chat.id)[nick] = target_user.id
    await update.message.reply_text(f"OK, '{nick}' set for {target_user.first_name}.")

# ========= Text handler =========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    txt = msg.text or ""
    low = txt.lower()
    chat = update.effective_chat

    # Capture user preferred name: "mera naam XYZ" or "my name XYZ"
    m = re.search(r"\b(mera|my)s+naams+([A-Za-z0-9_. -]{1,32})", txt, flags=re.IGNORECASE)
    if m:
        name = m.group(2).strip()
        user_names[msg.from_user.id] = name
        await msg.reply_text(f"Thik hai, yaad rakha: {name}")
        return

    # User asks for their username
    if "mera username" in low or "my username" in low:
        u = msg.from_user
        await msg.reply_text(f"Tumhara username: @{u.username}" if u.username else "Tumhara username set nahin hai.")
        return

    # User asks for their name
    if "mera naam" in low and "mera naam " not in low or "my name" in low:
        u = msg.from_user
        saved = user_names.get(u.id)
        display = saved or (u.first_name or "User")
        mention = mention_html(u.id, display)
        await msg.reply_html(f"Tumhara naam: {mention}")
        return

    # Owner/bot name Q&A
    if "tumhara naam" in low or "tera naam" in low or "what is your name" in low:
        me_name, me_user = await get_bot_profile(context)
        await msg.reply_text(f"Mera naam {AI_NAME} hai (display: {me_name}, @{me_user}). Owner: {OWNER_NAME}")
        return
    if "owner" in low:
        await msg.reply_text(f"Owner: {OWNER_NAME}")
        return

    # Group moderation: profanity
    if contains_profanity(txt):
        user = msg.from_user
        mention = mention_html(user.id, resolve_user_display(user))
        warn = f"{mention} Kripya gaali-galoch se bachen. Sabka respect karein."
        try:
            await msg.reply_html(warn)
        except Exception:
            await msg.reply_text("Language theek rakhein, kripya.")
        return

    # Group behavior
    me_name, me_user = await get_bot_profile(context)
    if chat.type in ("group", "supergroup"):
        is_reply = msg.reply_to_message is not None
        reply_to_bot = bool(is_reply and msg.reply_to_message.from_user and msg.reply_to_message.from_user.username == me_user)

        # Allow replies to bot (continue convo)
        if reply_to_bot:
            pass  # continue intents/AI
        # Allow explicit @mention
        elif is_bot_mentioned(msg, me_user):
            pass
        else:
            # Greetings with cooldown
            nt = norm_token(txt)
            if nt in hello_set:
                now = monotonic()
                key_u = (chat.id, msg.from_user.id)
                last_u = greet_cooldown_user.get(key_u, 0.0)
                last_c = greet_cooldown_chat.get(chat.id, 0.0)
                if (now - last_u) >= GREET_USER_COOLDOWN and (now - last_c) >= GREET_CHAT_DEBOUNCE:
                    greet_cooldown_user[key_u] = now
                    greet_cooldown_chat[chat.id] = now
                    await send_typing(update, context)
                    mention = mention_html(msg.from_user.id, resolve_user_display(msg.from_user))
                    await msg.reply_html(f"Hello {mention}! Kaise ho?")
                return

            # Targeted greeting: “hello @user” or “hello <nick>”
            is_hello, target_uid, target_username = extract_hello_target(msg)
            if is_hello:
                now = monotonic()
                key_u = (chat.id, msg.from_user.id)
                last_u = greet_cooldown_user.get(key_u, 0.0)
                last_c = greet_cooldown_chat.get(chat.id, 0.0)
                if (now - last_u) >= GREET_USER_COOLDOWN and (now - last_c) >= GREET_CHAT_DEBOUNCE:
                    greet_cooldown_user[key_u] = now
                    greet_cooldown_chat[chat.id] = now
                    await send_typing(update, context)
                    sender = mention_html(msg.from_user.id, resolve_user_display(msg.from_user))
                    if target_uid:
                        target = mention_html(target_uid, "friend")
                        await msg.reply_html(f"Hello {target}! {sender} ne greet kiya. Kaise ho?")
                    elif target_username:
                        await msg.reply_text(f"Hello {target_username}! {resolve_user_display(msg.from_user)} ne greet kiya. Kaise ho?")
                    else:
                        # Try plain target via nick_map
                        nick = extract_plain_target_word(txt)
                        uid = get_chat_nicks(chat.id).get(nick or "", None)
                        if uid:
                            target = mention_html(uid, nick or "friend")
                            await msg.reply_html(f"Hello {target}! {sender} ne greet kiya. Kaise ho?")
                        else:
                            await msg.reply_html(f"Hello {sender}! Kaise ho?")
                return

            # Home/time without reply/mention -> ignore to prevent noise
            return

    # Intents (work in private, and in groups when allowed by above pass)
    if any(k in low for k in ["ghar", "home", "group", "link"]) and any(q in low for q in ["konsa", "kaunsa", "kya", "tumhara", "tumhra", "kaha"]):
        await msg.reply_text(f"Mera home group: {HOME_GROUP_LINK}")
        return

    if any(k in low for k in ["time", "date", "samay", "waqt"]):
        now = now_ist()
        title = update.effective_chat.title or "Private chat"
        await msg.reply_text(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')} | Group: {title}")
        return

    # Private chats or allowed group paths → AI
    await send_typing(update, context)
    chat_id = chat.id
    append_history(chat_id, "user", txt)
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=chat_history.get(chat_id)
        )
        reply = completion.choices[0].message.content
        append_history(chat_id, "assistant", reply)
        await msg.reply_text(reply)
    except Exception:
        await msg.reply_text("OpenRouter/API error. Thodi der baad try karo.")

# ========= Sticker handler =========
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    # Ignore if sticker is a reply to someone (not the bot)
    if msg.reply_to_message is not None:
        # If replying to bot's sticker/message and you want to react, change condition:
        me_name, me_user = await get_bot_profile(context)
        if msg.reply_to_message.from_user and msg.reply_to_message.from_user.username == me_user:
            pass
        else:
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

# ========= App bootstrap =========
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("setnick", setnick))

    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
