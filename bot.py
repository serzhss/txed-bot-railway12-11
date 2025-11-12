# bot.py — исправленная версия
import os
import logging
import json
import datetime
import time
import threading
import sqlite3
from contextlib import closing
from dotenv import load_dotenv
load_dotenv()

from telebot import TeleBot, types, custom_filters
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

# ----------------- НАСТРОЙКА -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("🔧 Инициализация бота...")

# Токен обязателен — задайте в переменных окружения BOT_TOKEN на Railway
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("token") or ""
ADMIN_ID = int(os.getenv("ADMIN_ID") or os.getenv("admin_id") or "0")

if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан. Задайте переменную окружения BOT_TOKEN.")
    raise SystemExit(1)
if ADMIN_ID == 0:
    print("⚠️ Внимание: ADMIN_ID пуст или равен 0. Задайте на Railway ADMIN_ID (ваш Telegram ID).")

storage = StateMemoryStorage()
bot = TeleBot(TOKEN, state_storage=storage)

# Добавляем фильтр состояний (важно!)
bot.add_custom_filter(custom_filters.StateFilter(bot))

# ----------------- БАЗА ДАННЫХ (SQLite) -----------------
DB_FILE = "users.db"

def init_db():
    with closing(sqlite3.connect(DB_FILE, check_same_thread=False)) as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        full_name TEXT,
                        first_seen TEXT,
                        last_activity TEXT,
                        messages_count INTEGER DEFAULT 0
                    )""")
        conn.commit()

init_db()

def add_user_db(user_id, username, first_name, last_name):
    """Добавляет или обновляет пользователя (upsert)."""
    full_name = f"{first_name or ''} {last_name or ''}".strip() or None
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
        cur = conn.cursor()
        # Попробуем вставить; если уже есть — обновим
        cur.execute("""
            INSERT INTO users(user_id, username, first_name, last_name, full_name, first_seen, last_activity, messages_count)
            VALUES(?,?,?,?,?,?,?,1)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                full_name=excluded.full_name,
                last_activity=excluded.last_activity,
                messages_count=users.messages_count + 1
        """, (user_id, username, first_name, last_name, full_name, now, now))
        conn.commit()
    logger.info("✅ add_user_db: %s", user_id)

def get_all_users_db():
    """Возвращает словарь пользователей как в прежней реализации."""
    with sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name, last_name, full_name, first_seen, last_activity, messages_count FROM users")
        rows = cur.fetchall()
    users = {}
    for r in rows:
        users[str(r[0])] = {
            "username": r[1],
            "first_name": r[2],
            "last_name": r[3],
            "full_name": r[4] or "Неизвестно",
            "first_seen": r[5],
            "last_activity": r[6],
            "messages_count": r[7] or 0
        }
    logger.info("📥 Загружено пользователей: %d", len(users))
    return users

def update_user_activity_db(user_id):
    """Обновляет last_activity и увеличивает messages_count. Если пользователя нет — создаём минимальную запись."""
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            cur.execute("UPDATE users SET last_activity = ?, messages_count = messages_count + 1 WHERE user_id = ?", (now, user_id))
        else:
            # Минимальная запись — пользователь мог не вызвать /start
            cur.execute("""
                INSERT INTO users(user_id, username, first_name, last_name, full_name, first_seen, last_activity, messages_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, None, None, None, None, now, now, 1))
        conn.commit()
    logger.debug("🔄 Обновлена активность: %s", user_id)

# ----------------- ДАННЫЕ КАТАЛОГА (как у тебя) -----------------
bikes = {
    "PRIMO": {
        "description": "🚴‍♂️ <b>PRIMO</b>\n\nМаневренная, универсальная модель...",
        "photos": [
            "https://optim.tildacdn.com/tild6336-3032-4434-b935-346363326131/-/format/webp/Photo-70.webp",
            "https://optim.tildacdn.com/tild6536-6564-4661-b563-323737643733/-/format/webp/Photo-45.webp"
        ],
        "specs": {"Вилка": "UDING DS HLO", "Тормоза": "SHIMANO MT 200"}
    },
    "TERZO": {
        "description": "🚴‍♂️ <b>TERZO</b>\n\nНа треть эффективнее аналогов...",
        "photos": ["https://optim.tildacdn.com/tild3531-3036-4463-b536-303235326633/-/format/webp/Photo-71.webp"],
        "specs": {"Вилка": "UDING DS HLO", "Тормоза": "SHIMANO MT 200"}
    },
    # ... (при необходимости добавь остальные модели как в исходнике)
}

