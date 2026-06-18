import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time
import threading

TOKEN = "8926291831:AAF_SrgXk6E1Pwrp_TprNrMLuMebzh6i8hs"
bot = telebot.TeleBot(TOKEN)

# ---------- база данных ----------
def init_db():
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS contests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        channel_id TEXT,
        participants_limit INTEGER,
        winners_count INTEGER,
        text TEXT,
        photo_id TEXT,
        method TEXT,
        end_type TEXT,
        end_time INTEGER,
        message_id INTEGER,
        status TEXT DEFAULT 'active',
        created_at INTEGER
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER,
        user_id INTEGER,
        username TEXT,
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

def add_participant(contest_id, user_id, username, source):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT * FROM participants WHERE contest_id=? AND user_id=?", (contest_id, user_id))
    if cur.fetchone():
        conn.close()
        return False
    cur.execute("INSERT INTO participants (contest_id, user_id, username, joined_at, source) VALUES (?,?,?,?,?)",
                (contest_id, user_id, username, int(time.time()), source))
    conn.commit()
    conn.close()
    return True

def choose_winners(contest_id):
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT winners_count, channel_id, text FROM contests WHERE id=?", (contest_id,))
    winners_count, channel_id, text = cur.fetchone()
    cur.execute("SELECT user_id, username FROM participants WHERE contest_id=?", (contest_id,))
    participants = cur.fetchall()
    if not participants:
        bot.send_message(channel_id, "недостаточно участников для розыгрыша.")
        cur.execute("UPDATE contests SET status='cancelled' WHERE id=?", (contest_id,))
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

    winner_mentions = []
    for user_id, username in winners:
        if username:
            winner_mentions.append("@" + username)
        else:
            winner_mentions.append("[пользователь](tg://user?id={})".format(user_id))
    result_text = "розыгрыш завершён!\n\nконкурс: " + text[:100] + "...\n\nпобедители:\n" + "\n".join(winner_mentions)
    bot.send_message(channel_id, result_text, parse_mode="Markdown")
    for user_id, username in winners:
        try:
            bot.send_message(user_id, "поздравляем! вы выиграли в конкурсе: " + text[:100] + "...")
        except:
            pass

# ---------- ОБРАБОТЧИК КОММЕНТАРИЕВ (только ответы) ----------
@bot.message_handler(func=lambda msg: msg.reply_to_message is not None)
def handle_comment(msg):
    reply_to_id = msg.reply_to_message.message_id
    chat_id = str(msg.chat.id)
    user = msg.from_user
    if not user or user.is_bot:
        return

    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id, participants_limit, end_type FROM contests WHERE status='active' AND channel_id=? AND message_id=? AND method IN ('comment','both')", (chat_id, reply_to_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        return
    contest_id, limit, end_type = row

    if not is_subscribed(user.id, chat_id):
        bot.reply_to(msg, "вы не подписаны на канал, чтобы участвовать.")
        return

    added = add_participant(contest_id, user.id, user.username or "", "comment")
    if added and end_type == 'limit':
        current = get_participants_count(contest_id)
        if current >= limit:
            choose_winners(contest_id)

# ---------- фоновая проверка конкурсов по времени ----------
def check_time_contests():
    now = int(time.time())
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM contests WHERE status='active' AND end_type='time' AND end_time <= ?", (now,))
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        choose_winners(row[0])
    threading.Timer(60, check_time_contests).start()

threading.Timer(60, check_time_contests).start()

# ---------- МЕНЮ (общее для /start, /67, /xyilan) ----------
@bot.message_handler(commands=['start', '67', 'xyilan'])
def show_menu(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("добавить бота в канал", url=f"https://t.me/{bot.get_me().username}?startchannel=admin"),
        InlineKeyboardButton("создать конкурс", callback_data="create_contest"),
        InlineKeyboardButton("мои конкурсы", callback_data="my_contests"),
        InlineKeyboardButton("случайное число", callback_data="random_number")  # добавили кнопку
    )
    bot.send_message(message.chat.id,
                     "привет! я бот для конкурсов в каналах.\n"
                     "добавьте меня в канал как администратора с правами на отправку и чтение сообщений.\n\n"
                     "выберите действие:", reply_markup=markup, parse_mode="Markdown")

# ---------- ОБРАБОТЧИК ДЛЯ КНОПКИ "случайное число" ----------
@bot.callback_query_handler(func=lambda call: call.data == "random_number")
def random_callback(call):
    bot.answer_callback_query(call.id)
    num = random.randint(1, 100)
    bot.send_message(call.message.chat.id, f"случайное число: {num}")

# ---------- КОМАНДА /random (тоже выдаёт число) ----------
@bot.message_handler(commands=['random'])
def random_command(message):
    num = random.randint(1, 100)
    bot.reply_to(message, f"случайное число: {num}")

