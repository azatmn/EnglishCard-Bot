import os
import random
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
from dotenv import load_dotenv

print('Start telegram bot...')

# Load environment variables
load_dotenv()

# ---------------------- Настройка бота ----------------------
state_storage = StateMemoryStorage()
token_bot = os.getenv('BOT_TOKEN', '')
if not token_bot:
    raise RuntimeError('BOT_TOKEN is not set in environment')
bot = TeleBot(token_bot, state_storage=state_storage)

known_users = []
userStep = {}
current_card_by_chat = {}

# ---------------------- Подключение к БД ----------------------
def get_db_connection():
    dbname = os.getenv('DB_NAME')
    dbuser = os.getenv('DB_USER')
    dbpassword = os.getenv('DB_PASSWORD')
    dbhost = os.getenv('DB_HOST', 'localhost')
    dbport = os.getenv('DB_PORT', '5432')

    try:
        return psycopg2.connect(
            dbname=dbname,
            user=dbuser,
            password=dbpassword,
            host=dbhost,
            port=dbport,
        )
    except psycopg2.OperationalError as exc:
        msg = str(exc)
        if dbname and 'does not exist' in msg:
            # Try to create database by connecting to default 'postgres'
            try:
                admin_conn = psycopg2.connect(
                    dbname='postgres',
                    user=dbuser,
                    password=dbpassword,
                    host=dbhost,
                    port=dbport,
                )
                admin_conn.autocommit = True
                with admin_conn.cursor() as c:
                    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
                admin_conn.close()
                # Retry original connection
                return psycopg2.connect(
                    dbname=dbname,
                    user=dbuser,
                    password=dbpassword,
                    host=dbhost,
                    port=dbport,
                )
            except Exception:
                raise
        raise

try:
    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
except Exception as exc:
    raise RuntimeError(f'Failed to connect to database: {exc}')

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
# Базовый набор слов, доступный всем пользователям
SEED_PAIRS = [
    ('Hello', 'Привет'),
    ('Peace', 'Мир'),
    ('Green', 'Зелёный'),
    ('White', 'Белый'),
    ('Car', 'Машина'),
]


def ensure_schema_and_seed():
    try:
        with conn.cursor() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY,
                target_word TEXT NOT NULL UNIQUE,
                translate_word TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS user_words (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT,
                word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                UNIQUE (user_id, word_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id);
            """)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise

    # Seed common words into global dictionary
    try:
        with conn.cursor() as c:
            for target_word, translate_word in SEED_PAIRS:
                c.execute(
                    "INSERT INTO words (target_word, translate_word) VALUES (%s, %s) ON CONFLICT (target_word) DO NOTHING",
                    (target_word, translate_word),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def seed_user_words_for_user(user_id):
    """Привязать базовый набор слов к конкретному пользователю (без дублей)."""
    try:
        with conn.cursor() as c:
            # Получить id всех слов из словаря
            c.execute("SELECT id FROM words")
            word_ids = [row[0] for row in c.fetchall()]
            # Вставить связи, игнорируя существующие
            for wid in word_ids:
                c.execute(
                    "INSERT INTO user_words (user_id, word_id) VALUES (%s, %s) ON CONFLICT (user_id, word_id) DO NOTHING",
                    (user_id, wid),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def seed_user_words_for_all_users():
    """Привязать базовый набор слов ко всем существующим пользователям."""
    try:
        with conn.cursor() as c:
            c.execute("SELECT id FROM users")
            user_ids = [row[0] for row in c.fetchall()]
        for uid in user_ids:
            seed_user_words_for_user(uid)
    except Exception:
        # уже логика отката внутри seed_user_words_for_user
        pass


def add_word_to_user(user_id, username, target_word, translate_word):
    try:
        with conn.cursor() as c:
            # Ensure user exists
            c.execute(
                "INSERT INTO users (id, username) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username",
                (user_id, username),
            )
            # Ensure word exists in global dictionary
            c.execute("SELECT id FROM words WHERE target_word=%s", (target_word,))
            row = c.fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO words (target_word, translate_word) VALUES (%s, %s) RETURNING id",
                    (target_word, translate_word),
                )
                word_id = c.fetchone()[0]
            else:
                word_id = row[0]

            # Link to user, ignore duplicates
            c.execute(
                "INSERT INTO user_words (user_id, username, word_id) VALUES (%s, %s, %s) ON CONFLICT (user_id, word_id) DO NOTHING",
                (user_id, username, word_id),
            )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        return False


def get_words_for_user(user_id):
    try:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT uw.id as user_word_id, w.target_word, w.translate_word
                FROM user_words uw
                JOIN words w ON w.id = uw.word_id
                WHERE uw.user_id = %s
                ORDER BY uw.created_at DESC
                """,
                (user_id,),
            )
            return c.fetchall()
    except Exception:
        return []


