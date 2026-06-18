import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time
import threading

TOKEN = "8926291831:AAF_SrgXk6E1Pwrp_TprNrMLuMebzh6i8hs"
bot = telebot.TeleBot(TOKEN)

# ---------- глобальные настройки ----------
REQUIRED_CHANNEL = "@asaltadraws"

# ---------- база данных ----------
def init_db():
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS contests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        channel_id TEXT,
        winners_count INTEGER,
        text TEXT,
        photo_id TEXT,
        method TEXT,
        end_time INTEGER,
        message_id INTEGER,
        extra_channels TEXT,
        status TEXT DEFAULT 'active',
        created_at INTEGER
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER,
        user_id INTEGER,
        username TEXT,
        comment_text TEXT,
        joined_at INTEGER,
        source TEXT,
        FOREIGN KEY(contest_id) REFERENCES contests(id)
    )''')
    conn.commit()
    conn.close()
init_db()

# ---------- вспомогательные функции ----------
def is_subscribed(user_id, channel_id):
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ['member', 'creator', 'administrator']
    except:
        return False

def check_all_subscriptions(user_id, channel_list):
    for ch in channel_list:
        ch = ch.strip()
        if not ch:
            continue
        if not is_subscribed(user_id, ch):
            return False, ch
    return True, None

def get_contest(contest_id):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT * FROM contests WHERE id=?", (contest_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_participants_count(contest_id):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM participants WHERE contest_id=?", (contest_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def add_participant(contest_id, user_id, username, source, comment_text=None):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT * FROM participants WHERE contest_id=? AND user_id=?", (contest_id, user_id))
    if cur.fetchone():
        conn.close()
        return False
    cur.execute("INSERT INTO participants (contest_id, user_id, username, comment_text, joined_at, source) VALUES (?,?,?,?,?,?)",
                (contest_id, user_id, username, comment_text, int(time.time()), source))
    conn.commit()
    conn.close()
    update_participants_button(contest_id)
    return True

def update_participants_button(contest_id):
    contest = get_contest(contest_id)
    if not contest:
        return
    channel_id = contest[2]
    message_id = contest[8]
    method = contest[6]
    if not message_id or method not in ['button', 'both']:
        return
    count = get_participants_count(contest_id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"участвую ({count})", callback_data=f"join_{contest_id}"))
    try:
        bot.edit_message_reply_markup(chat_id=channel_id, message_id=message_id, reply_markup=markup)
    except Exception as e:
        print(f"не удалось обновить кнопку: {e}")

def choose_winners(contest_id):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT winners_count, channel_id, text FROM contests WHERE id=?", (contest_id,))
    winners_count, channel_id, text = cur.fetchone()
    cur.execute("SELECT user_id, username, comment_text FROM participants WHERE contest_id=?", (contest_id,))
    participants = cur.fetchall()
    if not participants:
        cur.execute("UPDATE contests SET status='finished' WHERE id=?", (contest_id,))
        conn.commit()
        conn.close()
        return
    if len(participants) <= winners_count:
        winners = participants
    else:
        winners = random.sample(participants, winners_count)
    cur.execute("UPDATE contests SET status='finished' WHERE id=?", (contest_id,))
    conn.commit()
    conn.close()

    winner_lines = []
    for user_id, username, comment in winners:
        mention = f"@{username}" if username else f"[пользователь](tg://user?id={user_id})"
        if comment:
            winner_lines.append(f"юз: {mention}, коммент: {comment[:50]}...")
        else:
            winner_lines.append(f"юз: {mention} (без комментария)")
    result_text = "конкурс завершён!\n\n" + text[:100] + "...\n\nпобедители:\n" + "\n".join(winner_lines)
    try:
        bot.send_message(channel_id, result_text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(channel_id, result_text)  # без форматирования, если ошибка
    for user_id, username, comment in winners:
        try:
            bot.send_message(user_id, f"поздравляем! вы выиграли в конкурсе: {text[:100]}...")
        except:
            pass

# ---------- ОБРАБОТЧИК КОММЕНТАРИЕВ ----------
@bot.message_handler(func=lambda msg: msg.reply_to_message is not None)
def handle_comment(msg):
    reply_to_id = msg.reply_to_message.message_id
    chat_id = str(msg.chat.id)
    user = msg.from_user
    if not user or user.is_bot:
        return

    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id, extra_channels FROM contests WHERE status='active' AND channel_id=? AND message_id=? AND method IN ('comment','both')", (chat_id, reply_to_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        return
    contest_id, extra_channels = row

    channels_to_check = [REQUIRED_CHANNEL, chat_id]
    if extra_channels:
        channels_to_check.extend([ch.strip() for ch in extra_channels.split(',') if ch.strip()])
    ok, failed = check_all_subscriptions(user.id, channels_to_check)
    if not ok:
        bot.reply_to(msg, f"вы не подписаны на канал {failed}. подпишитесь и участвуйте.")
        return

    added = add_participant(contest_id, user.id, user.username or "", "comment", msg.text)
    if added:
        bot.reply_to(msg, "вы записаны на конкурс!")

# ---------- фоновая проверка по времени ----------
def check_time_contests():
    now = int(time.time())
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM contests WHERE status='active' AND end_time <= ?", (now,))
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        choose_winners(row[0])
    threading.Timer(60, check_time_contests).start()

threading.Timer(60, check_time_contests).start()

# ---------- МЕНЮ ----------
@bot.message_handler(commands=['start', '67', 'xyilan'])
def show_menu(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("добавить бота в канал", url=f"https://t.me/{bot.get_me().username}?startchannel=admin"),
        InlineKeyboardButton("создать конкурс", callback_data="create_contest"),
        InlineKeyboardButton("мои конкурсы", callback_data="my_contests"),
        InlineKeyboardButton("случайное число", callback_data="random_number")
    )
    bot.send_message(message.chat.id,
                     "привет! я бот для конкурсов в каналах.\n"
                     "добавьте меня в канал как администратора с правами на отправку и чтение сообщений.\n\n"
                     "выберите действие:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "random_number")
def random_callback(call):
    bot.answer_callback_query(call.id)
    num = random.randint(1, 30)
    bot.send_message(call.message.chat.id, f"случайное число: {num}")

@bot.message_handler(commands=['random'])
def random_command(message):
    num = random.randint(1, 30)
    bot.reply_to(message, f"случайное число: {num}")

@bot.callback_query_handler(func=lambda call: call.data == "my_contests")
def my_contests(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id, text, status FROM contests WHERE creator_id=? ORDER BY created_at DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.send_message(call.message.chat.id, "у вас пока нет созданных конкурсов.")
        return
    text = "ваши конкурсы:\n\n"
    for row in rows:
        status_emoji = "активен" if row[2] == "active" else "завершён"
        text += "#" + str(row[0]) + ": " + row[1][:50] + "... (статус: " + status_emoji + ")\n"
    bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

# ---------- СОЗДАНИЕ КОНКУРСА ----------
user_data = {}

@bot.callback_query_handler(func=lambda call: call.data == "create_contest")
def ask_channel(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id,
                           "введите id канала (например, @my_channel или -1001234567890).\n"
                           "убедитесь, что я добавлен как администратор.")
    bot.register_next_step_handler(msg, process_channel, call.message.chat.id)

def process_channel(message, chat_id):
    channel = message.text.strip()
    try:
        chat = bot.get_chat(channel)
        if chat.type not in ['channel', 'supergroup']:
            bot.send_message(chat_id, "это не канал. введите корректный id.")
            show_menu(message)
            return
        channel_id = str(chat.id)
        try:
            member = bot.get_chat_member(channel_id, message.from_user.id)
            if member.status not in ['creator', 'administrator']:
                bot.send_message(chat_id, "вы не являетесь владельцем или администратором этого канала.")
                show_menu(message)
                return
        except:
            bot.send_message(chat_id, "не удалось проверить ваши права в канале.")
            show_menu(message)
            return
    except:
        bot.send_message(chat_id, "не удалось найти канал. проверьте id и права.")
        show_menu(message)
        return
    user_data[chat_id] = {'channel_id': channel_id}
    msg = bot.send_message(chat_id, "сколько победителей выбрать?")
    bot.register_next_step_handler(msg, process_winners, chat_id)

def process_winners(message, chat_id):
    try:
        winners = int(message.text)
        if winners < 1:
            bot.send_message(chat_id, "должен быть хотя бы 1 победитель.")
            show_menu(message)
            return
        user_data[chat_id]['winners'] = winners
        msg = bot.send_message(chat_id, "отправьте фото для конкурса (или /skip)")
        bot.register_next_step_handler(msg, process_photo, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите число.")
        show_menu(message)

def process_photo(message, chat_id):
    if message.text and message.text.startswith('/skip'):
        user_data[chat_id]['photo'] = None
        ask_text(message, chat_id)
        return
    if message.photo:
        user_data[chat_id]['photo'] = message.photo[-1].file_id
        ask_text(message, chat_id)
    else:
        bot.send_message(chat_id, "отправьте фото или /skip")
        bot.register_next_step_handler(message, process_photo, chat_id)

def ask_text(message, chat_id):
    msg = bot.send_message(chat_id, "введите текст конкурса (описание, условия)")
    bot.register_next_step_handler(msg, process_text, chat_id)

def process_text(message, chat_id):
    user_data[chat_id]['text'] = message.text
    msg = bot.send_message(chat_id, "введите дополнительные каналы для обязательной подписки (через запятую, например @chan1, @chan2) или /skip")
    bot.register_next_step_handler(msg, process_extra_channels, chat_id)

def process_extra_channels(message, chat_id):
    if message.text and message.text.startswith('/skip'):
        user_data[chat_id]['extra_channels'] = ""
    else:
        user_data[chat_id]['extra_channels'] = message.text.strip()
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("кнопка", callback_data="method_button"),
        InlineKeyboardButton("комментарий", callback_data="method_comment"),
        InlineKeyboardButton("оба", callback_data="method_both")
    )
    bot.send_message(chat_id, "выберите способ участия:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("method_"))
def process_method(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    method = call.data.split("_")[1]
    user_data[chat_id]['method'] = method
    msg = bot.send_message(chat_id, "через сколько минут завершить конкурс? (введите число)")
    bot.register_next_step_handler(msg, process_time_minutes, chat_id)

def process_time_minutes(message, chat_id):
    try:
        minutes = int(message.text)
        if minutes < 1:
            bot.send_message(chat_id, "время должно быть больше 0.")
            show_menu(message)
            return
        end_time = int(time.time()) + minutes * 60
        user_data[chat_id]['end_time'] = end_time
        finish_creation(message, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите целое число минут.")
        show_menu(message)

def finish_creation(message, chat_id):
    data = user_data[chat_id]
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute('''INSERT INTO contests 
                   (creator_id, channel_id, winners_count, text, photo_id, method, end_time, extra_channels, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (message.from_user.id, data['channel_id'], data['winners'],
                 data['text'], data['photo'], data['method'], data['end_time'],
                 data.get('extra_channels', ''), int(time.time())))
    contest_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Подготавливаем пост
    markup = InlineKeyboardMarkup()
    caption = data['text'] + "\n\nпобедителей: " + str(data['winners']) + "\n"
    channels_to_show = [REQUIRED_CHANNEL]
    if data.get('extra_channels'):
        channels_to_show.extend([ch.strip() for ch in data['extra_channels'].split(',') if ch.strip()])
    if channels_to_show:
        caption += "обязательная подписка на каналы: " + ", ".join(channels_to_show) + "\n"

    # Добавляем способ участия
    if data['method'] == 'button':
        caption += "нажмите кнопку, чтобы участвовать."
        count = 0
        markup.add(InlineKeyboardButton(f"участвую ({count})", callback_data=f"join_{contest_id}"))
    elif data['method'] == 'comment':
        caption += "оставьте комментарий под этим постом."
    else:  # both
        caption += "нажмите кнопку или оставьте комментарий под этим постом."
        count = 0
        markup.add(InlineKeyboardButton(f"участвую ({count})", callback_data=f"join_{contest_id}"))

    minutes_left = int((data['end_time'] - time.time()) / 60)
    caption += "\n\nконкурс завершится через " + str(minutes_left) + " минут."

    try:
        if data['photo']:
            sent = bot.send_photo(data['channel_id'], data['photo'], caption=caption, reply_markup=markup if markup.keyboard else None, parse_mode="Markdown")
        else:
            sent = bot.send_message(data['channel_id'], caption, reply_markup=markup if markup.keyboard else None, parse_mode="Markdown")
        conn = sqlite3.connect('giveaway.db')
        cur = conn.cursor()
        cur.execute("UPDATE contests SET message_id=? WHERE id=?", (sent.message_id, contest_id))
        conn.commit()
        conn.close()
        bot.send_message(chat_id, "конкурс создан и опубликован.")
    except Exception as e:
        bot.send_message(chat_id, "ошибка публикации: " + str(e) + "\nпроверьте права бота.")
    del user_data[chat_id]
    show_menu(message)

# ---------- УЧАСТИЕ ПО КНОПКЕ ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_contest(call):
    contest_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""

    contest = get_contest(contest_id)
    if not contest or contest[10] != 'active':
        bot.answer_callback_query(call.id, "конкурс не активен.", show_alert=True)
        return

    channel_id = contest[2]
    extra_channels = contest[9]

    channels_to_check = [REQUIRED_CHANNEL, channel_id]
    if extra_channels:
        channels_to_check.extend([ch.strip() for ch in extra_channels.split(',') if ch.strip()])

    ok, failed = check_all_subscriptions(user_id, channels_to_check)
    if not ok:
        bot.answer_callback_query(call.id, f"вы не подписаны на канал {failed}. подпишитесь и участвуйте.", show_alert=True)
        return

    added = add_participant(contest_id, user_id, username, "button")
    if not added:
        bot.answer_callback_query(call.id, "вы уже участвуете!", show_alert=True)
        return
    bot.answer_callback_query(call.id, "вы записаны.")

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    print("бот запущен...")
    bot.polling(none_stop=True)
