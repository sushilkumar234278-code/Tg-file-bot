import asyncio
import logging
import os
import sqlite3
import re
import uuid

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

OWNER_ID = 7392809201

YOUTUBE_LINK = "https://www.youtube.com/@Hop_Less_Gamer"

CHANNEL_USERNAME = "@hopless_gamer"
CHANNEL_LINK = "https://t.me/hopless_gamer"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_DIR = os.path.join(
    BASE_DIR,
    "files"
)

DB_FILE = os.path.join(
    BASE_DIR,
    "users.db"
)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():

    c = db()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            youtube_status TEXT DEFAULT 'none',
            telegram_status TEXT DEFAULT 'none',
            banned INTEGER DEFAULT 0,
            screenshot_file_id TEXT DEFAULT '',
            screenshot_message_id INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    columns = [
        x[1]
        for x in c.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    if "screenshot_file_id" not in columns:

        c.execute("""
            ALTER TABLE users
            ADD COLUMN screenshot_file_id TEXT DEFAULT ''
        """)

    if "screenshot_message_id" not in columns:

        c.execute("""
            ALTER TABLE users
            ADD COLUMN screenshot_message_id INTEGER DEFAULT 0
        """)

    c.commit()
    c.close()
    migrate_legacy_file()


# =========================================================
# USER DATABASE FUNCTIONS
# =========================================================

def add_user(user):

    c = db()

    c.execute("""
        INSERT INTO users(
            user_id,
            first_name,
            username
        )
        VALUES (?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username
    """, (
        user.id,
        user.first_name or "",
        user.username or ""
    ))

    c.commit()
    c.close()


def get_user(user_id):

    c = db()

    row = c.execute("""
        SELECT
            user_id,
            first_name,
            username,
            youtube_status,
            telegram_status,
            banned,
            screenshot_file_id,
            screenshot_message_id
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    c.close()

    return row


def set_youtube_status(
    user_id,
    status
):

    c = db()

    c.execute("""
        UPDATE users
        SET youtube_status=?
        WHERE user_id=?
    """, (
        status,
        user_id
    ))

    c.commit()
    c.close()


def get_youtube_status(user_id):

    row = get_user(user_id)

    if not row:
        return "none"

    return row[3]


def set_telegram_status(
    user_id,
    status
):

    c = db()

    c.execute("""
        UPDATE users
        SET telegram_status=?
        WHERE user_id=?
    """, (
        status,
        user_id
    ))

    c.commit()
    c.close()


def set_banned(
    user_id,
    value
):

    c = db()

    c.execute("""
        UPDATE users
        SET banned=?
        WHERE user_id=?
    """, (
        int(value),
        user_id
    ))

    c.commit()
    c.close()


def is_banned(user_id):

    row = get_user(user_id)

    return bool(
        row and row[5]
    )


def save_screenshot(
    user_id,
    file_id,
    message_id
):

    c = db()

    c.execute("""
        UPDATE users
        SET
            screenshot_file_id=?,
            screenshot_message_id=?
        WHERE user_id=?
    """, (
        file_id,
        message_id,
        user_id
    ))

    c.commit()
    c.close()


def clear_screenshot(user_id):

    c = db()

    c.execute("""
        UPDATE users
        SET
            screenshot_file_id='',
            screenshot_message_id=0
        WHERE user_id=?
    """, (
        user_id,
    ))

    c.commit()
    c.close()


def get_all_users():

    c = db()

    rows = c.execute("""
        SELECT user_id
        FROM users
        WHERE banned=0
    """).fetchall()

    c.close()

    return [
        x[0]
        for x in rows
    ]


# =========================================================
# MULTIPLE FILE FUNCTIONS
# =========================================================

def safe_filename(name):

    name = (name or "file").strip()
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9._() -]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")

    return name or "file"


def add_file_record(name, path):

    c = db()
    cur = c.execute("""
        INSERT INTO files(name, path)
        VALUES (?, ?)
    """, (name, path))
    file_id = cur.lastrowid
    c.commit()
    c.close()
    return file_id


def get_files():

    c = db()
    rows = c.execute("""
        SELECT id, name, path, added_at
        FROM files
        ORDER BY id DESC
    """).fetchall()
    c.close()
    return rows


def get_file_record(file_id):

    c = db()
    row = c.execute("""
        SELECT id, name, path, added_at
        FROM files
        WHERE id=?
    """, (file_id,)).fetchone()
    c.close()
    return row


def rename_file_record(file_id, new_name):

    row = get_file_record(file_id)
    if not row:
        return False

    new_name = safe_filename(new_name)
    old_path = row[2]
    new_path = os.path.join(FILES_DIR, f"{file_id}_{new_name}")

    try:
        if os.path.isfile(old_path) and old_path != new_path:
            os.replace(old_path, new_path)
        elif not os.path.isfile(old_path):
            return False

        c = db()
        c.execute("UPDATE files SET name=?, path=? WHERE id=?",
                  (new_name, new_path, file_id))
        c.commit()
        c.close()
        return True
    except Exception:
        logger.exception("Could not rename file %s", file_id)
        return False


def delete_file_record(file_id):

    row = get_file_record(file_id)
    if not row:
        return False

    try:
        if os.path.isfile(row[2]):
            os.remove(row[2])

        c = db()
        c.execute("DELETE FROM files WHERE id=?", (file_id,))
        c.commit()
        c.close()
        return True
    except Exception:
        logger.exception("Could not delete file %s", file_id)
        return False


def migrate_legacy_file():
    # Compatibility for an older installation that used files/latest_file.
    legacy = os.path.join(FILES_DIR, "latest_file")
    if not os.path.isfile(legacy):
        return

    if get_files():
        return

    try:
        name = "latest_file"
        new_path = os.path.join(FILES_DIR, f"legacy_{safe_filename(name)}")
        os.replace(legacy, new_path)
        add_file_record(name, new_path)
        logger.info("Migrated legacy latest_file into multiple-file storage.")
    except Exception:
        logger.exception("Legacy file migration failed")


def file_list_text():

    rows = get_files()
    if not rows:
        return "📁 FILES\n\n❌ No files added yet."

    lines = ["📁 ALL FILES", ""]
    for file_id, name, path, added_at in rows:
        if os.path.isfile(path):
            size = os.path.getsize(path) / 1024 / 1024
            lines.append(f"{file_id}️⃣ {name} — {size:.2f} MB")
        else:
            lines.append(f"{file_id}️⃣ {name} — ❌ missing")

    return "\n".join(lines)


def file_selection_keyboard():

    rows = get_files()
    buttons = []
    for file_id, name, path, added_at in rows:
        if os.path.isfile(path):
            label = f"📄 {name}"[:60]
            buttons.append([InlineKeyboardButton(label, callback_data=f"select_file:{file_id}")])

    if not buttons:
        return None

    return InlineKeyboardMarkup(buttons)


def owner_dashboard():

    return ReplyKeyboardMarkup([
        ["📊 Statistics", "📁 Files"],
        ["👥 Users", "📢 Broadcast"],
        ["➕ Add Admin", "❌ Remove Admin"],
        ["📋 Admin List"],
    ], resize_keyboard=True)


def admin_dashboard():

    return ReplyKeyboardMarkup([
        ["📊 Statistics", "📁 Files"],
        ["👥 Users", "📢 Broadcast"],
    ], resize_keyboard=True)


def file_manager_keyboard():

    return ReplyKeyboardMarkup([
        ["➕ Add File", "📋 All Files"],
        ["✏️ Rename File", "🗑️ Delete File"],
        ["🔙 Dashboard"],
    ], resize_keyboard=True)


def close_keyboard():
    return ReplyKeyboardRemove()


# =========================================================
# ADMIN FUNCTIONS
# =========================================================

def is_owner(user_id):

    return user_id == OWNER_ID


def is_admin(user_id):

    if user_id == OWNER_ID:
        return True

    c = db()

    row = c.execute("""
        SELECT 1
        FROM admins
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    c.close()

    return row is not None


def add_admin(user_id):

    c = db()

    c.execute("""
        INSERT OR REPLACE INTO admins(
            user_id,
            added_by
        )
        VALUES (?, ?)
    """, (
        user_id,
        OWNER_ID
    ))

    c.commit()
    c.close()


def remove_admin(user_id):

    c = db()

    c.execute("""
        DELETE FROM admins
        WHERE user_id=?
    """, (
        user_id,
    ))

    c.commit()
    c.close()


def get_admins():

    c = db()

    rows = c.execute("""
        SELECT user_id
        FROM admins
        ORDER BY user_id
    """).fetchall()

    c.close()

    return [
        x[0]
        for x in rows
    ]


def get_reviewers():

    reviewers = [
        OWNER_ID
    ]

    for admin_id in get_admins():

        if admin_id != OWNER_ID:
            reviewers.append(admin_id)

    return reviewers


# =========================================================
# STATS
# =========================================================

def get_stats():

    c = db()

    total = c.execute("""
        SELECT COUNT(*)
        FROM users
    """).fetchone()[0]

    pending = c.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE youtube_status='waiting_screenshot'
    """).fetchone()[0]

    approved = c.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE youtube_status='approved'
    """).fetchone()[0]

    verified = c.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE telegram_status='verified'
    """).fetchone()[0]

    banned = c.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE banned=1
    """).fetchone()[0]

    c.close()

    return (
        total,
        pending,
        approved,
        verified,
        banned
    )