def delete_user_word(user_id, user_word_id):
    try:
        with conn.cursor() as c:
            c.execute(
                "DELETE FROM user_words WHERE id=%s AND user_id=%s",
                (user_word_id, user_id),
            )
            affected = c.rowcount
        conn.commit()
        return affected > 0
    except Exception:
        conn.rollback()
        return False

# ---------------------- Обработчики команд ----------------------
@bot.message_handler(commands=['cards', 'start'])
def create_cards(message):
    cid = message.chat.id
    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0
        bot.send_message(cid, "Hello, stranger, let study English...")
        try:
            with conn.cursor() as c:
                c.execute(
                    "INSERT INTO users (id, username) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username",
                    (cid, message.from_user.username),
                )
            conn.commit()
            # При первой встрече добавим базовый набор слов этому пользователю
            seed_user_words_for_user(cid)
        except Exception:
            conn.rollback()

    words = get_words_for_user(cid)
    if not words:
        bot.send_message(cid, "У вас нет слов. Добавьте слово с помощью кнопки 'Добавить слово ➕'")
        return

    # Выбираем случайное слово
    word_data = random.choice(words)
    # words rows: user_word_id, target_word, translate_word
    user_word_id, target_word, translate_word = word_data
    # generate 3 distractors from global words
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT target_word FROM words WHERE target_word <> %s ORDER BY random() LIMIT 3",
                (target_word,),
            )
            distractors = [r[0] for r in c.fetchall()]
    except Exception:
        distractors = []
    all_words = distractors + [target_word]
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

    current_card_by_chat[cid] = {
        'user_word_id': user_word_id,
        'target_word': target_word,
        'translate_word': translate_word,
    }

@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_cards(message):
    create_cards(message)

@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def delete_word(message):
    cid = message.chat.id
    data = current_card_by_chat.get(cid)
    if not data:
        create_cards(message)
        return
    success = delete_user_word(cid, data.get('user_word_id'))
    if success:
        bot.send_message(cid, f"Слово {data['target_word']} удалено!")
    else:
        bot.send_message(cid, "Не удалось удалить слово. Попробуйте позже.")
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
        target, translate = [x.strip() for x in text.split('-')]
        if not target or not translate:
            raise ValueError
        added = add_word_to_user(cid, message.from_user.username, target, translate)
        if added:
            bot.send_message(cid, f"Слово {target} добавлено!")
        else:
            bot.send_message(cid, f"Слово {target} уже есть в вашем словаре.")
        bot.set_state(cid, None, cid)
    except ValueError:
        bot.send_message(cid, "Неверный формат! Используйте: Слово-Перевод")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    cid = message.chat.id
    text = (message.text or '').strip()
    # Игнорируем служебные кнопки, у них есть отдельные хендлеры
    if text in {Command.NEXT, Command.ADD_WORD, Command.DELETE_WORD}:
        return
    try:
        data = current_card_by_chat.get(cid)
        if not data:
            create_cards(message)
            return
        target_word = data.get('target_word')
        translate_word = data.get('translate_word')

        markup = types.ReplyKeyboardMarkup(row_width=2)
        # Regenerate options each time for robustness
        try:
            with conn.cursor() as c:
                c.execute(
                    "SELECT target_word FROM words WHERE target_word <> %s ORDER BY random() LIMIT 3",
                    (target_word,),
                )
                distractors = [r[0] for r in c.fetchall()]
        except Exception:
            distractors = []
        buttons = [types.KeyboardButton(word) for word in distractors + [target_word]]
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
                             f"Попробуй ещё раз вспомнить слово 🇷🇺{translate_word}")
            bot.send_message(cid, hint, reply_markup=markup)
    except Exception:
        create_cards(message)

# ---------------------- Запуск ----------------------
ensure_schema_and_seed()
seed_user_words_for_all_users()
bot.add_custom_filter(custom_filters.StateFilter(bot))
bot.infinity_polling(skip_pending=True)