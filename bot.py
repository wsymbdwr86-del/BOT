import os
import sqlite3
import random
import time
import threading
from datetime import date, datetime, timedelta
import telebot
from telebot import types
from flask import Flask
import re

# ==================================================
# إعدادات البوت والقنوات الأساسية
# ==================================================
TOKEN = "9084104214:AAHksEyIugwQyL7qXNmoOZstQ-UETf6sRZc"
OWNER_ID = 7110803688

WITHDRAW_CHANNEL = "@dhhdhdhshhshc"
BALANCE_CHANNEL = "@dhbsbsbsjsjj"
SUPPORT_CHANNEL = "@dbshhshshzj"

bot = telebot.TeleBot(TOKEN, threaded=False)

db = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = db.cursor()

# ==================================================
# إعداد سيرفر الويب المجاني لـ Render (لبقاء البوت شغال 24/7)
# ==================================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7 successfully!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# ==================================================
# متغيرات الصيانة والدول المسموحة
# ==================================================
bot_maintenance = False  # False = البوت شغال، True = متوقف للصيانة

ALLOWED_COUNTRY_CODES = {
    "963": "سوري 🇸🇾",
    "961": "لبناني 🇱🇧"
}

def check_maintenance(message):
    if bot_maintenance and not is_admin(message.from_user.id):
        bot.reply_to(message, "🛠️ **البوت متوقف حالياً للصيانة العامة.**\nيرجى العودة لاحقاً.", parse_mode="Markdown")
        return True
    return False