# =========================================================
# USER BUTTONS
# =========================================================

def user_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔴 Subscribe on YouTube",
                url=YOUTUBE_LINK
            )
        ],

        [
            InlineKeyboardButton(
                "📸 I Have Subscribed",
                callback_data="youtube_done"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 My Status",
                callback_data="my_status"
            )
        ]

    ])


def telegram_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📢 JOIN TELEGRAM CHANNEL",
                url=CHANNEL_LINK
            )
        ],

        [
            InlineKeyboardButton(
                "🔍 VERIFY JOIN",
                callback_data="verify_join"
            )
        ]

    ])


# =========================================================
# APPROVE / REJECT BUTTON
# =========================================================

def review_buttons(user_id):

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=f"approve:{user_id}"
            ),

            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=f"reject:{user_id}"
            )

        ]

    ])


# =========================================================
# OWNER PANEL
# =========================================================

def owner_panel():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "📊 STATS",
                callback_data="panel_stats"
            ),

            InlineKeyboardButton(
                "📁 FILE",
                callback_data="panel_file"
            )

        ],

        [

            InlineKeyboardButton(
                "👥 USERS",
                callback_data="panel_users"
            ),

            InlineKeyboardButton(
                "📢 BROADCAST",
                callback_data="panel_broadcast"
            )

        ],

        [

            InlineKeyboardButton(
                "➕ ADD ADMIN",
                callback_data="panel_add_admin"
            ),

            InlineKeyboardButton(
                "👑 ADMIN LIST",
                callback_data="panel_admins"
            )

        ],

        [

            InlineKeyboardButton(
                "❌ REMOVE ADMIN",
                callback_data="panel_remove_admin"
            )

        ]

    ])


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_panel():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "📊 STATS",
                callback_data="panel_stats"
            ),

            InlineKeyboardButton(
                "📁 FILE",
                callback_data="panel_file"
            )

        ],

        [

            InlineKeyboardButton(
                "👥 USERS",
                callback_data="panel_users"
            ),

            InlineKeyboardButton(
                "📢 BROADCAST",
                callback_data="panel_broadcast"
            )

        ]

    ])


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    add_user(user)

    if is_banned(user.id):

        await update.message.reply_text(
            "🚫 You are banned from using this bot."
        )

        return

    await update.message.reply_text(

        f"👋 Welcome {user.first_name}!\n\n"

        "🎮 Welcome to Hop_Less_Gamer!\n\n"

        "Sabse pehle YouTube channel ko subscribe karein.\n\n"

        "Subscribe ke baad "
        "📸 I Have Subscribed button dabayein.",

        reply_markup=user_menu()

    )


