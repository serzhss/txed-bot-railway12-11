import os
import logging
import json
import datetime
import time
import sqlite3
from telebot import TeleBot, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from flask import Flask, request

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
print("🔧 Начало инициализации бота...")

# ОТЛАДКА: Выведем все переменные окружения
print("🔍 Все переменные окружения:")
for key, value in os.environ.items():
    if 'BOT' in key.upper() or 'TOKEN' in key.upper() or 'ADMIN' in key.upper():
        print(f" {key}: {value}")

# Используем переменные окружения (без fallback для безопасности)
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None
print(f"🔧 Используемый токен: {'✅ Установлен' if TOKEN else '❌ НЕТ'}")
print(f"🔧 Админ ID: {ADMIN_ID}")

if not TOKEN or not ADMIN_ID:
    print("❌ Токен или ADMIN_ID не установлены. Завершение.")
    exit(1)

try:
    # Инициализация бота
    storage = StateMemoryStorage()
    bot = TeleBot(TOKEN, state_storage=storage)
    print("✅ Бот инициализирован")
except Exception as e:
    print(f"❌ Ошибка инициализации бота: {e}")
    exit(1)

# Инициализация БД
DB_FILE = "users.db"

def ensure_users_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            first_seen TEXT,
            last_activity TEXT,
            messages_count INTEGER
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✅ База данных {DB_FILE} готова")

# Вызываем при старте
ensure_users_db()

# ======== СИСТЕМА ХРАНЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ========
def load_users():
    """Загружает пользователей из БД"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        rows = cursor.fetchall()
        users = {}
        for row in rows:
            users[row[0]] = {
                'username': row[1],
                'first_name': row[2],
                'last_name': row[3],
                'full_name': row[4],
                'first_seen': row[5],
                'last_activity': row[6],
                'messages_count': row[7]
            }
        conn.close()
        print(f"📥 Загружено {len(users)} пользователей")
        return users
    except Exception as e:
        print(f"❌ Ошибка загрузки пользователей: {e}")
        return {}

def save_users(users):
    """Сохраняет пользователей в БД"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        for user_id, data in users.items():
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, full_name, first_seen, last_activity, messages_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                data.get('username'),
                data.get('first_name'),
                data.get('last_name'),
                data.get('full_name'),
                data.get('first_seen'),
                data.get('last_activity'),
                data.get('messages_count')
            ))
        conn.commit()
        conn.close()
        print(f"💾 Сохранено {len(users)} пользователей")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения пользователей: {e}")
        return False

def add_user(user_id, username, first_name, last_name):
    """Добавляет/обновляет пользователя"""
    try:
        users = load_users()
        current_time = datetime.datetime.now().isoformat()
       
        user_key = str(user_id)
        if user_key in users:
            # Обновляем существующего пользователя
            users[user_key].update({
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'full_name': f"{first_name} {last_name or ''}".strip(),
                'last_activity': current_time,
                'messages_count': users[user_key].get('messages_count', 0) + 1
            })
            print(f"📝 Обновлен пользователь {user_id}")
        else:
            # Добавляем нового пользователя
            users[user_key] = {
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'full_name': f"{first_name} {last_name or ''}".strip(),
                'first_seen': current_time,
                'last_activity': current_time,
                'messages_count': 1
            }
            print(f"✅ Добавлен новый пользователь {user_id}")
       
        if save_users(users):
            print(f"📊 Всего пользователей: {len(users)}")
        else:
            print("❌ Ошибка сохранения пользователя")
           
    except Exception as e:
        print(f"❌ Ошибка добавления пользователя {user_id}: {e}")

def get_all_users():
    """Возвращает всех пользователей"""
    users = load_users()
    print(f"📋 Запрошены все пользователи, найдено: {len(users)}")
    return users

def update_user_activity(user_id):
    """Обновляет время последней активности пользователя"""
    try:
        users = load_users()
        user_key = str(user_id)
        if user_key in users:
            users[user_key]['last_activity'] = datetime.datetime.now().isoformat()
            users[user_key]['messages_count'] = users[user_key].get('messages_count', 0) + 1
            save_users(users)
            print(f"🔄 Обновлена активность пользователя {user_id}")
        else:
            # Если пользователя нет, добавляем его с базовой информацией
            print(f"⚠️ Пользователь {user_id} не найден при обновлении активности")
            add_user(user_id, None, None, None)  # Добавляем с минимальными данными
    except Exception as e:
        print(f"❌ Ошибка обновления активности пользователя {user_id}: {e}")