# ==================================================
# إعداد الجداول في قاعدة البيانات
# ==================================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    spins INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0,
    invited_by INTEGER,
    phone_type TEXT DEFAULT 'غير محدد'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'moderator'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS gifts (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    max_uses INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS gift_usages (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY (user_id, code)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS withdraw_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_name TEXT UNIQUE
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS wheel_prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize_name TEXT,
    probability REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS wheel_cooldowns (
    user_id INTEGER PRIMARY KEY,
    last_spin TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_withdraw_counts (
    user_id INTEGER,
    withdraw_date TEXT,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, withdraw_date)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    name TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_claims (
    user_id INTEGER PRIMARY KEY,
    claim_date TEXT
)
""")

cursor.execute("INSERT OR IGNORE INTO admins (user_id, role) VALUES (?, ?)", (OWNER_ID, "owner"))
cursor.execute("INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)", ("ref_reward", "10"))
cursor.execute("INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)", ("min_withdraw", "100"))
cursor.execute("INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)", ("daily_withdraw_limit", "17"))
db.commit()

states = {}
temp_withdraw_data = {}
temp_gift_data = {}

# ==================================================
# تسجيل الأوامر في قائمة البوت
# ==================================================
try:
    bot.set_my_commands([
        types.BotCommand("start", "تشغيل البوت والقائمة الرئيسية 🏠"),
        types.BotCommand("admin", "لوحة التحكم والإدارة 👨‍💻")
    ])
except Exception as e:
    print(f"Could not set commands: {e}")

# ==================================================
# نظام التقارير اليومية التلقائي
# ==================================================
def daily_balance_reporter():
    last_sent_date = ""
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            today_str = now.date().isoformat()
            if last_sent_date != today_str:
                try:
                    cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
                    res = cursor.fetchone()
                    total_users = res[0]
                    total_balances = res[1]

                    report_text = (
                        f"📊 **التقرير اليومي لأرصدة المستخدمين (الساعة 12 ليلاً):**\n\n"
                        f"📅 التاريخ: `{today_str}`\n"
                        f"👥 إجمالي عدد المستخدمين: **{total_users}**\n"
                        f"💰 إجمالي الأرصدة في البوت: **{total_balances}** نقطة"
                    )
                    bot.send_message(BALANCE_CHANNEL, report_text, parse_mode="Markdown")
                    last_sent_date = today_str
                except Exception as e:
                    print(f"Error sending daily report: {e}")
        time.sleep(30)

threading.Thread(target=daily_balance_reporter, daemon=True).start()

# ==================================================
# وظائف مساعدة وتحليل الأرقام
# ==================================================
def detect_phone_type(text):
    clean = text.replace("+", "").strip()
    if clean.startswith("963") or clean.startswith("09"):
        return "سوري 🇸🇾"
    elif clean.startswith("961") or clean.startswith("03") or clean.startswith("70") or clean.startswith("71") or clean.startswith("76") or clean.startswith("78") or clean.startswith("81"):
        return "لبناني 🇱🇧"
    return "أخرى / دولي"

def is_admin(user_id):
    cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None

def is_owner(user_id):
    return user_id == OWNER_ID

def get_setting(name):
    cursor.execute("SELECT value FROM settings WHERE name=?", (name,))
    row = cursor.fetchone()
    return row[0] if row else "0"

def save_setting(name, value):
    cursor.execute("INSERT OR REPLACE INTO settings (name, value) VALUES (?, ?)", (name, str(value)))
    db.commit()

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

def check_ban_message(message):
    user = get_user(message.from_user.id)
    if user and user[5] == 1:
        bot.reply_to(message, "🚫 حسابك محظور حالياً.")
        return True
    return False

def check_ban_callback(call):
    user = get_user(call.from_user.id)
    if user and user[5] == 1:
        bot.answer_callback_query(call.id, "🚫 حسابك محظور حالياً.", show_alert=True)
        return True
    return False

# ==================================================
# القوائم والواجهات
# ==================================================
def main_menu_markup():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎡 عجلة الحظ", callback_data="btn_wheel_play"),
        types.InlineKeyboardButton("💰 رصيدي", callback_data="btn_balance")
    )
    kb.add(
        types.InlineKeyboardButton("👥 رابط الإحالة", callback_data="btn_ref"),
        types.InlineKeyboardButton("💸 سحب الرصيد", callback_data="btn_withdraw")
    )
    kb.add(
        types.InlineKeyboardButton("🎁 أكواد الهدايا", callback_data="btn_gift"),
        types.InlineKeyboardButton("🎯 المكافأة اليومية", callback_data="btn_daily")
    )
    kb.add(
        types.InlineKeyboardButton("ℹ️ معلوماتي", callback_data="btn_my_info"),
        types.InlineKeyboardButton("🏆 المتصدرين", callback_data="btn_leaderboard")
    )
    kb.add(
        types.InlineKeyboardButton("📞 تواصل مع الدعم الفني", callback_data="btn_support")
    )
    return kb

def admin_menu_markup():
    kb = types.InlineKeyboardMarkup(row_width=2)
    m_status = "🟢 تشغيل البوت" if bot_maintenance else "🔴 إيقاف البوت (صيانة)"
    kb.add(
        types.InlineKeyboardButton(m_status, callback_data="adm_toggle_maintenance"),
        types.InlineKeyboardButton("📊 إحصائيات وانواع الأرقام", callback_data="adm_stats")
    )
    kb.add(
        types.InlineKeyboardButton("🎡 إدارة عجلة الحظ", callback_data="adm_wheel_settings"),
        types.InlineKeyboardButton("🎁 مكافأة الإحالات", callback_data="adm_ref_reward")
    )
    kb.add(
        types.InlineKeyboardButton("📥 مراجعة طلبات السحب", callback_data="adm_withdraw_req"),
        types.InlineKeyboardButton("⚖️ الحد الأدنى للسحب", callback_data="adm_withdraw_limits")
    )
    kb.add(
        types.InlineKeyboardButton("📅 سقف السحب اليومي", callback_data="adm_daily_limit"),
        types.InlineKeyboardButton("📋 إدارة أكواد الهدايا", callback_data="adm_manage_gifts")
    )
    kb.add(
        types.InlineKeyboardButton("🎟️ إنشاء كود هدية", callback_data="adm_create_gift"),
        types.InlineKeyboardButton("♻️ تصفير جميع الأرصدة", callback_data="adm_reset_all")
    )
    kb.add(types.InlineKeyboardButton("🎁 الهدية اليومية", callback_data="adm_daily_gift_val"))
    kb.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="adm_main_menu"))
    return kb

def wheel_menu_markup():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("➕ إضافة جائزة للعجلة", callback_data="wh_add_prize"),
        types.InlineKeyboardButton("🎁 عرض قائمة الجوائز", callback_data="wh_list_prizes"),
        types.InlineKeyboardButton("↩️ العودة لوحة الإدارة", callback_data="adm_panel")
    )
    return kb

# ==================================================
# بدء التشغيل والتحقق الإجباري من رقم الهاتف عبر /start
# ==================================================
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    if check_maintenance(message):
        return
    if check_ban_message(message):
        return

    cursor.execute("SELECT phone_type FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()

    inviter = None
    parts = (message.text or "").split()
    if len(parts) > 1:
        try:
            inviter = int(parts[1])
        except ValueError:
            inviter = None

    if not row or not row[0] or row[0] == "غير محدد":
        states[uid] = f"waiting_phone_{inviter if inviter else 0}"
        
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add(types.KeyboardButton("📱 اضغط هنا لمشاركة رقم هاتفك والتحقق", request_contact=True))
        
        bot.send_message(
            uid,
            "⚠️ **مرحباً بك! يتطلب استخدام البوت التحقق من رقم هاتفك أولاً.**\n\nالرجاء الضغط على الزر بالأسفل لمشاركة رقم هاتفك والتحقق من دولتك: 👇",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    bot.send_message(uid, "🎉 **أهلاً بك مرة أخرى في البوت التفاعلي!**\n\nاختر الخدمة المطلوبة من القائمة أدناه 👇", parse_mode="Markdown", reply_markup=main_menu_markup())

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ هذه اللوحة للمشرفين فقط.")
        return
    bot.send_message(message.chat.id, "👨‍💻 **لوحة التحكم والإدارة**", parse_mode="Markdown", reply_markup=admin_menu_markup())

# ==================================================
# استقبال جهة الاتصال (رقم الهاتف) للتحقق الإجباري
# ==================================================
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    if not message.contact or message.contact.user_id != uid:
        bot.reply_to(message, "❌ يرجى مشاركة رقم هاتفك الصحيح باستخدام الزر المخصص.")
        return

    phone_number = str(message.contact.phone_number).replace("+", "").strip()
    p_type = "أخرى / دولي"
    for code, name in ALLOWED_COUNTRY_CODES.items():
        if phone_number.startswith(code):
            p_type = name
            break

    state = states.get(uid, "")
    inviter = None
    if state.startswith("waiting_phone_"):
        try:
            inviter = int(state.replace("waiting_phone_", ""))
            if inviter == 0:
                inviter = None
        except:
            inviter = None

    username = message.from_user.username or ""
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, balance, referrals, spins, banned, invited_by, phone_type)
        VALUES (?, ?, 
            COALESCE((SELECT balance FROM users WHERE user_id = ?), 0),
            COALESCE((SELECT referrals FROM users WHERE user_id = ?), 0),
            COALESCE((SELECT spins FROM users WHERE user_id = ?), 0),
            COALESCE((SELECT banned FROM users WHERE user_id = ?), 0),
            ?, ?
        )
    """, (uid, username, uid, uid, uid, uid, inviter, p_type))

    if inviter and inviter != uid:
        cursor.execute("SELECT invited_by FROM users WHERE user_id=?", (uid,))
        res = cursor.fetchone()
        if not res or not res[0]:
            reward = int(get_setting("ref_reward") or 10)
            cursor.execute("UPDATE users SET referrals=referrals+1, balance=balance+? WHERE user_id=?", (reward, inviter))

    db.commit()
    states.pop(uid, None)

    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(
        uid,
        f"✅ **تم التحقق من رقمك بنجاح!**\n📱 تصنيف رقمك: **{p_type}**\n\nأهلاً بك في البوت، يمكنك البدء الآن 👇",
        parse_mode="Markdown",
        reply_markup=remove_kb
    )
    bot.send_message(uid, "القائمة الرئيسية:", reply_markup=main_menu_markup())

# ==================================================
# معالجة الضغطات (Callback Queries)
# ==================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    if check_ban_callback(call):
        return

    data = call.data

    if data == "adm_toggle_maintenance":
        global bot_maintenance
        if not is_owner(uid) and not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ للمشرفين فقط", show_alert=True)
            return
        bot_maintenance = not bot_maintenance
        status_text = "متوقف للصيانة 🔴" if bot_maintenance else "يعمل بشكل طبيعي 🟢"
        bot.answer_callback_query(call.id, f"تم تغيير حالة البوت إلى: {status_text}", show_alert=True)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=admin_menu_markup())
        except:
            pass
        return

    # إعدادات عجلة الحظ في لوحة الإدارة
    if data == "adm_wheel_settings":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ للمشرفين فقط", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "🎡 **إدارة عجلة الحظ:**\nاختر الإجراء المطلوب من القناة أدناه:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=wheel_menu_markup()
        )
        return

    if data == "wh_add_prize":
        if not is_admin(uid):
            return
        states[uid] = "admin_wheel_prize"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "➕ أرسل اسم الجائزة والاحتمال (مثال: `50نقطة 1.5`):", parse_mode="Markdown")
        return

    if data == "wh_list_prizes":
        if not is_admin(uid):
            return
        cursor.execute("SELECT prize_name, probability FROM wheel_prizes")
        rows = cursor.fetchall()
        res = "🎁 **الجوائز النشطة في عجلة الحظ:**\n\n"
        for r in rows:
            res += f"🏆 {r[0]} — الاحتمال: {r[1]}%\n"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, res if rows else "📭 لا توجد جوائز مضافة حتى الآن.", parse_mode="Markdown")
        return

    if data.startswith("reply_user_"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ للمشرفين فقط", show_alert=True)
            return
        target_id = data.replace("reply_user_", "")
        states[uid] = f"admin_reply_to_{target_id}"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"✍️ أرسل الرد للمستخدم (ID: `{target_id}`):", parse_mode="Markdown")
        return

    if data.startswith("approve_wd_"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ للمشرفين فقط", show_alert=True)
            return
        target_uid = data.replace("approve_wd_", "")
        try:
            bot.edit_message_text(
                call.message.text + "\n\n✅ **حالة الطلب: تم القبول بنجاح ✔️**",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown"
            )
            bot.send_message(int(target_uid), "🎉 **تم قبول طلب السحب الخاص بك وتمت معالجته بنجاح!**", parse_mode="Markdown")
            bot.answer_callback_query(call.id, "✅ تم قبول الطلب وإشعار المستخدم.")
        except Exception as e:
            bot.answer_callback_query(call.id, f"خطأ: {e}", show_alert=True)
        return

    if data.startswith("reject_wd_"):
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "⛔ للمشرفين فقط", show_alert=True)
            return
        parts = data.replace("reject_wd_", "").split("_")
        target_uid = parts[0]
        amount = int(parts[1]) if len(parts) > 1 else 0
        try:
            if amount > 0:
                cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, int(target_uid)))
                db.commit()
            bot.edit_message_text(
                call.message.text + "\n\n❌ **حالة الطلب: تم الرفض وإعادة الرصيد 🔄**",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown"
            )
            bot.send_message(int(target_uid), f"❌ **عذراً، تم رفض طلب السحب وتمت إعادة {amount} نقطة إلى رصيدك.**", parse_mode="Markdown")
            bot.answer_callback_query(call.id, "❌ تم رفض الطلب وإعادة الرصيد.")
        except Exception as e:
            bot.answer_callback_query(call.id, f"خطأ: {e}", show_alert=True)
        return

    if data == "btn_wheel_play":
        cursor.execute("SELECT last_spin FROM wheel_cooldowns WHERE user_id=?", (uid,))
        row = cursor.fetchone()
        
        if row:
            last_time = datetime.fromisoformat(row[0])
            if datetime.now() - last_time < timedelta(hours=24):
                remaining = timedelta(hours=24) - (datetime.now() - last_time)
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                bot.answer_callback_query(call.id, f"⏳ لقد لعبت عجلة الحظ مؤخراً! يرجى الانتظار {hours} ساعة و {minutes} دقيقة.", show_alert=True)
                return

        cursor.execute("SELECT id, prize_name FROM wheel_prizes")
        prizes = cursor.fetchall()
        if not prizes:
            bot.answer_callback_query(call.id, "⚠️ عذراً، لم يقم المشرف بإضافة جوائز لعجلة الحظ بعد!", show_alert=True)
            return

        won_prize = random.choice(prizes)
        prize_text = won_prize[1]

        numbers = re.findall(r'\d+', prize_text)
        points_won = int(numbers[0]) if numbers else 10

        cursor.execute("UPDATE users SET balance=balance+?, spins=spins+1 WHERE user_id=?", (points_won, uid))
        cursor.execute("INSERT OR REPLACE INTO wheel_cooldowns (user_id, last_spin) VALUES (?, ?)", (uid, datetime.now().isoformat()))
        db.commit()

        try:
            bot.send_message(
                BALANCE_CHANNEL,
                f"🎡 **جائزة جديدة من عجلة الحظ:**\n\n"
                f"👤 المستخدم: @{call.from_user.username if call.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
                f"🎁 الربح: **{prize_text}** (أضيفت لرصيد البوت)",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending wheel prize notice: {e}")

        bot.answer_callback_query(call.id, f"🎁 مبروك! ربحت: {prize_text}", show_alert=True)
        bot.send_message(
            call.message.chat.id,
            f"🎡 **نتيجة تدوير عجلة الحظ:**\n\n"
            f"🎉 مبروك يا مبدع! ربحت معنا: **{prize_text}**\n"
            f"💰 تمت إضافة الجائزة مباشرة إلى رصيدك العام في البوت بنجاح!",
            parse_mode="Markdown"
        )
        return

    if data == "btn_ref":
        me = bot.get_me()
        link = f"https://t.me/{me.username}?start={uid}"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"🔗 **رابط الإحالة الخاص بك:**\n\n`{link}`", parse_mode="Markdown")

    elif data == "btn_balance":
        user = get_user(uid)
        if not user:
            bot.answer_callback_query(call.id, "⚠️ يرجى إرسال /start أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"💰 رصيدك الحالي: **{user[2]}** نقطة", parse_mode="Markdown")

    elif data == "btn_withdraw":
        user = get_user(uid)
        min_w = int(get_setting("min_withdraw") or 100)
        if user[2] < min_w:
            bot.answer_callback_query(call.id, f"❌ رصيدك غير كافٍ. الحد الأدنى للسحب هو {min_w} نقطة.", show_alert=True)
            return
        
        today_str = date.today().isoformat()
        cursor.execute("SELECT count FROM daily_withdraw_counts WHERE user_id=? AND withdraw_date=?", (uid, today_str))
        row = cursor.fetchone()
        current_count = row[0] if row else 0
        daily_limit = int(get_setting("daily_withdraw_limit") or 17)

        if current_count >= daily_limit:
            bot.answer_callback_query(call.id, f"⚠️ وصلت لسقف السحب اليومي ({daily_limit} عمليات).", show_alert=True)
            return

        methods = [("شام كاش (ShamCash)",), ("سيريتل كاش",)]
        cursor.execute("SELECT method_name FROM withdraw_methods")
        db_methods = cursor.fetchall()
        if db_methods:
            methods = db_methods

        kb = types.InlineKeyboardMarkup(row_width=1)
        for m in methods:
            kb.add(types.InlineKeyboardButton(f"💳 {m[0]}", callback_data=f"withdraw_meth_{m[0]}"))
        
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💸 **اختر طريقة السحب المناسبة:**", parse_mode="Markdown", reply_markup=kb)

    elif data.startswith("withdraw_meth_"):
        meth_name = data.replace("withdraw_meth_", "")
        states[uid] = f"withdraw_amount_{meth_name}"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"📝 الطريقة المحددة: **{meth_name}**\n\nأرسل الآن **المبلغ المراد سحبه** (أرقام فقط):", parse_mode="Markdown")

    elif data == "btn_gift":
        states[uid] = "user_gift"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🎁 أرسل كود الهدية الآن:")

    elif data == "btn_daily":
        today = date.today().isoformat()
        cursor.execute("SELECT claim_date FROM daily_claims WHERE user_id=?", (uid,))
        row = cursor.fetchone()
        if row and row[0] == today:
            bot.answer_callback_query(call.id, "⏳ استلمت مكافأتك اليومية مسبقاً!", show_alert=True)
            return

        daily_points = int(get_setting("daily_gift_val") or 5)
        cursor.execute("INSERT OR REPLACE INTO daily_claims (user_id, claim_date) VALUES (?, ?)", (uid, today))
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (daily_points, uid))
        db.commit()

        try:
            bot.send_message(
                BALANCE_CHANNEL,
                f"🎯 **استلام مكافأة يومية جديدة:**\n\n"
                f"👤 المستخدم: @{call.from_user.username if call.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
                f"🎁 القيمة: **{daily_points} نقطة**",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending daily reward notice: {e}")

        bot.answer_callback_query(call.id, f"🎉 مبروك، حصلت على {daily_points} نقاط!", show_alert=True)

    elif data == "btn_my_info":
        user = get_user(uid)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"ℹ️ **معلومات حسابك:**\n\n🆔 المعرف: `{uid}`\n👤 اليوزر: @{user[1] if user[1] else 'لا يوجد'}\n💰 الرصيد العام: {user[2]} نقطة\n👥 الإحالات: {user[3]}\n📱 نوع الرقم: {user[7]}", parse_mode="Markdown")

    elif data == "btn_leaderboard":
        cursor.execute("SELECT username, user_id, referrals FROM users ORDER BY referrals DESC LIMIT 5")
        top_users = cursor.fetchall()
        text = "🏆 **قائمة المتصدرين (أعلى الإحالات):**\n\n"
        for i, u in enumerate(top_users, 1):
            name = f"@{u[0]}" if u[0] else f"ID: {u[1]}"
            text += f"{i}. {name} ⟵ **{u[2]}** إحالة\n"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

    elif data == "btn_support":
        states[uid] = "user_support"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📞 أرسل رسالتك لفريق الدعم الفني:")

    # لوحة الإدارة
    elif data == "adm_main_menu":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🏠 القائمة الرئيسية:", reply_markup=main_menu_markup())

    elif data == "adm_panel":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "👨‍💻 لوحة الإدارة:", reply_markup=admin_menu_markup())

    elif data == "adm_stats":
        if not is_admin(uid):
            return
        cursor.execute("SELECT COUNT(*) FROM users")
        u_count = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
        p_total = cursor.fetchone()[0]
        
        cursor.execute("SELECT phone_type, COUNT(*) FROM users GROUP BY phone_type")
        types_counts = cursor.fetchall()
        phone_stats_str = ""
        for p_t, p_c in types_counts:
            phone_stats_str += f"- {p_t}: **{p_c}** مستخدم\n"

        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            f"📊 **إحصائيات البوت وانواع الأرقام:**\n\n"
            f"👥 إجمالي الانضمامات: **{u_count}** مستخدم\n"
            f"💰 إجمالي الأرصدة الكلية: **{p_total}** نقطة\n\n"
            f"📱 **تصنيف أنواع الأرقام المكتشفة:**\n{phone_stats_str if phone_stats_str else 'لم يتم تسجيل أرقام هاتف بعد'}",
            parse_mode="Markdown"
        )

    elif data == "adm_ref_reward":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "⛔ للمدير الأساسي فقط", show_alert=True)
            return
        states[uid] = "admin_ref"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"🎁 مكافأة الإحالات الحالية: {get_setting('ref_reward')}\nأرسل القيمة الجديدة:")

    elif data == "adm_withdraw_req":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"📥 طلبات السحب تصل مباشرة لقناة: {WITHDRAW_CHANNEL}")

    elif data == "adm_withdraw_limits":
        if not is_admin(uid):
            return
        states[uid] = "admin_set_min_w"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"⚖️ الحد الأدنى الحالي: {get_setting('min_withdraw')}\nأرسل القيمة الجديدة:")

    elif data == "adm_daily_limit":
        if not is_admin(uid):
            return
        states[uid] = "admin_set_daily_limit"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"📅 سقف السحب اليومي الحالي: {get_setting('daily_withdraw_limit')}\nأرسل العدد الجديد:")

    elif data == "adm_manage_gifts":
        if not is_admin(uid):
            return
        cursor.execute("SELECT code, amount, max_uses, used_count FROM gifts WHERE used_count < max_uses")
        rows = cursor.fetchall()
        res = "📋 الأكواد النشطة:\n\n"
        for r in rows:
            res += f"🔑 `{r[0]}` ⟵ القيمة: {r[1]} | الاستخدامات: {r[3]}/{r[2]}\n"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, res if rows else "📭 لا توجد أكواد نشطة.", parse_mode="Markdown")

    elif data == "adm_create_gift":
        if not is_admin(uid):
            return
        states[uid] = "admin_gift_name"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🎟️ **خطوة 1/3:** أرسل الآن **اسم الكود** (مثلاً: `WELCOME`):", parse_mode="Markdown")

    elif data == "adm_reset_all":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "⛔ للمدير الأساسي فقط", show_alert=True)
            return
        cursor.execute("UPDATE users SET balance=0")
        db.commit()
        bot.answer_callback_query(call.id, "♻️ تم تصفير جميع الأرصدة!", show_alert=True)

    elif data == "adm_daily_gift_val":
        if not is_admin(uid):
            return
        states[uid] = "admin_daily_val"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🎁 أرسل القيمة الجديدة للهدية اليومية:")