# =========================================================
# YOUTUBE SUBSCRIBED
# =========================================================

async def youtube_done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    await q.answer()

    user = q.from_user

    add_user(user)

    if is_banned(user.id):

        await q.answer(
            "🚫 You are banned.",
            show_alert=True
        )

        return

    set_youtube_status(
        user.id,
        "waiting_screenshot"
    )

    await q.message.reply_text(

        "📸 Ab YouTube subscription ka screenshot bhejiye.\n\n"

        "Screenshot clear hona chahiye."

    )


# =========================================================
# SCREENSHOT
# DIRECT OWNER + ADMIN
# =========================================================

async def screenshot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not update.message:
        return

    add_user(user)

    if is_banned(user.id):

        await update.message.reply_text(
            "🚫 You are banned."
        )

        return

    if get_youtube_status(user.id) != "waiting_screenshot":

        await update.message.reply_text(

            "❌ Pehle "
            "'📸 I Have Subscribed' "
            "button dabayein."

        )

        return

    # -----------------------------------------------------
    # PHOTO SCREENSHOT
    # -----------------------------------------------------

    if update.message.photo:

        photo = update.message.photo[-1]

        file_id = photo.file_id

        save_screenshot(
            user.id,
            file_id,
            update.message.message_id
        )

        caption = (

            "📸 YOUTUBE SUBSCRIPTION REVIEW\n\n"

            f"👤 Name: {user.first_name}\n"

            f"🔗 Username: "
            f"@{user.username or 'No Username'}\n"

            f"🆔 User ID: {user.id}\n\n"

            "Screenshot check karein."

        )

        sent = False

        for reviewer in get_reviewers():

            try:

                await context.bot.send_photo(

                    chat_id=reviewer,

                    photo=file_id,

                    caption=caption,

                    reply_markup=review_buttons(
                        user.id
                    )

                )

                sent = True

            except Exception:

                logger.exception(
                    "Could not send screenshot to %s",
                    reviewer
                )

        if sent:

            await update.message.reply_text(

                "✅ Screenshot received!\n\n"

                "⏳ Owner/Admin approval ka wait karein."

            )

        else:

            await update.message.reply_text(

                "❌ Screenshot Owner/Admin ko nahi bheja ja saka.\n\n"

                "Owner/Admin ko bot mein /start karna hoga."

            )

        return

    # -----------------------------------------------------
    # SCREENSHOT AS IMAGE DOCUMENT
    # -----------------------------------------------------

    if update.message.document:

        document = update.message.document

        if not document.mime_type:
            return

        if not document.mime_type.startswith("image/"):

            await update.message.reply_text(
                "❌ Sirf screenshot/photo bhejiye."
            )

            return

        file_id = document.file_id

        save_screenshot(
            user.id,
            file_id,
            update.message.message_id
        )

        caption = (

            "📸 YOUTUBE SUBSCRIPTION REVIEW\n\n"

            f"👤 Name: {user.first_name}\n"

            f"🔗 Username: "
            f"@{user.username or 'No Username'}\n"

            f"🆔 User ID: {user.id}\n\n"

            "Screenshot check karein."

        )

        sent = False

        for reviewer in get_reviewers():

            try:

                await context.bot.send_document(

                    chat_id=reviewer,

                    document=file_id,

                    caption=caption,

                    reply_markup=review_buttons(
                        user.id
                    )

                )

                sent = True

            except Exception:

                logger.exception(
                    "Could not send screenshot document to %s",
                    reviewer
                )

        if sent:

            await update.message.reply_text(

                "✅ Screenshot received!\n\n"

                "⏳ Owner/Admin approval ka wait karein."

            )

        else:

            await update.message.reply_text(

                "❌ Screenshot Owner/Admin ko nahi bheja ja saka."

            )


