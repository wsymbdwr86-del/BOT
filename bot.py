import os
import sqlite3
import random
import time
import threading
from datetime import date, datetime, timedelta
import telebot
from telebot import types

# ==================================================
# إعدادات البوت والقنوات
# ==================================================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = 7110803688

WITHDRAW_CHANNEL = "@YourWithdrawChannel"
BALANCE_CHANNEL = "@YourBalanceChannel"
SUPPORT_CHANNEL = "@YourSupportChannel"

if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise RuntimeError("ضع توكن البوت الصحيح في TOKEN أولاً.")

bot = telebot.TeleBot(TOKEN, threaded=False)

db = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = db.cursor()

# ==================================================
# قاعدة البيانات
# ==================================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    spins INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0,
    invited_by INTEGER
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
# تسجيل اختصارات الأوامر في تيليجرام (Menu Commands)
# ==================================================
try:
    bot.set_my_commands([
        types.BotCommand("start", "تشغيل البوت والقائمة الرئيسية 🏠"),
        types.BotCommand("admin", "لوحة التحكم والإدارة 👨‍💻")
    ])
except Exception as e:
    print(f"Could not set commands: {e}")

# ==================================================
# نظام إرسال التقرير اليومي الساعة 12 تلقائياً
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
# وظائف مساعدة
# ==================================================
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
# واجهة المستخدم الأساسية
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
    kb.add(
        types.InlineKeyboardButton("📊 إحصائيات البوت", callback_data="adm_stats"),
        types.InlineKeyboardButton("🎁 مكافأة الإحالات", callback_data="adm_ref_reward")
    )
    kb.add(types.InlineKeyboardButton("🔥 مكافأة الإحالات المؤقتة", callback_data="adm_temp_ref"))
    kb.add(
        types.InlineKeyboardButton("📥 مراجعة طلبات السحب", callback_data="adm_withdraw_req"),
        types.InlineKeyboardButton("⚖️ حد الأدنى والأقصى للسحب", callback_data="adm_withdraw_limits")
    )
    kb.add(types.InlineKeyboardButton("📅 سقف السحب اليومي", callback_data="adm_daily_limit"))
    kb.add(
        types.InlineKeyboardButton("➕ إضافة قناة اشتراك", callback_data="adm_add_chan"),
        types.InlineKeyboardButton("🗑️ حذف قناة اشتراك", callback_data="adm_del_chan")
    )
    kb.add(
        types.InlineKeyboardButton("💰 إضافة رصيد لمستخدم", callback_data="adm_add_balance"),
        types.InlineKeyboardButton("💸 خصم رصيد من مستخدم", callback_data="adm_sub_balance")
    )
    kb.add(types.InlineKeyboardButton("👥 البحث وإدارة المستخدمين", callback_data="adm_manage_users"))
    kb.add(types.InlineKeyboardButton("📢 إرسال وإدارة الإعلانات", callback_data="adm_broadcast"))
    kb.add(types.InlineKeyboardButton("🎁 إضافة وتعديل العروض", callback_data="adm_offers"))
    kb.add(
        types.InlineKeyboardButton("📋 إدارة أكواد الهدايا", callback_data="adm_manage_gifts"),
        types.InlineKeyboardButton("🎟️ إنشاء كود هدية", callback_data="adm_create_gift")
    )
    kb.add(types.InlineKeyboardButton("🗑️ حذف الاكواد القديمة", callback_data="adm_del_old_gifts"))
    kb.add(types.InlineKeyboardButton("♻️ تصفير جميع الأرصدة", callback_data="adm_reset_all"))
    kb.add(types.InlineKeyboardButton("🎁 تحديد قيمة الهدية اليومية", callback_data="adm_daily_gift_val"))
    kb.add(types.InlineKeyboardButton("📖 تعديل شرح البوت", callback_data="adm_edit_desc"))
    kb.add(types.InlineKeyboardButton("🎡 إدارة عجلة الحظ", callback_data="adm_wheel"))
    kb.add(
        types.InlineKeyboardButton("🏠 الرئيسية", callback_data="adm_main_menu"),
        types.InlineKeyboardButton("💳 دفع والسحب عبر شام كاش", callback_data="adm_sham_cash")
    )
    return kb