# ==================================================
# استقبال النصوص والحالات
# ==================================================
@bot.message_handler(content_types=["text"], func=lambda m: not (m.text or "").startswith("/"))
def handle_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    if text == "إلغاء":
        states.pop(uid, None)
        temp_withdraw_data.pop(uid, None)
        temp_gift_data.pop(uid, None)
        bot.reply_to(message, "تم إلغاء العملية.")
        return

    if check_ban_message(message):
        return

    state = states.get(uid)

    if state == "admin_wheel_prize":
        try:
            p_name, p_prob = text.split()
            cursor.execute("INSERT INTO wheel_prizes (prize_name, probability) VALUES (?, ?)", (p_name, float(p_prob)))
            db.commit()
            states.pop(uid, None)
            bot.reply_to(message, f"🎁 تمت إضافة الجائزة ({p_name}) إلى عجلة الحظ بنجاح!")
        except Exception as e:
            bot.reply_to(message, f"❌ صيغة خاطئة. مثال صحيح: `50نقطة 1.5`\nالخطأ: {e}", parse_mode="Markdown")
        return

    if state and state.startswith("admin_reply_to_"):
        target_id = int(state.replace("admin_reply_to_", ""))
        try:
            bot.send_message(target_id, f"💬 **رد من الدعم الفني:**\n\n{text}")
            states.pop(uid, None)
            bot.reply_to(message, "✅ تم إرسال الرد إلى المستخدم بنجاح!")
        except Exception as e:
            bot.reply_to(message, f"❌ خطأ أثناء إرسال الرد: {e}")
        return

    if state == "admin_gift_name":
        temp_gift_data[uid] = {"code": text.upper()}
        states[uid] = "admin_gift_amount"
        bot.reply_to(message, f"✅ اسم الكود: `{text.upper()}`\n\n📝 **خطوة 2/3:** أرسل الآن **قيمة الكود بالنقاط** (أرقام فقط):", parse_mode="Markdown")
        return

    if state == "admin_gift_amount":
        try:
            amount = int(text)
            temp_gift_data[uid]["amount"] = amount
            states[uid] = "admin_gift_uses"
            bot.reply_to(message, f"✅ القيمة: {amount} نقطة.\n\n👥 **خطوة 3/3:** أرسل الآن **عدد المستخدمين** المسموح لهم باستخدام الكود (أرقام فقط):")
        except ValueError:
            bot.reply_to(message, "❌ يرجى إرسال أرقام صحيحة فقط لقيمة الكود:")
        return

    if state == "admin_gift_uses":
        try:
            max_uses = int(text)
            gift_info = temp_gift_data.get(uid)
            if not gift_info:
                states.pop(uid, None)
                bot.reply_to(message, "❌ حدث خطأ، يرجى إعادة محاولة إنشاء الكود.")
                return
            
            code = gift_info["code"]
            amount = gift_info["amount"]

            cursor.execute("INSERT OR REPLACE INTO gifts (code, amount, max_uses, used_count) VALUES (?, ?, ?, 0)", (code, amount, max_uses))
            db.commit()

            states.pop(uid, None)
            temp_gift_data.pop(uid, None)
            bot.reply_to(message, f"🎉 **تم إنشاء كود الهدية بنجاح!**\n\n🔑 الكود: `{code}`\n💰 القيمة: {amount} نقطة\n👥 مخصص لـ: {max_uses} مستخدمين", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "❌ يرجى إرسال رقم صحيح لعدد المستخدمين:")
        return

    if state and state.startswith("withdraw_amount_"):
        meth = state.replace("withdraw_amount_", "")
        user = get_user(uid)
        try:
            amount = int(text)
            min_w = int(get_setting("min_withdraw") or 100)
            if amount < min_w:
                bot.reply_to(message, f"❌ أقل مبلغ للسحب هو {min_w} نقطة:")
                return
            if user[2] < amount:
                bot.reply_to(message, "❌ رصيدك لا يكفي:")
                return
            
            temp_withdraw_data[uid] = {"method": meth, "amount": amount}
            states[uid] = f"withdraw_address_{meth}"
            bot.reply_to(message, f"✅ المبلغ المطلوب: {amount} نقطة.\n\n📝 الآن أرسل **رقم الحساب أو عنوان المحفظة**:", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "❌ أرسل أرقاماً صحيحة فقط:")
        return

    if state and state.startswith("withdraw_address_"):
        data = temp_withdraw_data.get(uid)
        if not data:
            states.pop(uid, None)
            bot.reply_to(message, "حدث خطأ، حاول مجدداً.")
            return
        
        meth = data["method"]
        amount = data["amount"]
        address = text

        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
        
        today_str = date.today().isoformat()
        cursor.execute("""
            INSERT INTO daily_withdraw_counts (user_id, withdraw_date, count) 
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, withdraw_date) 
            DO UPDATE SET count = count + 1
        """, (uid, today_str))
        db.commit()

        kb_wd = types.InlineKeyboardMarkup(row_width=2)
        kb_wd.add(
            types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_wd_{uid}"),
            types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_wd_{uid}_{amount}")
        )

        cursor.execute("SELECT phone_type FROM users WHERE user_id=?", (uid,))
        p_row = cursor.fetchone()
        p_type = p_row[0] if p_row else "غير محدد"

        bot.send_message(
            WITHDRAW_CHANNEL,
            f"📥 **طلب سحب جديد:**\n\n"
            f"👤 المستخدم: @{message.from_user.username if message.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
            f"📱 نوع الرقم: **{p_type}**\n"
            f"💳 الطريقة: **{meth}**\n"
            f"💰 المبلغ: {amount} نقطة\n"
            f"📍 الحساب: `{address}`",
            parse_mode="Markdown",
            reply_markup=kb_wd
        )

        states.pop(uid, None)
        temp_withdraw_data.pop(uid, None)
        bot.reply_to(message, "✅ تم إرسال طلب السحب بنجاح للإدارة!")
        return

    if state == "admin_set_min_w":
        try:
            val = int(text)
            save_setting("min_withdraw", str(val))
            states.pop(uid, None)
            bot.reply_to(message, f"✅ تم تحديث الحد الأدنى إلى: {val}")
        except:
            bot.reply_to(message, "❌ أرسل رقماً صحيحاً.")
        return

    if state == "admin_set_daily_limit":
        try:
            val = int(text)
            save_setting("daily_withdraw_limit", str(val))
            states.pop(uid, None)
            bot.reply_to(message, f"✅ تم تحديث سقف السحب اليومي إلى: {val}")
        except:
            bot.reply_to(message, "❌ أرسل رقماً صحيحاً.")
        return

    if state == "user_support":
        kb_sup = types.InlineKeyboardMarkup()
        kb_sup.add(types.InlineKeyboardButton("💬 رد على المستخدم", callback_data=f"reply_user_{uid}"))

        bot.send_message(
            SUPPORT_CHANNEL,
            f"📞 **رسالة دعم جديدة:**\n\n"
            f"👤 المرسل: @{message.from_user.username if message.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
            f"💬 الرسالة: {text}",
            parse_mode="Markdown",
            reply_markup=kb_sup
        )
        states.pop(uid, None)
        bot.reply_to(message, "✅ تم إرسال رسالتك لفريق الدعم بنجاح.")
        return

    if state == "admin_ref":
        try:
            amount = int(text)
            save_setting("ref_reward", str(amount))
            states.pop(uid, None)
            bot.reply_to(message, f"✅ تم تحديث مكافأة الإحالة إلى {amount} نقطة.")
        except:
            bot.reply_to(message, "❌ أرسل رقماً صحيحاً.")
        return

    if state == "admin_daily_val":
        try:
            amount = int(text)
            save_setting("daily_gift_val", str(amount))
            states.pop(uid, None)
            bot.reply_to(message, f"✅ تم تحديد قيمة الهدية اليومية بـ {amount} نقطة.")
        except:
            bot.reply_to(message, "❌ أرسل رقماً صحيحاً.")
        return

    if state == "user_gift":
        code = text.upper()
        cursor.execute("SELECT amount, max_uses, used_count FROM gifts WHERE code=?", (code,))
        gift = cursor.fetchone()

        if not gift:
            bot.reply_to(message, "❌ الكود غير صحيح.")
            return
        
        amount, max_uses, used_count = gift

        if used_count >= max_uses:
            bot.reply_to(message, "❌ عذراً، لقد استنفد هذا الكود الحد الأقصى لعدد المستخدمين!")
            return

        cursor.execute("SELECT 1 FROM gift_usages WHERE user_id=? AND code=?", (uid, code))
        if cursor.fetchone():
            bot.reply_to(message, "❌ لقد قمت باستخدام هذا الكود مسبقاً ولا يمكنك استخدامه مرة أخرى.")
            return

        cursor.execute("INSERT INTO gift_usages (user_id, code) VALUES (?, ?)", (uid, code))
        cursor.execute("UPDATE gifts SET used_count = used_count + 1 WHERE code=?", (code,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
        db.commit()

        try:
            bot.send_message(
                BALANCE_CHANNEL,
                f"🎟️ **استخدام كود هدية جديد:**\n\n"
                f"👤 المستخدم: @{message.from_user.username if message.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
                f"🔑 الكود: `{code}`\n"
                f"💰 القيمة: **{amount} نقطة**\n"
                f"📊 الاستخدامات الكلية: `{used_count + 1}/{max_uses}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending gift usage notice: {e}")

        states.pop(uid, None)
        bot.reply_to(message, f"🎉 تم استبدال الكود بنجاح! حصلت على {amount} نقطة.")
        return

    bot.send_message(message.chat.id, "اختر الخدمة من القائمة أدناه 👇", reply_markup=main_menu_markup())

# ==================================================
# دورة التشغيل والإيقاف الآمن للبوت (Bot Lifecycle)
# ==================================================
if __name__ == "__main__":
    print("🤖 Bot is starting and polling safely...")
    try:
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"⚠️ Bot stopped due to an error: {e}")
    finally:
        db.close()
        print("🛑 Bot database connection closed safely.")