frame_sizes = {
    "M (17\")": "163-177 см",
    "L (19\")": "173-187 см",
    "XL (21\")": "182-197 см"
}

# Локальный словарь для текущих выборов (временный, для UX)
user_selections = {}

# ----------------- FSM -----------------
class ContactForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()

class AdminForm(StatesGroup):
    waiting_for_broadcast_message = State()

# ----------------- ХЭЛПЕРЫ (photo nav, send broadcast) -----------------
user_photo_index = {}

def show_photo(message, user_id, bike_name, photo_index):
    bike_data = bikes[bike_name]
    photos = bike_data["photos"]
    kb = types.InlineKeyboardMarkup()
    if len(photos) > 1:
        row = []
        if photo_index > 0:
            row.append(types.InlineKeyboardButton("⬅️", callback_data=f"prev_photo_{bike_name}"))
        row.append(types.InlineKeyboardButton(f"{photo_index + 1}/{len(photos)}", callback_data="photo_counter"))
        if photo_index < len(photos) - 1:
            row.append(types.InlineKeyboardButton("➡️", callback_data=f"next_photo_{bike_name}"))
        kb.row(*row)
    kb.add(types.InlineKeyboardButton("📋 Спецификация", callback_data=f"specs_{bike_name}"))
    kb.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{bike_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад в каталог", callback_data="back_to_catalog"))

    caption = bike_data["description"] if photo_index == 0 else f"Фото {photo_index + 1} из {len(photos)}"
    try:
        bot.send_photo(message.chat.id, photos[photo_index], caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        # В случае ошибки с ссылкой на фото — отправим текст
        bot.send_message(message.chat.id, caption, reply_markup=kb, parse_mode="HTML")
        logger.warning("Не удалось отправить фото: %s", e)

def _send_broadcast_thread(users_dict, message_text, chat_id, message_id):
    success_count = 0
    fail_count = 0
    for i, user_id in enumerate(list(users_dict.keys())):
        try:
            bot.send_message(int(user_id), message_text)
            success_count += 1
            # пауза каждые 10 сообщений
            if (i + 1) % 10 == 0:
                time.sleep(1)
        except Exception as e:
            fail_count += 1
            logger.warning("Ошибка отправки %s: %s", user_id, e)
    result_text = (
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Не удалось: {fail_count}\n"
        f"👥 Всего: {len(users_dict)}"
    )
    try:
        bot.edit_message_text(result_text, chat_id, message_id, parse_mode="HTML")
    except Exception as e:
        logger.warning("Не удалось обновить сообщение с результатом рассылки: %s", e)

# ----------------- АДМИН-ПАНЕЛЬ -----------------
@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.send_message(msg.chat.id, "⛔ У вас нет доступа к админ-панели")
        return

    users = get_all_users_db()
    total_users = len(users)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📊 Статистика"))
    kb.add(types.KeyboardButton("📢 Рассылка"))
    kb.add(types.KeyboardButton("📋 Список пользователей"))
    kb.add(types.KeyboardButton("⬅️ Выйти из админки"))

    bot.send_message(
        msg.chat.id,
        f"👑 <b>Админ-панель</b>\n\n"
        f"📈 Всего пользователей: {total_users}\n"
        f"🆔 Ваш ID: {ADMIN_ID}",
        parse_mode="HTML",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id == ADMIN_ID)
def show_stats(msg):
    users = get_all_users_db()
    total_users = len(users)

    today = datetime.datetime.now().date()
    active_today = 0
    active_week = 0
    week_ago = today - datetime.timedelta(days=7)

    for user_data in users.values():
        try:
            last_activity_str = user_data.get('last_activity', '')
            if last_activity_str:
                last_activity = datetime.datetime.fromisoformat(last_activity_str).date()
                if last_activity == today:
                    active_today += 1
                if last_activity >= week_ago:
                    active_week += 1
        except Exception as e:
            logger.warning("Ошибка обработки даты активности: %s", e)
            continue

    total_messages = sum(user_data.get('messages_count', 0) for user_data in users.values())

    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных сегодня: {active_today}\n"
        f"📈 Активных за неделю: {active_week}\n"
        f"💬 Всего сообщений: {total_messages}\n"
        f"📅 Дата: {today.strftime('%d.%m.%Y')}"
    )

    bot.send_message(msg.chat.id, stats_text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📋 Список пользователей" and m.from_user.id == ADMIN_ID)
def show_users_list(msg):
    users = get_all_users_db()

    if not users:
        bot.send_message(msg.chat.id, "📭 Пользователей пока нет")
        return

    sorted_users = []
    for user_id, user_data in users.items():
        try:
            last_activity_str = user_data.get('last_activity', '')
            if last_activity_str:
                last_activity = datetime.datetime.fromisoformat(last_activity_str)
            else:
                last_activity = datetime.datetime.fromtimestamp(0)
            sorted_users.append((user_id, user_data, last_activity))
        except Exception as e:
            logger.warning("Ошибка сортировки пользователя %s: %s", user_id, e)
            continue

    sorted_users.sort(key=lambda x: x[2], reverse=True)

    users_list = "👥 <b>Последние пользователи:</b>\n\n"
    for i, (user_id, user_data, last_activity) in enumerate(sorted_users[:10], 1):
        try:
            first_seen_str = user_data.get('first_seen', '')
            first_seen = datetime.datetime.fromisoformat(first_seen_str).strftime('%d.%m.%Y') if first_seen_str else 'неизвестно'
            last_activity_str = last_activity.strftime('%d.%m.%Y %H:%M') if isinstance(last_activity, datetime.datetime) else 'неизвестно'
            messages_count = user_data.get('messages_count', 0)
            username = user_data.get('username', 'нет')
            full_name = user_data.get('full_name', 'Неизвестно')

            users_list += (
                f"{i}. {full_name}\n"
                f"   👤 @{username}\n"
                f"   🆔 {user_id}\n"
                f"   📅 Первый визит: {first_seen}\n"
                f"   ⏰ Последняя активность: {last_activity_str}\n"
                f"   💬 Сообщений: {messages_count}\n\n"
            )
        except Exception as e:
            logger.warning("Ошибка форматирования пользователя %s: %s", user_id, e)
            continue

    if len(users) > 10:
        users_list += f"... и еще {len(users) - 10} пользователей"

    bot.send_message(msg.chat.id, users_list, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка" and m.from_user.id == ADMIN_ID)
def start_broadcast(msg):
    users = get_all_users_db()
    total_users = len(users)

    if total_users == 0:
        bot.send_message(msg.chat.id, "❌ Нет пользователей для рассылки")
        return

    bot.send_message(
        msg.chat.id,
        f"📢 <b>Рассылка сообщений</b>\n\n"
        f"Получателей: {total_users} пользователей\n\n"
        "Отправьте сообщение, которое хотите разослать:",
        parse_mode="HTML"
    )
    bot.set_state(msg.from_user.id, AdminForm.waiting_for_broadcast_message, msg.chat.id)

@bot.message_handler(state=AdminForm.waiting_for_broadcast_message, content_types=['text'])
def process_broadcast_message(msg):
    users = get_all_users_db()
    total_users = len(users)

    if total_users == 0:
        bot.send_message(msg.chat.id, "❌ Нет пользователей для рассылки")
        bot.delete_state(msg.from_user.id, msg.chat.id)
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Разослать", callback_data="confirm_broadcast"))
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast"))

    with bot.retrieve_data(msg.from_user.id, msg.chat.id) as data:
        data['broadcast_message'] = msg.text

    preview_text = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text

    bot.send_message(
        msg.chat.id,
        f"📢 <b>Подтверждение рассылки</b>\n\n"
        f"Сообщение: {preview_text}\n\n"
        f"Получателей: {total_users} пользователей\n\n"
        f"Подтвердите отправку:",
        parse_mode="HTML",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda call: call.data == "confirm_broadcast")
def confirm_broadcast(call):
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        message_text = data.get('broadcast_message', '')
    if not message_text:
        bot.answer_callback_query(call.id, "Ошибка: сообщение не найдено")
        return

    users = get_all_users_db()
    bot.edit_message_text("🔄 Рассылка начата...", call.message.chat.id, call.message.message_id)

    # Запускаем в отдельном потоке, чтобы не блокировать бот
    threading.Thread(target=_send_broadcast_thread, args=(users, message_text, call.message.chat.id, call.message.message_id), daemon=True).start()

    bot.delete_state(call.from_user.id, call.message.chat.id)
    bot.answer_callback_query(call.id, "Запущено")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_broadcast")
def cancel_broadcast(call):
    bot.delete_state(call.from_user.id, call.message.chat.id)
    try:
        bot.edit_message_text("❌ Рассылка отменена", call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.text == "⬅️ Выйти из админки" and m.from_user.id == ADMIN_ID)
def exit_admin(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Каталог 🚲"))
    kb.add(types.KeyboardButton("Позвать специалиста 👨‍💼"))
    kb.add(types.KeyboardButton("О нас ℹ️"))

    bot.send_message(msg.chat.id, "✅ Вы вышли из админ-панели", reply_markup=kb)

# ----------------- ОСНОВНАЯ ЛОГИКА БОТА -----------------
@bot.message_handler(commands=['start'])
def start(msg):
    add_user_db(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Каталог 🚲"))
    kb.add(types.KeyboardButton("Позвать специалиста 👨‍💼"))
    kb.add(types.KeyboardButton("О нас ℹ️"))

    welcome_text = "👋 Добро пожаловать!\n\nЯ помогу вам выбрать идеальный велосипед 🚴‍♂️\n\nВыберите действие из меню ниже:"
    bot.send_message(msg.chat.id, welcome_text, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text and "специалиста" in m.text.lower())
def call_specialist(msg):
    update_user_activity_db(msg.from_user.id)

    bot.send_message(msg.chat.id, "Отлично! Я уведомил специалиста. С вами свяжутся в ближайшее время! ☎️")
    specialist_message = f"👨‍💼 ЗАПРОС СПЕЦИАЛИСТА\n\nПользователь: {msg.from_user.first_name or 'Неизвестно'}\nID: {msg.from_user.id}\nUsername: @{msg.from_user.username or 'не указан'}"
    try:
        bot.send_message(ADMIN_ID, specialist_message)
    except Exception as e:
        logger.warning("Не удалось отправить администратору сообщение о специалисте: %s", e)

@bot.message_handler(func=lambda m: m.text and "каталог" in m.text.lower())
def catalog(msg):
    update_user_activity_db(msg.from_user.id)
    kb = types.InlineKeyboardMarkup()
    for bike in bikes:
        kb.add(types.InlineKeyboardButton(bike, callback_data=bike))
    bot.send_message(msg.chat.id, "Выбери модель:", reply_markup=kb)

# Единый обработчик для выбора модели (из каталога) — нет дубликатов
@bot.callback_query_handler(func=lambda call: call.data in bikes or call.data.startswith(("prev_photo_", "next_photo_", "specs_", "order_", "size_", "back_to_catalog")))
def handle_callback(call):
    data = call.data

    # Навигация по фото
    if data.startswith("prev_photo_") or data.startswith("next_photo_"):
        update_user_activity_db(call.from_user.id)
        user_id = call.from_user.id
        if user_id not in user_photo_index:
            bot.answer_callback_query(call.id, "Сессия устарела, начните заново")
            return
        current_data = user_photo_index[user_id]
        bike_name = current_data['bike']
        current_index = current_data['index']
        photos = bikes[bike_name]["photos"]
        if data.startswith("prev_photo_"):
            new_index = max(0, current_index - 1)
        else:
            new_index = min(len(photos) - 1, current_index + 1)
        user_photo_index[user_id]['index'] = new_index
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        show_photo(call.message, user_id, bike_name, new_index)
        bot.answer_callback_query(call.id)
        return

    # Показ модели (или возврат к модели по названию)
    if data in bikes:
        update_user_activity_db(call.from_user.id)
        name = data
        user_photo_index[call.from_user.id] = {'bike': name, 'index': 0}
        # отправляем первое фото/карточку
        show_photo(call.message, call.from_user.id, name, 0)
        bot.answer_callback_query(call.id)
        return

    # Показ спецификации
    if data.startswith("specs_"):
        update_user_activity_db(call.from_user.id)
        bike_name = data.replace("specs_", "")
        bike_data = bikes.get(bike_name)
        if not bike_data:
            bot.answer_callback_query(call.id, "Модель не найдена")
            return
        specs = bike_data["specs"]
        specs_text = f"🔧 <b>Спецификация {bike_name}</b>\n\n"
        for component, value in specs.items():
            specs_text += f"• <b>{component}:</b> {value}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад к модели", callback_data=bike_name))
        kb.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{bike_name}"))
        bot.send_message(call.message.chat.id, specs_text, parse_mode="HTML", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    # Начало оформления заказа — выбор размера
    if data.startswith("order_"):
        update_user_activity_db(call.from_user.id)
        bike_name = data.replace("order_", "")
        user_selections[call.from_user.id] = {"bike": bike_name}
        kb = types.InlineKeyboardMarkup()
        for size, height_range in frame_sizes.items():
            kb.add(types.InlineKeyboardButton(f"{size} ({height_range})", callback_data=f"size_{size}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад к модели", callback_data=bike_name))
        bot.send_message(call.message.chat.id, f"Вы выбрали {bike_name}! 🚴‍♂️\n\nТеперь выбери размер рамы:", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    # Сохранение размера и переход к сбору контактных данных (через FSM)
    if data.startswith("size_"):
        update_user_activity_db(call.from_user.id)
        frame_size = data.replace("size_", "")
        user_id = call.from_user.id
        if user_id in user_selections:
            user_selections[user_id]["frame_size"] = frame_size
            user_selections[user_id]["height_range"] = frame_sizes.get(frame_size, "")
        bike_name = user_selections.get(user_id, {}).get("bike", "Неизвестная модель")

        bot.send_message(call.message.chat.id, f"Отлично! 🎯\nМодель: {bike_name}\nРазмер рамы: {frame_size} ({user_selections[user_id].get('height_range','')})\n\nТеперь напиши своё имя:")
        # Переводим пользователя в состояние ожидания имени
        bot.set_state(call.from_user.id, ContactForm.waiting_for_name, call.message.chat.id)
        bot.answer_callback_query(call.id)
        return

    # Возврат к каталогу
    if data == "back_to_catalog":
        update_user_activity_db(call.from_user.id)
        kb = types.InlineKeyboardMarkup()
        for bike in bikes:
            kb.add(types.InlineKeyboardButton(bike, callback_data=bike))
        bot.send_message(call.message.chat.id, "Выбери модель:", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    # Если ничего не подошло
    bot.answer_callback_query(call.id, "Неизвестная команда")

# ----------------- FSM: сбор контактов для заявки -----------------
@bot.message_handler(state=ContactForm.waiting_for_name, content_types=['text'])
def process_name(msg):
    name = msg.text.strip()
    if not name:
        bot.send_message(msg.chat.id, "Имя не может быть пустым. Введите ваше имя:")
        return
    with bot.retrieve_data(msg.from_user.id, msg.chat.id) as data:
        data['order_name'] = name
    bot.set_state(msg.from_user.id, ContactForm.waiting_for_phone, msg.chat.id)
    bot.send_message(msg.chat.id, "Отлично! Теперь пришлите телефон (например +79161234567):")

@bot.message_handler(state=ContactForm.waiting_for_phone, content_types=['text'])
def process_phone(msg):
    phone = msg.text.strip()
    # Простая валидация: разрешаем цифры, пробелы, +, -, скобки; проверим длину цифр
    digits = "".join([c for c in phone if c.isdigit()])
    if len(digits) < 6:
        bot.send_message(msg.chat.id, "Похоже, это не телефон. Введите корректный номер (минимум 6 цифр):")
        return

    user_id = msg.from_user.id
    # Собираем данные и отправляем администратору
    selection = user_selections.get(user_id, {})
    selected_bike = selection.get("bike", "Неизвестная модель")
    frame_size = selection.get("frame_size", "Не выбран")
    height_range = selection.get("height_range", "")

    with bot.retrieve_data(msg.from_user.id, msg.chat.id) as data:
        name = data.get('order_name', msg.from_user.first_name or "Не указано")

    admin_message = (
        f"📩 Новая заявка:\n\n"
        f"👤 Имя: {name}\n"
        f"🆔 ID: {user_id}\n"
        f"🚲 Модель: {selected_bike}\n"
        f"📏 Размер рамы: {frame_size} ({height_range})\n"
        f"📞 Контакты: {phone}"
    )
    try:
        bot.send_message(ADMIN_ID, admin_message)
    except Exception as e:
        logger.warning("Не удалось отправить заявку администратору: %s", e)

    bot.send_message(msg.chat.id, "Спасибо! Мы свяжемся с тобой в ближайшее время!")
    # очищаем выбор
    if user_id in user_selections:
        del user_selections[user_id]
    bot.delete_state(msg.from_user.id, msg.chat.id)

# ----------------- ОБРАБОТКА ВСЕХ СООБЩЕНИЙ: трекинг активности -----------------
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'sticker', 'video', 'voice'])
def track_all_messages(msg):
    try:
        update_user_activity_db(msg.from_user.id)
    except Exception as e:
        logger.warning("Ошибка при обновлении активности: %s", e)
    # Не мешаем основному UX — обработчики выше отрабатывают как нужно

# ----------------- СТАРТ -----------------
if __name__ == "__main__":
    print("🤖 Запуск бота...")
    print(f"🔑 ADMIN_ID: {ADMIN_ID}")
    print(f"📁 DB: {DB_FILE}")
    initial_users = get_all_users_db()
    print(f"📊 Начальное количество пользователей: {len(initial_users)}")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("Остановлено вручную")
    except Exception as e:
        logger.exception("Критическая ошибка при запуске polling: %s", e)