# =========================================================
# APPROVE / REJECT
# =========================================================

async def admin_review(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    reviewer_id = q.from_user.id

    if not is_admin(reviewer_id):

        await q.answer(
            "❌ Not authorized.",
            show_alert=True
        )

        return

    await q.answer()

    try:

        action, user_id_text = q.data.split(
            ":",
            1
        )

        user_id = int(user_id_text)

    except Exception:

        return

    row = get_user(user_id)

    if not row:

        await q.answer(
            "❌ User not found.",
            show_alert=True
        )

        return

    if is_banned(user_id):

        await q.answer(
            "❌ User is banned.",
            show_alert=True
        )

        return

    if get_youtube_status(user_id) != "waiting_screenshot":

        await q.answer(
            "Already handled.",
            show_alert=True
        )

        return

    # -----------------------------------------------------
    # APPROVE
    # -----------------------------------------------------

    if action == "approve":

        set_youtube_status(
            user_id,
            "approved"
        )

        clear_screenshot(user_id)

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "🎉 YouTube verification APPROVED!\n\n"

                    "Ab Telegram channel join karein.\n\n"

                    "Join karne ke baad "
                    "🔍 VERIFY JOIN dabayein."

                ),

                reply_markup=telegram_menu()

            )

        except Exception:

            logger.exception(
                "Could not send approval message"
            )

        try:

            old_caption = q.message.caption or ""

            await q.edit_message_caption(

                caption=(
                    old_caption
                    + "\n\n"
                    + "✅ APPROVED"
                ),

                reply_markup=None

            )

        except Exception:

            pass

    # -----------------------------------------------------
    # REJECT
    # -----------------------------------------------------

    elif action == "reject":

        set_youtube_status(
            user_id,
            "waiting_screenshot"
        )

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "❌ Screenshot reject ho gaya.\n\n"

                    "Clear YouTube subscription screenshot "
                    "dobara bhejiye."

                )

            )

        except Exception:

            logger.exception(
                "Could not send rejection message"
            )

        try:

            old_caption = q.message.caption or ""

            await q.edit_message_caption(

                caption=(
                    old_caption
                    + "\n\n"
                    + "❌ REJECTED"
                ),

                reply_markup=None

            )

        except Exception:

            pass