# ======== FSM STATES ========
class ContactForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()

class AdminForm(StatesGroup):
    waiting_for_broadcast_message = State()

# Словарь для отслеживания текущего фото для каждого пользователя
user_photo_index = {}

# ======== КАТАЛОГ ========
bikes = {
    "PRIMO": {
        "description": "🚴‍♂️ <b>PRIMO</b>\n\nМаневренная, универсальная модель для активного фанового катания в холмистой местности.\n\nБазовый уровень линейки — для зрелых любителей качества и современных тенденций велостроения.\n\nРозничная цена 50 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild6336-3032-4434-b935-346363326131/-/format/webp/Photo-70.webp",
            "https://optim.tildacdn.com/tild6536-6564-4661-b563-323737643733/-/format/webp/Photo-45.webp",
            "https://optim.tildacdn.com/tild6263-6233-4537-a436-633033386132/-/format/webp/Photo-47.webp",
            "https://optim.tildacdn.com/tild3731-3531-4463-b933-386135363632/-/format/webp/Photo-48.webp",
            "https://optim.tildacdn.com/tild3038-3263-4935-a533-326637363030/-/format/webp/Photo-49.webp",
            "https://optim.tildacdn.com/tild3831-3637-4836-b836-363934653638/-/format/webp/Photo-50.webp",
            "https://optim.tildacdn.com/tild6665-3839-4632-a663-613133313564/-/format/webp/Photo-55.webp",
            "https://optim.tildacdn.com/tild3734-6433-4835-b639-623036366165/-/format/webp/Photo-57.webp"
        ],
        "specs": {
            "Вилка": "UDING DS HLO",
            "Передний переключатель": "SHIMANO ALTUS M315",
            "Задний переключатель": "SHIMANO ALTUS M310",
            "Шифтеры": "SHIMANO ALTUS M315 2x8s",
            "Тормоза": "SHIMANO MT 200",
            "Кассета": "SHIMANO CS-HG-41-8 11-34T",
            "Цепь": "TEC C8 16S",
            "Система": "PROWHEEL CY-10TM",
            "Картридж": "GINEYEA BB73 68mm",
            "Ротор": "SHIMANO RT-26S 160мм",
            "Втулки": "SOLON 901F/R AL",
            "Обода": "HENGTONG HLQC-GA10",
            "Покрышки": "KENDA K1162",
            "Руль": "ZOOM MTB AL 31,8 720/760мм",
            "Вынос": "ZOOM TDS-C301",
            "Грипсы": "VELO VLG-609",
            "Рулевая колонка": "GINEYEA GH-830",
            "Седло": "VELO VL-3534",
            "Подседельный штырь": "ZOOM SP-C212",
            "Педали": "FENGDE NW-430"
        }
    },
    "TERZO": {
        "description": "🚴‍♂️ <b>TERZO</b>\n\nНа треть эффективнее аналогов в этой нише.\nОтличное решение для тех, кто перерос прогулочный байк и готов для большего.\n\nРозничная цена 65 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild3531-3036-4463-b536-303235326633/-/format/webp/Photo-71.webp"
        ],
        "specs": {
            "Вилка": "UDING DS HLO",
            "Передний переключатель": "-",
            "Задний переключатель": "SHIMANO CUES 9S",
            "Шифтеры": "SHIMANO CUES 9S",
            "Тормоза": "SHIMANO MT 200",
            "Кассета": "SHIMANO CUES 11-41T 9S",
            "Цепь": "SHIMANO LG500",
            "Система": "PROWHEEL C10YNW-32T",
            "Картридж": "GINEYEA BB73 68mm",
            "Ротор": "SHIMANO RT-26M 180мм",
            "Втулки": "SOLON 901F/R AL",
            "Обода": "HENGTONG HLGC-GA10",
            "Покрышки": "KENDA K1162",
            "Руль": "ZOOM MTB AL 31,8 740/760мм",
            "Вынос": "ZOOM TDS-RD301",
            "Грипсы": "VELO VLG-609",
            "Рулевая колонка": "GINEYEA GH-830",
            "Седло": "VELO VL-3534",
            "Подседельный штырь": "ZOOM SP-C212",
            "Педали": "FENGDE NW-430"
        }
    },
    "ULTIMO": {
        "description": "🚴‍♂️ <b>ULTIMO</b>\n\nТоповый в линейке middle-сегмента трейловых велосипедов для прогрессирующих райдеров.\nПредназначен для гонок и катания на пересечённой местности со средним или существенным перепадом высот.\n\nРозничная цена 75 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild3637-6439-4237-b638-303336613863/-/format/webp/Photo-69.webp"
        ],
        "specs": {
            "Вилка": "UDING DS HLO",
            "Передний переключатель": "-",
            "Задний переключатель": "SHIMANO CUES 10S",
            "Шифтеры": "SHIMANO CUES 10S",
            "Тормоза": "SHIMANO MT 200",
            "Кассета": "SHIMANO CUES CS-LG400 11-48T 10S",
            "Цепь": "SHIMANO LG500",
            "Система": "PROWHEEL RMZ 32T",
            "Картридж": "PROWHEEL PW-MBB73 HOLOWTECH 2",
            "Ротор": "SHIMANO RT-26M 180мм",
            "Втулки": "SOLON 901F/R AL",
            "Обода": "HENGTONG HLGC-GA10",
            "Покрышки": "OBOR W3104",
            "Руль": "ZOOM MTB AL 31,8 740/760мм",
            "Вынос": "ZOOM TDS-C301",
            "Грипсы": "VELO VLG-609",
            "Рулевая колонка": "GINEYEA GH-830",
            "Седло": "VELO VL-3534",
            "Подседельный штырь": "ZOOM SP-C212",
            "Педали": "FENGDE NW-430"
        }
    },
    "TESORO": {
        "description": "🚴‍♂️ <b>TESORO</b>\n\nСбалансированный аппарат для катания в горах и холмистой местности, для техничных трасс с прыжками и виражами.\n\nРозничная цена 85 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild3932-3166-4537-b837-386365666162/-/format/webp/Photo-72.webp"
        ],
        "specs": {
            "Вилка": "ZOOM 868 AIR BOOST",
            "Передний переключатель": "-",
            "Задний переключатель": "SHIMANO CUES 115",
            "Шифтеры": "SHIMANO CUES 115",
            "Тормоза": "SHIMANO MT 200",
            "Кассета": "SHIMANO CUES CS-LG400 11-50T 11S",
            "Цепь": "SHIMANO LG500",
            "Система": "PROWHEEL RMZ 32T",
            "Картридж": "PROWHEEL PW-MB73 HOLOWITECH 2",
            "Ротор": "SHIMANO RT-26M 180мм",
            "Втулки": "SOLON 9081F/TR AL",
            "Обода": "ПИСТОНИРОВАННЫЙ STAR 32H",
            "Покрышки": "OBOR W3104",
            "Руль": "ZOOM MTB AL 31,8 740/760мм",
            "Вынос": "ZOOM TDS-RD307A",
            "Грипсы": "VELO VLG-609",
            "Рулевая колонка": "GINEYEA GH-830",
            "Седло": "VELO VLG-609",
            "Подседельный штырь": "ZOOM SP218",
            "Педали": "FENGDE NW-430"
        }
    },
    "OTTIMO": {
        "description": "🚴‍♂️ <b>OTTIMO</b>\n\nНа этом байке реально проехать кросс-кантрийный марафон, уверенно проходить сложные участки и крутые спуски.\nПозволяет чувствовать себя на равных с мировыми брендами в соревнованиях.\n\nРозничная цена 95 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild3662-3335-4362-a665-303137396364/-/format/webp/Photo-73.webp"
        ],
        "specs": {
            "Вилка": "ROCK SHOX FS RECON 29F",
            "Передний переключатель": "-",
            "Задний переключатель": "SHIMANO CUES 11S",
            "Шифтеры": "SHIMANO CUES 11S",
            "Тормоза": "SHIMANO MT 200",
            "Кассета": "SHIMANO CUES CS-LG400 11-50T 11S",
            "Цепь": "SHIMANO LG500",
            "Система": "SHIMANO CUES FC-U6000-1",
            "Картридж": "SHIMANO BB-M501 HOLOWTECH 2",
            "Ротор": "SHIMANO RT-26M 180мм",
            "Втулки": "SOLON 908TF/TR AL",
            "Обода": "ПИСТОНИРОВАННЫЙ STAR 32H",
            "Покрышки": "MAXXIS RECON M355",
            "Руль": "ZOOM MTB AL 31,8 740/760мм",
            "Вынос": "ZOOM TDS-D479",
            "Грипсы": "VELO VLG-1266-11D2",
            "Рулевая колонка": "GINEYEA GH-202",
            "Седло": "VELO 1C58",
            "Подседельный штырь": "ZOOM SP218"
        }
    }
}

