import random
import psycopg2
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup

print('Start telegram bot...')

# ---------------------- Настройка бота ----------------------
state_storage = StateMemoryStorage()
token_bot = ''  # вставь сюда свой токен
bot = TeleBot(token_bot, state_storage=state_storage)

known_users = []
userStep = {}

# ---------------------- Подключение к БД ----------------------
conn = psycopg2.connect(
    dbname='',
    user='',
    password='',
    host='',
    port=''
)
cur = conn.cursor()

# ---------------------- Вспомогательные функции ----------------------
def show_hint(*lines):
    return '\n'.join(lines)

def show_target(data):
    return f"{data['target_word']} -> {data['translate_word']}"

class Command:
    ADD_WORD = 'Добавить слово ➕'
    DELETE_WORD = 'Удалить слово🔙'
    NEXT = 'Дальше ⏭'

class MyStates(StatesGroup):
    target_word = State()
    translate_word = State()
    another_words = State()

def get_user_step(uid):
    if uid in userStep:
        return userStep[uid]
    else:
        known_users.append(uid)
        userStep[uid] = 0
        print("New user detected, who hasn't used \"/start\" yet")
        return 0

# ---------------------- Функции работы с БД ----------------------
def add_word_to_db(user_id, username, target_word, translate_word, other_words):
    cur.execute("""
        INSERT INTO user_words (user_id, username, target_word, translate_word, other_words)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, username, target_word, translate_word, other_words))
    conn.commit()

def get_words_for_user(user_id):
    cur.execute("SELECT target_word, translate_word, other_words FROM user_words WHERE user_id = %s", (user_id,))
    return cur.fetchall()

def delete_word_from_db(user_id, target_word):
    cur.execute("DELETE FROM user_words WHERE user_id=%s AND target_word=%s", (user_id, target_word))
    conn.commit()

# ---------------------- Обработчики команд ----------------------
@bot.message_handler(commands=['cards', 'start'])
def create_cards(message):
    cid = message.chat.id
    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0
        bot.send_message(cid, "Hello, stranger, let study English...")

    words = get_words_for_user(cid)
    if not words:
        bot.send_message(cid, "У вас нет слов. Добавьте слово с помощью кнопки 'Добавить слово ➕'")
        return

    # Выбираем случайное слово
    word_data = random.choice(words)
    target_word, translate_word, other_words = word_data
    all_words = other_words + [target_word]
    random.shuffle(all_words)

    markup = types.ReplyKeyboardMarkup(row_width=2)
    buttons = [types.KeyboardButton(word) for word in all_words]
    buttons.extend([
        types.KeyboardButton(Command.NEXT),
        types.KeyboardButton(Command.ADD_WORD),
        types.KeyboardButton(Command.DELETE_WORD)
    ])
    markup.add(*buttons)

    greeting = f"Выбери перевод слова:\n🇷🇺 {translate_word}"
    bot.send_message(cid, greeting, reply_markup=markup)

    with bot.retrieve_data(cid, cid) as data:
        data['target_word'] = target_word
        data['translate_word'] = translate_word
        data['other_words'] = other_words

@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_cards(message):
    create_cards(message)

@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def delete_word(message):
    cid = message.chat.id
    with bot.retrieve_data(message.from_user.id, cid) as data:
        delete_word_from_db(cid, data['target_word'])
        bot.send_message(cid, f"Слово {data['target_word']} удалено!")
    create_cards(message)

@bot.message_handler(func=lambda message: message.text == Command.ADD_WORD)
def add_word(message):
    cid = message.chat.id
    bot.send_message(cid, "Введите слово и перевод через дефис (пример: Peace-Мир)")
    bot.set_state(cid, MyStates.target_word, cid)

@bot.message_handler(state=MyStates.target_word)
def save_new_word(message):
    cid = message.chat.id
    text = message.text
    try:
        target, translate = text.split('-')
        other_words = ['Green', 'White', 'Hello', 'Car']  # пример неправильных слов
        add_word_to_db(cid, message.from_user.username, target, translate, other_words)
        bot.send_message(cid, f"Слово {target} добавлено!")
        bot.set_state(cid, None, cid)
    except ValueError:
        bot.send_message(cid, "Неверный формат! Используйте: Слово-Перевод")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    cid = message.chat.id
    text = message.text
    with bot.retrieve_data(message.from_user.id, cid) as data:
        target_word = data['target_word']
        markup = types.ReplyKeyboardMarkup(row_width=2)
        buttons = [types.KeyboardButton(word) for word in data['other_words'] + [target_word]]
        random.shuffle(buttons)
        buttons.extend([
            types.KeyboardButton(Command.NEXT),
            types.KeyboardButton(Command.ADD_WORD),
            types.KeyboardButton(Command.DELETE_WORD)
        ])
        markup.add(*buttons)

        if text == target_word:
            hint = show_target(data)
            hint_text = ["Отлично!❤", hint]
            bot.send_message(cid, show_hint(*hint_text), reply_markup=markup)
        else:
            hint = show_hint("Допущена ошибка!",
                             f"Попробуй ещё раз вспомнить слово 🇷🇺{data['translate_word']}")
            bot.send_message(cid, hint, reply_markup=markup)

# ---------------------- Запуск ----------------------
bot.add_custom_filter(custom_filters.StateFilter(bot))
bot.infinity_polling(skip_pending=True)