# =========================================================
# VERIFY TELEGRAM + SEND FILE
# =========================================================

async def verify_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    await q.answer()

    user_id = q.from_user.id

    if is_banned(user_id):

        await q.message.reply_text(
            "🚫 You are banned."
        )

        return

    if get_youtube_status(user_id) != "approved":

        await q.message.reply_text(

            "❌ Pehle YouTube verification complete karein."

        )

        return

    try:

        member = await context.bot.get_chat_member(

            CHANNEL_USERNAME,

            user_id

        )

        if member.status not in (
            "member",
            "administrator",
            "creator"
        ):

            await q.message.reply_text(

                "❌ Aapne abhi Telegram channel join nahi kiya."

            )

            return

        set_telegram_status(
            user_id,
            "verified"
        )

        files = [row for row in get_files() if os.path.isfile(row[2])]

        if not files:

            await q.message.reply_text(
                "❌ Abhi koi file available nahi hai.\n\n"
                "Owner Panel → 📁 Files → ➕ Add File"
            )
            return

        await q.message.reply_text(
            "✅ Telegram channel verified!\n\n"
            "📁 Neeche se jis file ko chahte ho select karo:",
            reply_markup=file_selection_keyboard()
        )

    except Exception:

        logger.exception(
            "Telegram verification error"
        )

        await q.message.reply_text(

            "⚠️ Verification error.\n\n"

            "Bot ko Telegram channel ka ADMIN "
            "banaya hai ya nahi check karein."

        )


# =========================================================
# FILE SELECTION FOR VERIFIED USERS
# =========================================================