def wheel_menu_markup():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("⚙️ إعدادات العجلة", callback_data="wh_settings"),
        types.InlineKeyboardButton("⚙️ تعديل حدود السحب", callback_data="wh_limits"),
        types.InlineKeyboardButton("➕ إضافة جائزة", callback_data="wh_add_prize"),
        types.InlineKeyboardButton("🎁 قائمة الجوائز وإدارتها", callback_data="wh_list_prizes"),
        types.InlineKeyboardButton("👥 إدارة مستخدمي العجلة", callback_data="wh_users"),
        types.InlineKeyboardButton("💸 طلبات سحب العجلة", callback_data="wh_withdrawals"),
        types.InlineKeyboardButton("🔄 تحديث الإحصائيات", callback_data="wh_stats"),
        types.InlineKeyboardButton("↩️ لوحة الإدارة", callback_data="adm_panel")
    )
    return kb

def register_user(message, inviter=None):
    uid = message.from_user.id
    if get_user(uid):
        return False
    username = message.from_user.username or ""
    valid_inviter = inviter if (inviter and inviter != uid and get_user(inviter)) else None

    cursor.execute("INSERT INTO users (user_id, username, invited_by) VALUES (?, ?, ?)", (uid, username, valid_inviter))
    if valid_inviter:
        reward = int(get_setting("ref_reward") or 10)
        cursor.execute("UPDATE users SET referrals=referrals+1, balance=balance+? WHERE user_id=?", (reward, valid_inviter))
    db.commit()
    return True

@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    if check_ban_message(message):
        return
    inviter = None
    parts = (message.text or "").split()
    if len(parts) > 1:
        try:
            inviter = int(parts[1])
        except ValueError:
            inviter = None
    register_user(message, inviter)
    bot.send_message(uid, "🎉 **أهلاً بك في البوت التفاعلي!**\n\nاختر الخدمة المطلوبة من القائمة أدناه 👇", parse_mode="Markdown", reply_markup=main_menu_markup())

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ هذه اللوحة للمشرفين فقط.")
        return
    bot.send_message(message.chat.id, "👨‍💻 **لوحة التحكم والإدارة**", parse_mode="Markdown", reply_markup=admin_menu_markup())

