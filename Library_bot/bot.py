import sqlite3
import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

TOKEN = "YOUR_TOKEN_HERE"  # 👈 paste your token

# --- Conversation states ---
LOGIN_USER, LOGIN_PASS = range(2)
UPLOAD_COURSE, UPLOAD_FILE, UPLOAD_TITLE = range(3, 6)

# ────────────────────────────
# DATABASE SETUP
# ────────────────────────────
def init_db():
    conn = sqlite3.connect("library.db")
    c = conn.cursor()

    # Course reps table
    c.execute('''CREATE TABLE IF NOT EXISTS reps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        course TEXT
    )''')

    # Materials table
    c.execute('''CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT,
        title TEXT,
        file_id TEXT,
        file_type TEXT,
        uploaded_by TEXT
    )''')

    # Pre-load some course reps (username, password, course)
    # Password is hashed with SHA256
    default_reps = [
        ("rep_math",    hash_pw("math123"),    "Mathematics"),
        ("rep_phy",     hash_pw("phy123"),     "Physics"),
        ("rep_cs",      hash_pw("cs123"),      "Computer Science"),
        ("rep_eng",     hash_pw("eng123"),     "English"),
    ]
    for username, password, course in default_reps:
        c.execute("INSERT OR IGNORE INTO reps (username, password, course) VALUES (?, ?, ?)",
                  (username, password, course))

    conn.commit()
    conn.close()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_rep(username, password):
    conn = sqlite3.connect("library.db")
    c = conn.cursor()
    c.execute("SELECT * FROM reps WHERE username=? AND password=?", (username, hash_pw(password)))
    rep = c.fetchone()
    conn.close()
    return rep  # (id, username, password, course)

def save_material(course, title, file_id, file_type, uploaded_by):
    conn = sqlite3.connect("library.db")
    c = conn.cursor()
    c.execute("INSERT INTO materials (course, title, file_id, file_type, uploaded_by) VALUES (?, ?, ?, ?, ?)",
              (course, title, file_id, file_type, uploaded_by))
    conn.commit()
    conn.close()

def get_courses():
    conn = sqlite3.connect("library.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT course FROM materials")
    courses = [row[0] for row in c.fetchall()]
    conn.close()
    return courses

def get_materials(course):
    conn = sqlite3.connect("library.db")
    c = conn.cursor()
    c.execute("SELECT id, title, file_type, uploaded_by FROM materials WHERE course=?", (course,))
    materials = c.fetchall()
    conn.close()
    return materials

def get_file_id(material_id):
    conn = sqlite3.connect("library.db")
    c = conn.cursor()
    c.execute("SELECT file_id, file_type FROM materials WHERE id=?", (material_id,))
    result = c.fetchone()
    conn.close()
    return result

# ────────────────────────────
# STUDENT COMMANDS
# ────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Welcome to the Student Library Bot!*\n\n"
        "*For Students:*\n"
        "/browse — Browse course materials\n\n"
        "*For Course Reps:*\n"
        "/login — Login to upload materials\n"
        "/logout — Logout\n",
        parse_mode="Markdown"
    )

async def browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    courses = get_courses()
    if not courses:
        await update.message.reply_text("📭 No materials uploaded yet. Check back later!")
        return

    keyboard = [[InlineKeyboardButton(f"📖 {c}", callback_data=f"course:{c}")] for c in courses]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📚 *Select a course:*", reply_markup=reply_markup, parse_mode="Markdown")

async def course_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course = query.data.split("course:")[1]

    materials = get_materials(course)
    if not materials:
        await query.edit_message_text(f"📭 No materials for *{course}* yet.", parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton(f"{'📄' if t=='document' else '🖼'} {title}", callback_data=f"file:{mid}")]
        for mid, title, t, _ in materials
    ]
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"📖 *{course} Materials:*\nTap a file to download it.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    material_id = int(query.data.split("file:")[1])
    result = get_file_id(material_id)

    if not result:
        await query.message.reply_text("❌ File not found.")
        return

    file_id, file_type = result
    await query.message.reply_text("⏳ Sending file...")

    if file_type == "document":
        await query.message.reply_document(document=file_id)
    elif file_type == "photo":
        await query.message.reply_photo(photo=file_id)
    else:
        await query.message.reply_document(document=file_id)

async def back_to_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    courses = get_courses()
    keyboard = [[InlineKeyboardButton(f"📖 {c}", callback_data=f"course:{c}")] for c in courses]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📚 *Select a course:*", reply_markup=reply_markup, parse_mode="Markdown")

# ────────────────────────────
# COURSE REP LOGIN
# ────────────────────────────
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("logged_in"):
        await update.message.reply_text(
            f"✅ You're already logged in as *{context.user_data['username']}* ({context.user_data['course']}).",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    await update.message.reply_text("🔐 Enter your *username:*", parse_mode="Markdown")
    return LOGIN_USER

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["temp_username"] = update.message.text.strip()
    await update.message.reply_text("🔑 Enter your *password:*", parse_mode="Markdown")
    return LOGIN_PASS

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("temp_username")
    password = update.message.text.strip()
    rep = get_rep(username, password)

    if rep:
        context.user_data["logged_in"] = True
        context.user_data["username"] = rep[1]
        context.user_data["course"] = rep[3]
        await update.message.reply_text(
            f"✅ Welcome, *{rep[1]}*!\nYou manage: *{rep[3]}*\n\n"
            "Use /upload to add new materials.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Invalid credentials. Try /login again.")

    return ConversationHandler.END

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("👋 Logged out successfully.")

# ────────────────────────────
# COURSE REP UPLOAD
# ────────────────────────────
async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("logged_in"):
        await update.message.reply_text("🔒 Please /login first.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"📤 Upload for *{context.user_data['course']}*\n\nSend the *title* of this material:",
        parse_mode="Markdown"
    )
    return UPLOAD_TITLE

async def upload_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["upload_title"] = update.message.text.strip()
    await update.message.reply_text("📎 Now send the *file or image:*", parse_mode="Markdown")
    return UPLOAD_FILE

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = context.user_data.get("upload_title", "Untitled")
    course = context.user_data["course"]
    username = context.user_data["username"]

    if update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    else:
        await update.message.reply_text("❌ Please send a file or image.")
        return UPLOAD_FILE

    save_material(course, title, file_id, file_type, username)
    await update.message.reply_text(
        f"✅ *'{title}'* uploaded to *{course}*!\n\nSend /upload to add more.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ────────────────────────────
# MAIN
# ────────────────────────────
if __name__ == "__main__":
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    # Login conversation
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Upload conversation
    upload_handler = ConversationHandler(
        entry_points=[CommandHandler("upload", upload_start)],
        states={
            UPLOAD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, upload_title)],
            UPLOAD_FILE:  [MessageHandler(filters.Document.ALL | filters.PHOTO, upload_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("browse", browse))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(login_handler)
    app.add_handler(upload_handler)
    app.add_handler(CallbackQueryHandler(course_selected, pattern="^course:"))
    app.add_handler(CallbackQueryHandler(send_file, pattern="^file:"))
    app.add_handler(CallbackQueryHandler(back_to_courses, pattern="^back$"))

    print("📚 Library Bot is running...")
    app.run_polling()