# Размеры рам
frame_sizes = {
    "M (17\")": "163-177 см",
    "L (19\")": "173-187 см",
    "XL (21\")": "182-197 см"
}

# Словарь для хранения выбранных моделей и размеров пользователей
user_selections = {}

# ======== АДМИН ПАНЕЛЬ ========
@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.send_message(msg.chat.id, "⛔ У вас нет доступа к админ-панели")
        return
   
    users = get_all_users()
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
    users = get_all_users()
    total_users = len(users)
   
    # Статистика по активности
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
            print(f"Ошибка обработки даты активности: {e}")
            continue
   
    # Статистика по сообщениям
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
    users = get_all_users()
   
    if not users:
        bot.send_message(msg.chat.id, "📭 Пользователей пока нет")
        return
   
    # Сортируем по дате последней активности (новые сначала)
    sorted_users = []
    for user_id, user_data in users.items():
        try:
            last_activity_str = user_data.get('last_activity', '')
            if last_activity_str:
                last_activity = datetime.datetime.fromisoformat(last_activity_str)
                sorted_users.append((user_id, user_data, last_activity))
        except Exception as e:
            print(f"Ошибка сортировки пользователя {user_id}: {e}")
            continue
   
    sorted_users.sort(key=lambda x: x[2], reverse=True)
   
    # Показываем первых 10 пользователей
    users_list = "👥 <b>Последние пользователи:</b>\n\n"
    for i, (user_id, user_data, last_activity) in enumerate(sorted_users[:10], 1):
        try:
            first_seen_str = user_data.get('first_seen', '')
            first_seen = datetime.datetime.fromisoformat(first_seen_str).strftime('%d.%m.%Y') if first_seen_str else 'неизвестно'
            last_activity_str = last_activity.strftime('%d.%m.%Y %H:%M')
            messages_count = user_data.get('messages_count', 0)
            username = user_data.get('username', 'нет')
            full_name = user_data.get('full_name', 'Неизвестно')
           
            users_list += (
                f"{i}. {full_name}\n"
                f" 👤 @{username}\n"
                f" 🆔 {user_id}\n"
                f" 📅 Первый визит: {first_seen}\n"
                f" ⏰ Последняя активность: {last_activity_str}\n"
                f" 💬 Сообщений: {messages_count}\n\n"
            )
        except Exception as e:
            print(f"Ошибка форматирования пользователя {user_id}: {e}")
            continue
   
    if len(users) > 10:
        users_list += f"... и еще {len(users) - 10} пользователей"
   
    bot.send_message(msg.chat.id, users_list, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка" and m.from_user.id == ADMIN_ID)
def start_broadcast(msg):
    users = get_all_users()
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
    users = get_all_users()
    total_users = len(users)
   
    if total_users == 0:
        bot.send_message(msg.chat.id, "❌ Нет пользователей для рассылки")
        bot.delete_state(msg.from_user.id, msg.chat.id)
        return
   
    # Подтверждение рассылки
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Разослать", callback_data="confirm_broadcast"))
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast"))
   
    # Сохраняем сообщение для рассылки
    with bot.retrieve_data(msg.from_user.id, msg.chat.id) as data:
        data['broadcast_message'] = msg.text
   
    # Показываем превью сообщения
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
    users = get_all_users()
   
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        message_text = data.get('broadcast_message', '')
   
    if not message_text:
        bot.answer_callback_query(call.id, "Ошибка: сообщение не найдено")
        return
   
    # Рассылка сообщения с задержками
    success_count = 0
    fail_count = 0
   
    bot.edit_message_text(
        "🔄 Рассылка начата...\n\n⏳ Это может занять несколько минут",
        call.message.chat.id,
        call.message.message_id
    )
   
    # Рассылка с задержками для обхода ограничений
    for i, user_id in enumerate(users.keys()):
        try:
            # Отправляем сообщение
            bot.send_message(int(user_id), message_text)
            success_count += 1
           
            # Задержка каждые 10 сообщений
            if (i + 1) % 10 == 0:
                time.sleep(1)
               
        except Exception as e:
            fail_count += 1
            print(f"Ошибка отправки пользователю {user_id}: {e}")
   
    # Результат рассылки
    result_text = (
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Не удалось: {fail_count}\n"
        f"👥 Всего: {len(users)}"
    )
   
    bot.edit_message_text(
        result_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML"
    )
   
    bot.delete_state(call.from_user.id, call.message.chat.id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_broadcast")
def cancel_broadcast(call):
    bot.delete_state(call.from_user.id, call.message.chat.id)
    bot.edit_message_text(
        "❌ Рассылка отменена",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.text == "⬅️ Выйти из админки" and m.from_user.id == ADMIN_ID)
def exit_admin(msg):
    # Возвращаем обычную клавиатуру
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Каталог 🚲"))
    kb.add(types.KeyboardButton("Позвать специалиста 👨‍💼"))
    kb.add(types.KeyboardButton("О нас ℹ️"))
   
    bot.send_message(msg.chat.id, "✅ Вы вышли из админ-панели", reply_markup=kb)

# ======== ОСНОВНЫЕ ФУНКЦИИ БОТА ========
@bot.message_handler(commands=['start'])
def start(msg):
    # Сохраняем пользователя при старте
    add_user(
        msg.from_user.id,
        msg.from_user.username,
        msg.from_user.first_name,
        msg.from_user.last_name
    )
   
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Каталог 🚲"))
    kb.add(types.KeyboardButton("Позвать специалиста 👨‍💼"))
    kb.add(types.KeyboardButton("О нас ℹ️"))
   
    welcome_text = "👋 Добро пожаловать!\n\nЯ помогу вам выбрать идеальный велосипед 🚴‍♂️\n\nВыберите действие из меню ниже:"
    bot.send_message(msg.chat.id, welcome_text, reply_markup=kb)

# ======== СПЕЦИАЛИСТ ========
@bot.message_handler(func=lambda m: m.text and "специалиста" in m.text.lower())
def call_specialist(msg):
    # Сохраняем активность
    update_user_activity(msg.from_user.id)
   
    bot.send_message(msg.chat.id, "Отлично! Я уведомил специалиста. С вами свяжутся в ближайшее время! ☎️")
    specialist_message = f"👨‍💼 ЗАПРОС СПЕЦИАЛИСТА\n\nПользователь: {msg.from_user.first_name} {msg.from_user.last_name or ''}\nID: {msg.from_user.id}\nUsername: @{msg.from_user.username or 'не указан'}"
    bot.send_message(ADMIN_ID, specialist_message)

# ======== КАТАЛОГ ========
@bot.message_handler(func=lambda m: m.text and "Каталог" in m.text)
def catalog(msg):
    # Сохраняем активность
    update_user_activity(msg.from_user.id)
   
    kb = types.InlineKeyboardMarkup()
    for bike in bikes:
        kb.add(types.InlineKeyboardButton(bike, callback_data=bike))
    bot.send_message(msg.chat.id, "Выбери модель:", reply_markup=kb)

# ======== ПОКАЗ МОДЕЛИ С НАВИГАЦИЕЙ ПО ФОТО ========
@bot.callback_query_handler(func=lambda call: call.data in bikes)
def show_bike(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    name = call.data
    bike_data = bikes[name]
    # Устанавливаем начальный индекс фото для пользователя
    user_photo_index[call.from_user.id] = {
        'bike': name,
        'index': 0
    }
    # Показываем первое фото
    show_photo(call.message, call.from_user.id, name, 0)
    bot.answer_callback_query(call.id)

def show_photo(message, user_id, bike_name, photo_index):
    bike_data = bikes[bike_name]
    photos = bike_data["photos"]
    # Создаем клавиатуру навигации
    kb = types.InlineKeyboardMarkup()
    # Кнопки навигации если фото больше одного
    if len(photos) > 1:
        row = []
        if photo_index > 0:
            row.append(types.InlineKeyboardButton("⬅️", callback_data=f"prev_photo_{bike_name}"))
        row.append(types.InlineKeyboardButton(f"{photo_index + 1}/{len(photos)}", callback_data="photo_counter"))
        if photo_index < len(photos) - 1:
            row.append(types.InlineKeyboardButton("➡️", callback_data=f"next_photo_{bike_name}"))
        kb.row(*row)
    # Основные кнопки
    kb.add(types.InlineKeyboardButton("📋 Спецификация", callback_data=f"specs_{bike_name}"))
    kb.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{bike_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад в каталог", callback_data="back_to_catalog"))
    # Текст для фото
    caption = bike_data["description"] if photo_index == 0 else f"Фото {photo_index + 1} из {len(photos)}"
    # Отправляем фото
    bot.send_photo(
        message.chat.id,
        photos[photo_index],
        caption=caption,
        reply_markup=kb,
        parse_mode="HTML"
    )

# ======== НАВИГАЦИЯ ПО ФОТО ========
@bot.callback_query_handler(func=lambda call: call.data.startswith(("prev_photo_", "next_photo_")))
def navigate_photo(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    user_id = call.from_user.id
    if user_id not in user_photo_index:
        bot.answer_callback_query(call.id, "Сессия устарела, начните заново")
        return
    current_data = user_photo_index[user_id]
    bike_name = current_data['bike']
    current_index = current_data['index']
    photos = bikes[bike_name]["photos"]
    # Определяем направление навигации
    if call.data.startswith("prev_photo_"):
        new_index = max(0, current_index - 1)
    else: # next_photo_
        new_index = min(len(photos) - 1, current_index + 1)
    # Обновляем индекс
    user_photo_index[user_id]['index'] = new_index
    # Удаляем старое сообщение и показываем новое фото
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    show_photo(call.message, user_id, bike_name, new_index)
    bot.answer_callback_query(call.id)

# ======== СПЕЦИФИКАЦИЯ ========
@bot.callback_query_handler(func=lambda call: call.data.startswith("specs_"))
def show_specs(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    bike_name = call.data.replace("specs_", "")
    bike_data = bikes[bike_name]
    specs = bike_data["specs"]
    specs_text = f"🔧 <b>Спецификация {bike_name}</b>\n\n"
    for component, value in specs.items():
        specs_text += f"• <b>{component}:</b> {value}\n"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Назад к модели", callback_data=bike_name))
    kb.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{bike_name}"))
    bot.send_message(call.message.chat.id, specs_text, parse_mode="HTML", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ======== ВЫБОР РАЗМЕРА ========
@bot.callback_query_handler(func=lambda call: call.data.startswith("order_"))
def select_frame_size(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    bike_name = call.data.replace("order_", "")
    user_selections[call.from_user.id] = {"bike": bike_name}
    kb = types.InlineKeyboardMarkup()
    for size, height_range in frame_sizes.items():
        kb.add(types.InlineKeyboardButton(f"{size} ({height_range})", callback_data=f"size_{size}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад к модели", callback_data=bike_name))
    bot.send_message(call.message.chat.id, f"Вы выбрали {bike_name}! 🚴‍♂️\n\nТеперь выбери размер рамы:", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ======== СОХРАНЕНИЕ РАЗМЕРА ========
@bot.callback_query_handler(func=lambda call: call.data.startswith("size_"))
def save_frame_size(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    frame_size = call.data.replace("size_", "")
    height_range = frame_sizes.get(frame_size, "")
    user_id = call.from_user.id
    if user_id in user_selections:
        user_selections[user_id]["frame_size"] = frame_size
        user_selections[user_id]["height_range"] = height_range
    bike_name = user_selections[user_id]["bike"]
    bot.send_message(call.message.chat.id, f"Отлично! 🎯\nМодель: {bike_name}\nРазмер рамы: {frame_size} ({height_range})\n\nТеперь напиши своё имя и телефон:")
    bot.answer_callback_query(call.id)

# ======== ВОЗВРАТ К КАТАЛОГУ ========
@bot.callback_query_handler(func=lambda call: call.data == "back_to_catalog")
def back_to_catalog(call):
    # Сохраняем активность
    update_user_activity(call.from_user.id)
   
    kb = types.InlineKeyboardMarkup()
    for bike in bikes:
        kb.add(types.InlineKeyboardButton(bike, callback_data=bike))
    bot.send_message(call.message.chat.id, "Выбери модель:", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ======== ВОЗВРАТ К МОДЕЛИ ========
# Уже обработано в show_bike

# ======== О НАС ========
@bot.message_handler(func=lambda m: m.text and "О нас" in m.text)
def about(msg):
    # Сохраняем активность
    update_user_activity(msg.from_user.id)
   
    bot.send_message(
        msg.chat.id,
        """О нас | Официальный импортер TXED в России
Компания "СИБВЕЛО" рада представить себя как официального импортера бренда TXED в России. Мы гордимся тем, что предлагаем российским потребителям качественную продукцию с 40-летней историей.
🚴‍♂️ *Почему мы выбрали TXED?*
После тщательного анализа рынка мы остановились на бренде TXED благодаря его безупречной репутации в 50+ странах мира. Современное производство с европейскими стандартами качества.
📅 *Наш путь с брендом:*
• 2023 — начало переговоров о сотрудничестве
• 2024 — официальный старт продаж в России
• Сегодня — активное развитие дилерской сети
✅ *Что мы предлагаем:*
• Качественные велосипеды и E-bike по доступным ценам
• Полную техническую поддержку
• Гарантийное обслуживание на территории РФ
• Постоянное наличие запчастей на складах
🏆 *Наши преимущества:*
Прямые поставки с завода позволяют нам поддерживать конкурентные цены и обеспечивать стабильное наличие товара.
🌟 *Наша миссия:*
Сделать современные велосипеды и E-bike доступными для широкого круга российских потребителей.
🌐 *Сайт:* https://txedbikes.ru
📞 *Напишите нам* — ответим на все вопросы!
*С уважением,*
*Команда "СИБВЕЛО"*
*Официальный импортер TXED в России*""",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

# ======== ОБРАБОТКА ЗАКАЗОВ ========
@bot.message_handler(func=lambda m: any(x.isdigit() for x in m.text) and len(m.text) > 5)
def save_order(msg):
    # Сохраняем активность
    update_user_activity(msg.from_user.id)
   
    user_id = msg.from_user.id
    # Получаем данные пользователя
    user_data = user_selections.get(user_id, {})
    selected_bike = user_data.get("bike", "Неизвестная модель")
    frame_size = user_data.get("frame_size", "Не выбран")
    height_range = user_data.get("height_range", "")
    admin_message = f"📩 Новая заявка:\n\n👤 Пользователь: {msg.from_user.first_name} {msg.from_user.last_name or ''}\n🆔 ID: {user_id}\n🚲 Модель: {selected_bike}\n📏 Размер рамы: {frame_size} ({height_range})\n📞 Контакты: {msg.text}"
    bot.send_message(ADMIN_ID, admin_message)
    bot.send_message(msg.chat.id, "Спасибо! Мы свяжемся с тобой в ближайшее время!")
    if user_id in user_selections:
        del user_selections[user_id]

# ======== ОБРАБОТКА ВСЕХ СООБЩЕНИЙ ДЛЯ ТРЕКИНГА ========
@bot.message_handler(func=lambda m: True)
def track_all_messages(msg):
    """Отслеживает все сообщения для сохранения активности"""
    update_user_activity(msg.from_user.id)

# ======== ЗАПУСК С WEBHOOK ДЛЯ RAILWAY ========
app = Flask(__name__)

@app.route('/bot', methods=['POST'])
def webhook():
    update = types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == "__main__":
    print("🤖 Запуск бота...")
    print(f"🔑 Админ ID: {ADMIN_ID}")
    print(f"📁 База данных: {DB_FILE}")
   
    # Проверяем начальное состояние БД
    initial_users = get_all_users()
    print(f"📊 Начальное количество пользователей: {len(initial_users)}")
   
    print("🚀 Бот запущен!")
    print("💡 Для доступа к админ-панели отправьте: /admin")
    
    # Установка webhook
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Установите в env: https://your-app-name.up.railway.app/bot
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"✅ Webhook установлен: {WEBHOOK_URL}")
    else:
        print("❌ WEBHOOK_URL не установлен. Используйте polling для теста.")
        bot.infinity_polling()
    
    # Запуск Flask для webhook
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