# ==================================================
# معالجة الضغطات (Callback Queries)
# ==================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    if check_ban_callback(call):
        return

    data = call.data

    # زر الرد على المستخدم من قناة الدعم
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

        import re
        numbers = re.findall(r'\d+', prize_text)
        points_won = int(numbers[0]) if numbers else 10

        cursor.execute("UPDATE users SET balance=balance+?, spins=spins+1 WHERE user_id=?", (points_won, uid))
        cursor.execute("INSERT OR REPLACE INTO wheel_cooldowns (user_id, last_spin) VALUES (?, ?)", (uid, datetime.now().isoformat()))
        db.commit()

        bot.answer_callback_query(call.id, f"🎁 مبروك! ربحت: {prize_text}", show_alert=True)
        bot.send_message(
            call.message.chat.id,
            f"🎡 **نتيجة تدوير عجلة الحظ:**\n\n"
            f"🎉 مبروك يا مبدع! ربحت معنا: **{prize_text}**\n"
            f"💰 تمت إضافة الجائزة إلى رصيدك بنجاح!",
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
            register_user(call.message)
            user = get_user(uid)
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
        bot.send_message(call.message.chat.id, f"ℹ️ **معلومات حسابك:**\n\n🆔 المعرف: `{uid}`\n👤 اليوزر: @{user[1] if user[1] else 'لا يوجد'}\n💰 الرصيد: {user[2]} نقطة\n👥 الإحالات: {user[3]}", parse_mode="Markdown")

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
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"📊 إحصائيات البوت:\n\n👥 المستخدمين: {u_count}\n💰 إجمالي الأرصدة: {p_total}")

    elif data == "adm_ref_reward":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "⛔ للمدير الأساسي فقط", show_alert=True)
            return
        states[uid] = "admin_ref"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"🎁 مكافأة الإحالات الحالية: {get_setting('ref_reward')}\nأرسل القيمة الجديدة:")

    elif data == "adm_temp_ref":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔥 مكافأة الإحالات المؤقتة.")

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

    elif data == "adm_add_chan":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "➕ أرسل معرف القناة المراد إضافتها:")

    elif data == "adm_del_chan":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🗑️ أرسل معرف القناة المراد حذفها:")

    elif data == "adm_add_balance":
        if not is_admin(uid):
            return
        states[uid] = "admin_points"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💰 أرسل المعرف والكمية (مثال: `123456789 50`):", parse_mode="Markdown")

    elif data == "adm_sub_balance":
        if not is_admin(uid):
            return
        states[uid] = "admin_sub_points"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💸 أرسل المعرف والكمية للخصم (مثال: `123456789 20`):", parse_mode="Markdown")

    elif data == "adm_manage_users":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "👥 إدارة المستخدمين.")

    elif data == "adm_broadcast":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📢 أرسل نص الإعلان:")

    elif data == "adm_offers":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🎁 إدارة العروض.")

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

    elif data == "adm_del_old_gifts":
        if not is_admin(uid):
            return
        cursor.execute("DELETE FROM gifts WHERE used_count >= max_uses")
        db.commit()
        bot.answer_callback_query(call.id, "🗑️ تم حذف الأكواد المنتهية!", show_alert=True)

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

    elif data == "adm_edit_desc":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📖 أرسل شرح البوت الجديد:")

    elif data == "adm_wheel":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🎡 **إدارة عجلة الحظ:**", parse_mode="Markdown", reply_markup=wheel_menu_markup())

    elif data == "adm_sham_cash":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💳 إعدادات شام كاش.")

    elif data == "wh_settings":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "⚙️ إعدادات العجلة.")

    elif data == "wh_limits":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "⚙️ تعديل حدود سحب العجلة.")

    elif data == "wh_add_prize":
        if not is_admin(uid):
            return
        states[uid] = "admin_wheel_prize"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "➕ أرسل اسم الجائزة واحتمالها (مثال: `50نقطة 1.5`):", parse_mode="Markdown")

    elif data == "wh_list_prizes":
        if not is_admin(uid):
            return
        cursor.execute("SELECT prize_name, probability FROM wheel_prizes")
        rows = cursor.fetchall()
        res = "🎁 **الجوائز النشطة:**\n\n"
        for r in rows:
            res += f"🏆 {r[0]} — {r[1]}%\n"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, res if rows else "📭 لا توجد جوائز.", parse_mode="Markdown")

    elif data == "wh_users":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "👥 إدارة مستخدمي العجلة.")

    elif data == "wh_withdrawals":
        if not is_admin(uid):
            return
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💸 طلبات سحب العجلة.")

    elif data == "wh_stats":
        if not is_admin(uid):
            return
        cursor.execute("SELECT SUM(probability) FROM wheel_prizes")
        tot = cursor.fetchone()[0] or 0.0
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"🔄 مجموع احتمالات العجلة: **{tot}%**", parse_mode="Markdown")

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

    # معالجة رد المشرف على المستخدم عندما يضغط على زر "رد على المستخدم"
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
            bot.reply_to(message, f"✅ القيمة: {amount} نقطة.\n\n👥 **خطوة 3/3:** أرسل الآن **عدد المستخدمين** الذين يمكنهم استخدام هذا الكود (أرقام فقط):")
        except ValueError:
            bot.reply_to(message, "❌ يرجى إرسال أرقام صحيحة فقط للقيمة:")
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
            bot.reply_to(message, f"✅ المبلغ المطلوب: {amount} نقطة.\n\n📝 الآن أرسل **رقم الحساب أو عنوان المحفظة**:")
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

        bot.send_message(
            WITHDRAW_CHANNEL,
            f"📥 **طلب سحب جديد:**\n\n"
            f"👤 المستخدم: @{message.from_user.username if message.from_user.username else 'لا يوجد'} (ID: `{uid}`)\n"
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

    # استقبال رسالة الدعم من المستخدم وإرسالها للقناة مع زر الرد التفاعلي
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

    if state == "admin_wheel_prize":
        try:
            p_name, p_prob = text.split()
            cursor.execute("INSERT INTO wheel_prizes (prize_name, probability) VALUES (?, ?)", (p_name, float(p_prob)))
            db.commit()
            states.pop(uid, None)
            bot.reply_to(message, f"🎁 تمت إضافة الجائزة ({p_name}) بنجاح!")
        except:
            bot.reply_to(message, "❌ صيغة خطأ. مثال: `50نقطة 1.5`", parse_mode="Markdown")
        return

    if state == "admin_points":
        try:
            target, amount = map(int, text.split())
            cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target))
            db.commit()
            states.pop(uid, None)
            bot.reply_to(message, "✅ تمت إضافة الرصيد بنجاح.")
        except:
            bot.reply_to(message, "❌ صيغة خاطئة.")
        return

    if state == "admin_sub_points":
        try:
            target, amount = map(int, text.split())
            cursor.execute("UPDATE users SET balance=MAX(0, balance-?) WHERE user_id=?", (amount, target))
            db.commit()
            states.pop(uid, None)
            bot.reply_to(message, "✅ تم خصم الرصيد بنجاح.")
        except:
            bot.reply_to(message, "❌ صيغة خاطئة.")
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
# تشغيل البوت
# ==================================================
print("🤖 Bot is starting successfully with fixed support reply system...")
bot.remove_webhook()
bot.infinity_polling(skip_pending=True)
