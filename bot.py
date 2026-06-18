import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time
import threading
import re

TOKEN = "8926291831:AAF_SrgXk6E1Pwrp_TprNrMLuMebzh6i8hs"  # замените на реальный токен
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
        method TEXT,               -- button, comment, both
        end_type TEXT,             -- limit или time
        end_time INTEGER,          -- unix timestamp для time
        message_id INTEGER,
        last_checked_id INTEGER,
        status TEXT DEFAULT 'active',
        created_at INTEGER
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER,
        user_id INTEGER,
        username TEXT,
        joined_at INTEGER,
        source TEXT,               -- button или comment
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

# ---------- фоновая проверка комментариев ----------
def check_comments():
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id, channel_id, message_id, last_checked_id, participants_limit FROM contests WHERE status='active' AND method IN ('comment','both')")
    contests = cur.fetchall()
    conn.close()

    for contest_id, channel_id, msg_id, last_checked, limit in contests:
        try:
            if last_checked:
                from_id = last_checked
            else:
                from_id = msg_id
            messages = bot.get_chat_history(channel_id, from_message_id=from_id, limit=100)
            new_last = from_id
            for msg in messages:
                if msg.reply_to_message and msg.reply_to_message.message_id == msg_id:
                    user = msg.from_user
                    if user and not user.is_bot:
                        added = add_participant(contest_id, user.id, user.username or "", "comment")
                        if added:
                            current = get_participants_count(contest_id)
                            # если конкурс по лимиту и достигнут - запускаем
                            contest = get_contest(contest_id)
                            if contest and contest[8] == 'limit' and current >= limit:
                                choose_winners(contest_id)
                                break
                if msg.message_id > new_last:
                    new_last = msg.message_id
            conn = sqlite3.connect('giveaway.db')
            cur = conn.cursor()
            cur.execute("UPDATE contests SET last_checked_id=? WHERE id=?", (new_last, contest_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print("ошибка при проверке комментариев для конкурса", contest_id, e)
    
    threading.Timer(30, check_comments).start()

# ---------- фоновая проверка конкурсов по времени ----------
def check_time_contests():
    now = int(time.time())
    conn = sqlite3.connect('giveaway.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM contests WHERE status='active' AND end_type='time' AND end_time <= ?", (now,))
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        contest_id = row[0]
        choose_winners(contest_id)
    threading.Timer(60, check_time_contests).start()  # проверяем каждую минуту

# запускаем фоновые потоки
threading.Timer(30, check_comments).start()
threading.Timer(60, check_time_contests).start()

# ---------- /start ----------
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("добавить бота в канал", url=f"https://t.me/{bot.get_me().username}?startchannel=admin"),
        InlineKeyboardButton("создать конкурс", callback_data="create_contest"),
        InlineKeyboardButton("мои конкурсы", callback_data="my_contests")
    )
    bot.send_message(message.chat.id,
                     "привет! я бот для конкурсов в каналах.\n"
                     "добавьте меня в канал как администратора с правами на отправку сообщений.\n"
                     "для конкурсов по комментариям нужно право чтения сообщений.\n\n"
                     "выберите действие:", reply_markup=markup, parse_mode="Markdown")

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

# ---------- создание конкурса (пошагово) ----------
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
            start(message)
            return
        channel_id = str(chat.id)
    except:
        bot.send_message(chat_id, "не удалось найти канал. проверьте id и права.")
        start(message)
        return
    user_data[chat_id] = {'channel_id': channel_id}
    msg = bot.send_message(chat_id, "сколько участников должно набраться для розыгрыша? (введите число)")
    bot.register_next_step_handler(msg, process_limit, chat_id)

def process_limit(message, chat_id):
    try:
        limit = int(message.text)
        if limit < 2:
            bot.send_message(chat_id, "нужно минимум 2 участника.")
            start(message)
            return
        user_data[chat_id]['limit'] = limit
        msg = bot.send_message(chat_id, "сколько победителей выбрать?")
        bot.register_next_step_handler(msg, process_winners, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите число.")
        start(message)

def process_winners(message, chat_id):
    try:
        winners = int(message.text)
        if winners < 1:
            bot.send_message(chat_id, "должен быть хотя бы 1 победитель.")
            start(message)
            return
        if winners > user_data[chat_id]['limit']:
            bot.send_message(chat_id, "победителей не может быть больше участников (" + str(user_data[chat_id]['limit']) + ").")
            start(message)
            return
        user_data[chat_id]['winners'] = winners
        msg = bot.send_message(chat_id, "отправьте фото для конкурса (или /skip)")
        bot.register_next_step_handler(msg, process_photo, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите число.")
        start(message)

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
    # спрашиваем метод участия
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
    # теперь спрашиваем тип завершения
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
    end_type = call.data.split("_")[1]  # limit или time
    user_data[chat_id]['end_type'] = end_type
    if end_type == 'time':
        msg = bot.send_message(chat_id, "через сколько минут завершить конкурс? (введите число)")
        bot.register_next_step_handler(msg, process_time_minutes, chat_id)
    else:
        # по лимиту - сразу сохраняем
        finish_creation(call.message, chat_id)

def process_time_minutes(message, chat_id):
    try:
        minutes = int(message.text)
        if minutes < 1:
            bot.send_message(chat_id, "время должно быть больше 0.")
            start(message)
            return
        user_data[chat_id]['end_time'] = int(time.time()) + minutes * 60
        finish_creation(message, chat_id)
    except:
        bot.send_message(chat_id, "ошибка! введите целое число минут.")
        start(message)

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

    # публикуем пост
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
            sent = bot.send_photo(data['channel_id'], data['photo'], caption=caption, reply_markup=markup if markup.inline_keyboard else None, parse_mode="Markdown")
        else:
            sent = bot.send_message(data['channel_id'], caption, reply_markup=markup if markup.inline_keyboard else None, parse_mode="Markdown")
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
    start(message)  # возврат в меню

# ---------- участие по кнопке ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_contest(call):
    contest_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""

    contest = get_contest(contest_id)
    if not contest or contest[7] != 'active':  # index status? проверим
        bot.answer_callback_query(call.id, "конкурс не активен.", show_alert=True)
        return
    # contest indexes: 0 id,1 creator,2 channel,3 limit,4 winners,5 text,6 photo,7 method,8 end_type,9 end_time,10 msg_id,11 last_checked,12 status,13 created
    if contest[12] != 'active':
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

    # если конкурс по лимиту и достигнут - запускаем
    if contest[8] == 'limit':
        current = get_participants_count(contest_id)
        if current >= contest[3]:
            choose_winners(contest_id)

# ---------- запуск ----------
if __name__ == "__main__":
    print("бот запущен...")
    bot.polling(none_stop=True)