# ---------- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (конкурсы) ----------
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

# ---------- создание конкурса ----------
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
    except:
        bot.send_message(chat_id, "не удалось найти канал. проверьте id и права.")
        show_menu(message)
        return
    user_data[chat_id] = {'channel_id': channel_id}
    msg = bot.send_message(chat_id, "сколько участников должно набраться для розыгрыша? (введите число)")
    bot.register_next_step_handler(msg, process_limit, chat_id)

def process_limit(message, chat_id):
    try:
        limit = int(message.text)
        if limit < 2:
            bot.send_message(chat_id, "нужно минимум 2 участника.")
            show_menu(message)
            return
        user_data[chat_id]['limit'] = limit
        msg = bot.send_message(chat_id, "сколько победителей выбрать?")
        bot.register_next_step_handler(msg, process_winners, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите число.")
        show_menu(message)

def process_winners(message, chat_id):
    try:
        winners = int(message.text)
        if winners < 1:
            bot.send_message(chat_id, "должен быть хотя бы 1 победитель.")
            show_menu(message)
            return
        if winners > user_data[chat_id]['limit']:
            bot.send_message(chat_id, "победителей не может быть больше участников (" + str(user_data[chat_id]['limit']) + ").")
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
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("по лимиту участников", callback_data="end_limit"),
        InlineKeyboardButton("по времени", callback_data="end_time")
    )
    bot.send_message(chat_id, "как закончится конкурс?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("end_"))
def process_end_type(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    end_type = call.data.split("_")[1]
    user_data[chat_id]['end_type'] = end_type
    if end_type == 'time':
        msg = bot.send_message(chat_id, "через сколько минут завершить конкурс? (введите число)")
        bot.register_next_step_handler(msg, process_time_minutes, chat_id)
    else:
        finish_creation(call.message, chat_id)

def process_time_minutes(message, chat_id):
    try:
        minutes = int(message.text)
        if minutes < 1:
            bot.send_message(chat_id, "время должно быть больше 0.")
            show_menu(message)
            return
        user_data[chat_id]['end_time'] = int(time.time()) + minutes * 60
        finish_creation(message, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите целое число минут.")
        show_menu(message)

def finish_creation(message, chat_id):
    data = user_data[chat_id]
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute('''INSERT INTO contests 
                   (creator_id, channel_id, participants_limit, winners_count, text, photo_id, method, end_type, end_time, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (message.from_user.id, data['channel_id'], data['limit'], data['winners'],
                 data['text'], data['photo'], data['method'], data['end_type'],
                 data.get('end_time', 0), int(time.time())))
    contest_id = cur.lastrowid
    conn.commit()
    conn.close()

    markup = InlineKeyboardMarkup()
    caption = "розыгрыш!\n\n" + data['text'] + "\n\nнужно участников: " + str(data['limit']) + "\nпобедителей: " + str(data['winners']) + "\n"
    if data['method'] in ['button', 'both']:
        markup.add(InlineKeyboardButton("участвую", callback_data="join_" + str(contest_id)))
        caption += "\nнажмите кнопку, чтобы участвовать."
    if data['method'] in ['comment', 'both']:
        caption += "\n\nили оставьте комментарий под этим постом."
    if data['end_type'] == 'time':
        minutes_left = int((data['end_time'] - time.time()) / 60)
        caption += "\n\nконкурс завершится через " + str(minutes_left) + " минут."

    try:
        if data['photo']:
            sent = bot.send_photo(data['channel_id'], data['photo'], caption=caption, reply_markup=markup if markup.keyboard else None, parse_mode="Markdown")
        else:
            sent = bot.send_message(data['channel_id'], caption, reply_markup=markup if markup.keyboard else None, parse_mode="Markdown")
        if data['method'] in ['comment', 'both']:
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

# ---------- участие по кнопке ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_contest(call):
    contest_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""

    contest = get_contest(contest_id)
    if not contest or contest[11] != 'active':
        bot.answer_callback_query(call.id, "конкурс не активен.", show_alert=True)
        return

    channel_id = contest[2]
    if not is_subscribed(user_id, channel_id):
        bot.answer_callback_query(call.id, "подпишитесь на канал!", show_alert=True)
        return

    added = add_participant(contest_id, user_id, username, "button")
    if not added:
        bot.answer_callback_query(call.id, "вы уже участвуете!", show_alert=True)
        return
    bot.answer_callback_query(call.id, "вы записаны.")

    if contest[8] == 'limit':
        current = get_participants_count(contest_id)
        if current >= contest[3]:
            choose_winners(contest_id)

# ---------- запуск ----------
if __name__ == "__main__":
    print("бот запущен...")
    bot.polling(none_stop=True)