async def select_file(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    if is_banned(user_id):
        await q.message.reply_text("🚫 You are banned.")
        return

    row = get_user(user_id)
    if not row or row[4] != "verified":
        await q.message.reply_text("❌ Pehle Telegram verification complete karein.")
        return

    try:
        file_id = int(q.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await q.message.reply_text("❌ Invalid file selection.")
        return

    file_row = get_file_record(file_id)
    if not file_row or not os.path.isfile(file_row[2]):
        await q.message.reply_text("❌ Ye file available nahi hai.")
        return

    try:
        with open(file_row[2], "rb") as file:
            await context.bot.send_document(
                chat_id=user_id,
                document=file,
                caption=f"📁 {file_row[1]}"
            )
        await q.message.reply_text("✅ File sent successfully.")
    except Exception as e:
        logger.exception("FILE SEND ERROR")
        await q.message.reply_text(
            "❌ File send nahi ho paayi.\n\n"
            f"Error: {type(e).__name__}"
        )


# =========================================================
# MY STATUS
# =========================================================

async def my_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    await q.answer()

    row = get_user(
        q.from_user.id
    )

    if not row:

        await q.message.reply_text(
            "ℹ️ Abhi koi status nahi hai."
        )

        return

    await q.message.reply_text(

        "📊 MY STATUS\n\n"

        f"▶️ YouTube: {row[3]}\n"

        f"📢 Telegram: {row[4]}\n"

        f"🚫 Banned: "
        f"{'Yes' if row[5] else 'No'}"

    )


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not is_admin(user_id):

        await update.message.reply_text(
            "❌ Not authorized."
        )

        return

    context.user_data.pop(
        "mode",
        None
    )

    if is_owner(user_id):

        await update.message.reply_text(

            "👑 OWNER PANEL\n\n"
            "Neeche se option select karein.",

            reply_markup=owner_dashboard()

        )

    else:

        await update.message.reply_text(

            "🛡️ ADMIN PANEL\n\n"
            "Neeche se option select karein.",

            reply_markup=admin_dashboard()

        )


# =========================================================
# PANEL BUTTONS
# =========================================================

async def panel_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kept for compatibility with older inline dashboard messages.
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("❌ Not authorized.", show_alert=True)
        return
    await q.answer()
    await q.message.reply_text(
        "ℹ️ Dashboard ab keyboard mein hai. Neeche buttons use karein.",
        reply_markup=owner_dashboard() if is_owner(uid) else admin_dashboard()
    )


# =========================================================
# ADMIN TEXT
# =========================================================

async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    if not is_admin(uid):
        return

    mode = context.user_data.get("mode")
    if not mode:
        return

    text = (update.message.text or "").strip()

    if mode == "add_admin":
        if not is_owner(uid):
            await update.message.reply_text("❌ Owner only.")
        else:
            try:
                new_id = int(text)
                if new_id == OWNER_ID:
                    await update.message.reply_text("❌ Owner already has full access.")
                else:
                    add_admin(new_id)
                    await update.message.reply_text(
                        f"✅ Admin added successfully.\n\n🆔 {new_id}",
                        reply_markup=owner_dashboard()
                    )
                    context.user_data.pop("mode", None)
                    return
            except ValueError:
                await update.message.reply_text("❌ Sirf numeric Telegram User ID bhejo.")

    elif mode == "remove_admin":
        if not is_owner(uid):
            await update.message.reply_text("❌ Owner only.")
        else:
            try:
                remove_id = int(text)
                if remove_id == OWNER_ID:
                    await update.message.reply_text("❌ Owner ko remove nahi kar sakte.")
                else:
                    remove_admin(remove_id)
                    await update.message.reply_text(
                        f"✅ Admin removed.\n\n🆔 {remove_id}",
                        reply_markup=owner_dashboard()
                    )
                    context.user_data.pop("mode", None)
                    return
            except ValueError:
                await update.message.reply_text("❌ Sirf numeric Telegram User ID bhejo.")

    elif mode == "broadcast":
        sent = 0
        failed = 0
        for target in get_all_users():
            try:
                await context.bot.send_message(chat_id=target, text=text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await update.message.reply_text(
            "📢 BROADCAST COMPLETE\n\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}",
            reply_markup=owner_dashboard() if is_owner(uid) else admin_dashboard()
        )
        context.user_data.pop("mode", None)
        return

    elif mode == "rename_file_id":
        try:
            file_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ File ID numeric hona chahiye.\nExample: 1")
            return
        if not get_file_record(file_id):
            await update.message.reply_text("❌ File ID nahi mili.")
            return
        context.user_data["rename_file_id"] = file_id
        context.user_data["mode"] = "rename_file_name"
        await update.message.reply_text("✏️ Ab new file name bhejo.\n\nCancel: /cancel")
        return

    elif mode == "rename_file_name":
        file_id = context.user_data.get("rename_file_id")
        if not file_id or not rename_file_record(file_id, text):
            await update.message.reply_text("❌ File rename nahi ho paayi.")
            context.user_data.pop("mode", None)
            context.user_data.pop("rename_file_id", None)
            return
        context.user_data.pop("mode", None)
        context.user_data.pop("rename_file_id", None)
        await update.message.reply_text(
            "✅ File renamed successfully.\n\n" + file_list_text(),
            reply_markup=file_manager_keyboard()
        )
        return

    elif mode == "upload_file":
        await update.message.reply_text(
            "📤 Abhi file upload mode active hai.\n\n"
            "Please Telegram document/file bhejo, ya /cancel dabao."
        )
        return

    elif mode == "delete_file_id":
        try:
            file_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ File ID numeric hona chahiye.\nExample: 1")
            return
        if delete_file_record(file_id):
            await update.message.reply_text(
                "🗑️ File deleted successfully.\n\n" + file_list_text(),
                reply_markup=file_manager_keyboard()
            )
            context.user_data.pop("mode", None)
        else:
            await update.message.reply_text("❌ File ID nahi mili ya file delete nahi ho paayi.")
        return

    else:
        context.user_data.pop("mode", None)




# =========================================================
# FILE UPLOAD
# =========================================================

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id

    if not is_owner(uid):
        await update.message.reply_text("❌ Sirf Owner files add kar sakta hai.")
        return

    if context.user_data.get("mode") != "upload_file":
        return

    document = update.message.document
    if not document:
        return

    os.makedirs(FILES_DIR, exist_ok=True)

    original_name = safe_filename(document.file_name or "uploaded_file")
    unique_name = f"{uuid.uuid4().hex[:12]}_{original_name}"
    final_path = os.path.join(FILES_DIR, unique_name)
    temp_path = final_path + ".uploading"

    try:
        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(temp_path)
        os.replace(temp_path, final_path)
        file_id = add_file_record(original_name, final_path)
        size = os.path.getsize(final_path)

        context.user_data.pop("mode", None)

        await update.message.reply_text(
            "✅ FILE ADDED SUCCESSFULLY!\n\n"
            f"🆔 ID: {file_id}\n"
            f"📄 {original_name}\n"
            f"📦 {size / 1024 / 1024:.2f} MB\n\n"
            "Ab verified users ko multiple files mein se select karne ka option milega.",
            reply_markup=file_manager_keyboard()
        )

    except Exception:
        logger.exception("File upload failed")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        await update.message.reply_text(
            "❌ File upload failed.\n\nConsole log check karo."
        )


# =========================================================
# ADMIN REPLY KEYBOARD
# =========================================================

async def admin_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    if not is_admin(uid):
        return

    text = (update.message.text or "").strip()
    mode = context.user_data.get("mode")

    # Do not hijack an active text-entry operation except dashboard navigation.
    if mode and text not in {"🔙 Dashboard", "📁 Files"}:
        return

    dashboard = owner_dashboard() if is_owner(uid) else admin_dashboard()

    if text == "📊 Statistics":
        total, pending, approved, verified, banned = get_stats()
        await update.message.reply_text(
            "📊 BOT STATISTICS\n\n"
            f"👥 Total Users: {total}\n"
            f"⏳ Waiting Screenshots: {pending}\n"
            f"✅ Approved: {approved}\n"
            f"🎉 Verified: {verified}\n"
            f"🚫 Banned: {banned}",
            reply_markup=dashboard
        )

    elif text == "📁 Files":
        context.user_data.pop("mode", None)
        await update.message.reply_text(
            file_list_text() + "\n\nSelect an option below:",
            reply_markup=file_manager_keyboard()
        )

    elif text == "👥 Users":
        total, pending, approved, verified, banned = get_stats()
        await update.message.reply_text(
            "👥 USER MANAGEMENT\n\n"
            f"👥 Total: {total}\n"
            f"⏳ Waiting Screenshots: {pending}\n"
            f"✅ Approved: {approved}\n"
            f"🎉 Verified: {verified}\n"
            f"🚫 Banned: {banned}\n\n"
            "Commands: /user USER_ID /ban USER_ID /unban USER_ID",
            reply_markup=dashboard
        )

    elif text == "📢 Broadcast":
        context.user_data["mode"] = "broadcast"
        await update.message.reply_text("📢 Broadcast message bhejo.\n\nCancel: /cancel")

    elif text == "➕ Add Admin":
        if not is_owner(uid):
            return
        context.user_data["mode"] = "add_admin"
        await update.message.reply_text("➕ Admin ka Telegram User ID bhejo.\n\nCancel: /cancel")

    elif text == "❌ Remove Admin":
        if not is_owner(uid):
            return
        context.user_data["mode"] = "remove_admin"
        await update.message.reply_text("❌ Admin ka Telegram User ID bhejo.\n\nCancel: /cancel")

    elif text == "📋 Admin List":
        if not is_owner(uid):
            return
        admins = get_admins()
        body = "\n".join(f"🛡️ {x}" for x in admins) if admins else "No extra admins."
        await update.message.reply_text("👑 ADMIN LIST\n\n" + body, reply_markup=dashboard)

    elif text == "➕ Add File":
        if not is_owner(uid):
            await update.message.reply_text("❌ Sirf Owner files add kar sakta hai.")
            return
        context.user_data["mode"] = "upload_file"
        await update.message.reply_text("📤 Ab file isi chat mein bhejo.\n\nMultiple files add kar sakte ho.\n\nCancel: /cancel")

    elif text == "📋 All Files":
        await update.message.reply_text(file_list_text(), reply_markup=file_manager_keyboard())

    elif text == "✏️ Rename File":
        if not is_owner(uid):
            await update.message.reply_text("❌ Sirf Owner file rename kar sakta hai.")
            return
        if not get_files():
            await update.message.reply_text("❌ Koi file nahi hai.", reply_markup=file_manager_keyboard())
            return
        context.user_data["mode"] = "rename_file_id"
        await update.message.reply_text(file_list_text() + "\n\n✏️ File ID bhejo.\n\nCancel: /cancel")

    elif text == "🗑️ Delete File":
        if not is_owner(uid):
            await update.message.reply_text("❌ Sirf Owner file delete kar sakta hai.")
            return
        if not get_files():
            await update.message.reply_text("❌ Koi file nahi hai.", reply_markup=file_manager_keyboard())
            return
        context.user_data["mode"] = "delete_file_id"
        await update.message.reply_text(file_list_text() + "\n\n🗑️ File ID bhejo.\n\nCancel: /cancel")

    elif text == "🔙 Dashboard":
        context.user_data.pop("mode", None)
        await update.message.reply_text(
            "👑 OWNER PANEL" if is_owner(uid) else "🛡️ ADMIN PANEL",
            reply_markup=dashboard
        )


# =========================================================
# CANCEL
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if is_admin(
        update.effective_user.id
    ):

        context.user_data.pop(
            "mode",
            None
        )

        await update.message.reply_text(
            "✅ Current action cancelled.",
            reply_markup=owner_dashboard() if is_owner(update.effective_user.id) else admin_dashboard()
        )


# =========================================================
# USER DETAILS
# =========================================================

async def user_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Not authorized."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /user USER_ID"
        )

        return

    try:

        uid = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    row = get_user(uid)

    if not row:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    await update.message.reply_text(

        "👤 USER DETAILS\n\n"

        f"🆔 ID: {row[0]}\n"

        f"👤 Name: {row[1]}\n"

        f"🔗 @{row[2] or 'No Username'}\n"

        f"▶️ YouTube: {row[3]}\n"

        f"📢 Telegram: {row[4]}\n"

        f"🚫 Banned: "
        f"{'Yes' if row[5] else 'No'}"

    )


# =========================================================
# BAN
# =========================================================

async def ban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Not authorized."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /ban USER_ID"
        )

        return

    try:

        uid = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    if uid == OWNER_ID:

        await update.message.reply_text(
            "❌ Owner ko ban nahi kar sakte."
        )

        return

    if not get_user(uid):

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    set_banned(
        uid,
        True
    )

    await update.message.reply_text(

        f"🚫 User {uid} banned."

    )


# =========================================================
# UNBAN
# =========================================================

async def unban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Not authorized."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /unban USER_ID"
        )

        return

    try:

        uid = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    if not get_user(uid):

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    set_banned(
        uid,
        False
    )

    await update.message.reply_text(

        f"✅ User {uid} unbanned."

    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Unhandled error: %s",
        context.error,
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    os.makedirs(
        FILES_DIR,
        exist_ok=True
    )
    migrate_legacy_file()

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN / TELEGRAM_BOT_TOKEN environment variable is missing.")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # =====================================================
    # COMMANDS
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "user",
            user_command
        )
    )

    app.add_handler(
        CommandHandler(
            "ban",
            ban_command
        )
    )

    app.add_handler(
        CommandHandler(
            "unban",
            unban_command
        )
    )

    app.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    # =====================================================
    # USER CALLBACKS
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            youtube_done,
            pattern=r"^youtube_done$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            my_status,
            pattern=r"^my_status$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            verify_join,
            pattern=r"^verify_join$"
        )
    )

    # =====================================================
    # APPROVE / REJECT
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            admin_review,
            pattern=r"^(approve|reject):"
        )
    )

    # =====================================================
    # OWNER / ADMIN PANEL
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            select_file,
            pattern=r"^select_file:"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            panel_buttons,
            pattern=r"^(panel_|file_)"
        )
    )

    # =====================================================
    # FILE UPLOAD
    #
    # IMPORTANT:
    # Image documents are NOT caught here.
    # They go to screenshot() below.
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.Document.ALL
            & ~filters.Document.IMAGE,
            upload_file
        )
    )

    # =====================================================
    # SCREENSHOT
    #
    # Normal Telegram photo
    # OR image sent as document
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.Document.IMAGE,
            screenshot
        )
    )

    # =====================================================
    # ADMIN REPLY KEYBOARD
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_keyboard
        )
    )

    # =====================================================
    # ADMIN TEXT INPUT
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text
        )
    )

    # =====================================================
    # ERROR
    # =====================================================

    app.add_error_handler(
        error_handler
    )

    # =====================================================
    # START
    # =====================================================

    print(
        "================================"
    )

    print(
        "🤖 BOT STARTED"
    )

    print(
        "👑 Owner Panel: ON"
    )

    print(
        "🛡️ Admin System: ON"
    )

    print(
        "📸 Direct Screenshot Review: ON"
    )

    print(
        "✅ Approve / Reject: ON"
    )

    print(
        "📁 Multiple File Management: ON"
    )

    print(
        "📢 Broadcast: ON"
    )

    print(
        "================================"
    )

    app.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
