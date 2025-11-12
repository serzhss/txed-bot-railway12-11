import os
import logging
import datetime
import time
import sqlite3
from telebot import TeleBot, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateRedisStorage  # <-- Redis!
from flask import Flask, request

# Настройка логирования
logging.basicConfig(level=logging.INFO)
print("Начало инициализации бота...")

# Переменные окружения
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None
REDIS_URL = os.getenv("REDIS_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

print(f"Токен: {'Да' if TOKEN else 'НЕТ'}")
print(f"Админ ID: {ADMIN_ID}")
print(f"Redis: {'Да' if REDIS_URL else 'НЕТ'}")
print(f"Webhook: {WEBHOOK_URL}")

if not TOKEN or not ADMIN_ID or not REDIS_URL:
    print("ОШИБКА: Проверьте BOT_TOKEN, ADMIN_ID, REDIS_URL")
    exit(1)

try:
    storage = StateRedisStorage(url=REDIS_URL)
    bot = TeleBot(TOKEN, state_storage=storage)
    print("Бот инициализирован с Redis")
except Exception as e:
    print(f"Ошибка бота: {e}")
    exit(1)

# База данных
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
    print(f"БД {DB_FILE} готова")
ensure_users_db()

# === ПОЛЬЗОВАТЕЛИ ===
def load_users():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        rows = cursor.fetchall()
        users = {}
        for row in rows:
            users[row[0]] = {
                'username': row[1], 'first_name': row[2], 'last_name': row[3],
                'full_name': row[4], 'first_seen': row[5], 'last_activity': row[6],
                'messages_count': row[7]
            }
        conn.close()
        return users
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return {}

def save_users(users):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        for uid, data in users.items():
            cursor.execute('''
                INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (uid, data.get('username'), data.get('first_name'), data.get('last_name'),
                  data.get('full_name'), data.get('first_seen'), data.get('last_activity'),
                  data.get('messages_count')))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return False

def add_user(user_id, username, first_name, last_name):
    users = load_users()
    now = datetime.datetime.now().isoformat()
    uid = str(user_id)
    if uid in users:
        users[uid].update({
            'username': username, 'first_name': first_name, 'last_name': last_name,
            'full_name': f"{first_name} {last_name or ''}".strip(),
            'last_activity': now, 'messages_count': users[uid].get('messages_count', 0) + 1
        })
    else:
        users[uid] = {
            'username': username, 'first_name': first_name, 'last_name': last_name,
            'full_name': f"{first_name} {last_name or ''}".strip(),
            'first_seen': now, 'last_activity': now, 'messages_count': 1
        }
    save_users(users)

def get_all_users():
    return load_users()

def update_user_activity(user_id):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]['last_activity'] = datetime.datetime.now().isoformat()
        users[uid]['messages_count'] = users[uid].get('messages_count', 0) + 1
        save_users(users)
    else:
        add_user(user_id, None, None, None)

# === FSM ===
class AdminForm(StatesGroup):
    waiting_for_broadcast_message = State()

user_photo_index = {}
user_selections = {}

# === КАТАЛОГ ===
bikes = {
    "PRIMO": {
        "description": "<b>PRIMO</b>\n\nМаневренная, универсальная модель для активного фанового катания в холмистой местности.\n\nБазовый уровень линейки — для зрелых любителей качества и современных тенденций велостроения.\n\nРозничная цена 50 000 руб.",
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
        "description": "<b>TERZO</b>\n\nНа треть эффективнее аналогов в этой нише.\nОтличное решение для тех, кто перерос прогулочный байк и готов для большего.\n\nРозничная цена 65 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3531-3036-4463-b536-303235326633/-/format/webp/Photo-71.webp"],
        "specs": {
            "Вилка": "UDING DS HLO", "Передний переключатель": "-", "Задний переключатель": "SHIMANO CUES 9S",
            "Шифтеры": "SHIMANO CUES 9S", "Тормоза": "SHIMANO MT 200", "Кассета": "SHIMANO CUES 11-41T 9S",
            "Цепь": "SHIMANO LG500", "Система": "PROWHEEL C10YNW-32T", "Картридж": "GINEYEA BB73 68mm",
            "Ротор": "SHIMANO RT-26M 180мм", "Втулки": "SOLON 901F/R AL", "Обода": "HENGTONG HLGC-GA10",
            "Покрышки": "KENDA K1162", "Руль": "ZOOM MTB AL 31,8 740/760мм", "Вынос": "ZOOM TDS-RD301",
            "Грипсы": "VELO VLG-609", "Рулевая колонка": "GINEYEA GH-830", "Седло": "VELO VL-3534",
            "Подседельный штырь": "ZOOM SP-C212", "Педали": "FENGDE NW-430"
        }
    },
    "ULTIMO": {
        "description": "<b>ULTIMO</b>\n\nТоповый в линейке middle-сегмента трейловых велосипедов для прогрессирующих райдеров.\nПредназначен для гонок и катания на пересечённой местности со средним или существенным перепадом высот.\n\nРозничная цена 75 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3637-6439-4237-b638-303336613863/-/format/webp/Photo-69.webp"],
        "specs": {
            "Вилка": "UDING DS HLO", "Передний переключатель": "-", "Задний переключатель": "SHIMANO CUES 10S",
            "Шифтеры": "SHIMANO CUES 10S", "Тормоза": "SHIMANO MT 200", "Кассета": "SHIMANO CUES CS-LG400 11-48T 10S",
            "Цепь": "SHIMANO LG500", "Система": "PROWHEEL RMZ 32T", "Картридж": "PROWHEEL PW-MBB73 HOLOWTECH 2",
            "Ротор": "SHIMANO RT-26M 180мм", "Втулки": "SOLON 901F/R AL", "Обода": "HENGTONG HLGC-GA10",
            "Покрышки": "OBOR W3104", "Руль": "ZOOM MTB AL 31,8 740/760мм", "Вынос": "ZOOM TDS-C301",
            "Грипсы": "VELO VLG-609", "Рулевая колонка": "GINEYEA GH-830", "Седло": "VELO VL-3534",
            "Подседельный штырь": "ZOOM SP-C212", "Педали": "FENGDE NW-430"
        }
    },
    "TESORO": {
        "description": "<b>TESORO</b>\n\nСбалансированный аппарат для катания в горах и холмистой местности, для техничных трасс с прыжками и виражами.\n\nРозничная цена 85 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3932-3166-4537-b837-386365666162/-/format/webp/Photo-72.webp"],
        "specs": {
            "Вилка": "ZOOM 868 AIR BOOST", "Передний переключатель": "-", "Задний переключатель": "SHIMANO CUES 115",
            "Шифтеры": "SHIMANO CUES 115", "Тормоза": "SHIMANO MT 200", "Кассета": "SHIMANO CUES CS-LG400 11-50T 11S",
            "Цепь": "SHIMANO LG500", "Система": "PROWHEEL RMZ 32T", "Картридж": "PROWHEEL PW-MB73 HOLOWITECH 2",
            "Ротор": "SHIMANO RT-26M 180мм", "Втулки": "SOLON 9081F/TR AL", "Обода": "ПИСТОНИРОВАННЫЙ STAR 32H",
            "Покрышки": "OBOR W3104", "Руль": "ZOOM MTB AL 31,8 740/760мм", "Вынос": "ZOOM TDS-RD307A",
            "Грипсы": "VELO VLG-609", "Рулевая колонка": "GINEYEA GH-830", "Седло": "VELO VLG-609",
            "Подседельный штырь": "ZOOM SP218", "Педали": "FENGDE NW-430"
        }
    },
    "OTTIMO": {
        "description": "<b>OTTIMO</b>\n\nНа этом байке реально проехать кросс-кантрийный марафон, уверенно проходить сложные участки и крутые спуски.\nПозволяет чувствовать себя на равных с мировыми брендами в соревнованиях.\n\nРозничная цена 95 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3662-3335-4362-a665-303137396364/-/format/webp/Photo-73.webp"],
        "specs": {
            "Вилка": "ROCK SHOX FS RECON 29F", "Передний переключатель": "-", "Задний переключатель": "SHIMANO CUES 11S",
            "Шифтеры": "SHIMANO CUES 11S", "Тормоза": "SHIMANO MT 200", "Кассета": "SHIMANO CUES CS-LG400 11-50T 11S",
            "Цепь": "SHIMANO LG500", "Система": "SHIMANO CUES FC-U6000-1", "Картридж": "SHIMANO BB-M501 HOLOWTECH 2",
            "Ротор": "SHIMANO RT-26M 180мм", "Втулки": "SOLON 908TF/TR AL", "Обода": "ПИСТОНИРОВАННЫЙ STAR 32H",
            "Покрышки": "MAXXIS RECON M355", "Руль": "ZOOM MTB AL 31,8 740/760мм", "Вынос": "ZOOM TDS-D479",
            "Грипсы": "VELO VLG-1266-11D2", "Рулевая колонка": "GINEYEA GH-202", "Седло": "VELO 1C58",
            "Подседельный штырь": "ZOOM SP218"
        }
    }
}

frame_sizes = {"M (17\")": "163-177 см", "L (19\")": "173-187 см", "XL (21\")": "182-197 см"}

# === АДМИНКА ===
@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.send_message(msg.chat.id, "Нет доступа")
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Статистика", "Рассылка", "Список пользователей", "Выйти из админки")
    bot.send_message(msg.chat.id, f"<b>Админ-панель</b>\nПользователей: {len(get_all_users())}", parse_mode="HTML", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "Статистика" and m.from_user.id == ADMIN_ID)
def show_stats(msg):
    users = get_all_users()
    today = datetime.datetime.now().date()
    active_today = sum(1 for u in users.values() if u.get('last_activity') and datetime.datetime.fromisoformat(u['last_activity']).date() == today)
    total_messages = sum(u.get('messages_count', 0) for u in users.values())
    bot.send_message(msg.chat.id, f"<b>Статистика</b>\nВсего: {len(users)}\nСегодня: {active_today}\nСообщений: {total_messages}", parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "Рассылка" and m.from_user.id == ADMIN_ID)
def start_broadcast(msg):
    total = len(get_all_users())
    if total == 0:
        bot.send_message(msg.chat.id, "Нет пользователей")
        return
    bot.send_message(msg.chat.id, f"<b>Рассылка</b>\nПолучателей: {total}\n\nНапишите сообщение:", parse_mode="HTML")
    bot.set_state(msg.from_user.id, AdminForm.waiting_for_broadcast_message, msg.chat.id)

@bot.message_handler(state=AdminForm.waiting_for_broadcast_message, content_types=['text'])
def process_broadcast_message(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Разослать", callback_data="confirm_broadcast"))
    kb.add(types.InlineKeyboardButton("Отмена", callback_data="cancel_broadcast"))
    with bot.retrieve_data(msg.from_user.id, msg.chat.id) as data:
        data['broadcast_message'] = msg.text
    preview = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text
    bot.send_message(msg.chat.id, f"<b>Подтверждение</b>\n\n{preview}\n\nПолучателей: {len(get_all_users())}", parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_broadcast")
def confirm_broadcast(call):
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        text = data.get('broadcast_message', '')
    if not text:
        bot.answer_callback_query(call.id, "Ошибка")
        return
    users = get_all_users()
    success = 0
    bot.edit_message_text("Рассылка начата...", call.message.chat.id, call.message.message_id)
    for i, uid in enumerate(users.keys()):
        try:
            bot.send_message(int(uid), text)
            success += 1
            if (i + 1) % 10 == 0:
                time.sleep(1)
        except:
            pass
    bot.edit_message_text(f"<b>Готово</b>\nУспешно: {success}\nВсего: {len(users)}", call.message.chat.id, call.message.message_id, parse_mode="HTML")
    bot.delete_state(call.from_user.id, call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_broadcast")
def cancel_broadcast(call):
    bot.delete_state(call.from_user.id, call.message.chat.id)
    bot.edit_message_text("Отменено", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text == "Выйти из админки" and m.from_user.id == ADMIN_ID)
def exit_admin(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Каталог", "Позвать специалиста", "О нас")
    bot.send_message(msg.chat.id, "Вышли из админки", reply_markup=kb)

# === ОСНОВНОЕ ===
@bot.message_handler(commands=['start'])
def start(msg):
    add_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Каталог", "Позвать специалиста", "О нас")
    bot.send_message(msg.chat.id, "Привет! Выберите действие:", reply_markup=kb)

@bot.message_handler(func=lambda m: "специалиста" in m.text.lower())
def call_specialist(msg):
    update_user_activity(msg.from_user.id)
    bot.send_message(msg.chat.id, "Специалист свяжется с вами!")
    bot.send_message(ADMIN_ID, f"Запрос от @{msg.from_user.username or 'нет'} ({msg.from_user.id})")

@bot.message_handler(func=lambda m: "Каталог" in m.text)
def catalog(msg):
    update_user_activity(msg.from_user.id)
    kb = types.InlineKeyboardMarkup()
    for bike in bikes:
        kb.add(types.InlineKeyboardButton(bike, callback_data=bike))
    bot.send_message(msg.chat.id, "Выберите модель:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data in bikes)
def show_bike(call):
    update_user_activity(call.from_user.id)
    name = call.data
    user_photo_index[call.from_user.id] = {'bike': name, 'index': 0}
    show_photo(call.message, call.from_user.id, name, 0)
    bot.answer_callback_query(call.id)

def show_photo(message, user_id, bike_name, idx):
    bike = bikes[bike_name]
    photos = bike["photos"]
    kb = types.InlineKeyboardMarkup()
    if len(photos) > 1:
        row = []
        if idx > 0:
            row.append(types.InlineKeyboardButton("Пред", callback_data=f"prev_photo_{bike_name}"))
        row.append(types.InlineKeyboardButton(f"{idx+1}/{len(photos)}", callback_data="ignore"))
        if idx < len(photos) - 1:
            row.append(types.InlineKeyboardButton("След", callback_data=f"next_photo_{bike_name}"))
        kb.row(*row)
    kb.add(types.InlineKeyboardButton("Спецификация", callback_data=f"specs_{bike_name}"))
    kb.add(types.InlineKeyboardButton("Заказать", callback_data=f"order_{bike_name}"))
    kb.add(types.InlineKeyboardButton("Назад", callback_data="back_to_catalog"))
    caption = bike["description"] if idx == 0 else f"Фото {idx+1}"
    bot.send_photo(message.chat.id, photos[idx], caption=caption, reply_markup=kb, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("prev_photo_", "next_photo_")))
def navigate_photo(call):
    update_user_activity(call.from_user.id)
    uid = call.from_user.id
    if uid not in user_photo_index:
        return
    data = user_photo_index[uid]
    bike = data['bike']
    idx = data['index']
    if call.data.startswith("prev"):
        idx = max(0, idx - 1)
    else:
        idx = min(len(bikes[bike]["photos"]) - 1, idx + 1)
    user_photo_index[uid]['index'] = idx
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    show_photo(call.message, uid, bike, idx)

@bot.callback_query_handler(func=lambda call: call.data.startswith("specs_"))
def show_specs(call):
    update_user_activity(call.from_user.id)
    name = call.data.replace("specs_", "")
    specs = bikes[name]["specs"]
    text = f"<b>Спецификация {name}</b>\n\n"
    for k, v in specs.items():
        text += f"• <b>{k}:</b> {v}\n"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Назад", callback_data=name))
    bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("order_"))
def select_size(call):
    update_user_activity(call.from_user.id)
    name = call.data.replace("order_", "")
    user_selections[call.from_user.id] = {"bike": name}
    kb = types.InlineKeyboardMarkup()
    for size, h in frame_sizes.items():
        kb.add(types.InlineKeyboardButton(f"{size} ({h})", callback_data=f"size_{size}"))
    kb.add(types.InlineKeyboardButton("Назад", callback_data=name))
    bot.send_message(call.message.chat.id, f"Выбрано: {name}\n\nВыберите размер:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("size_"))
def save_size(call):
    update_user_activity(call.from_user.id)
    size = call.data.replace("size_", "")
    uid = call.from_user.id
    user_selections[uid]["frame_size"] = size
    user_selections[uid]["height_range"] = frame_sizes[size]
    bot.send_message(call.message.chat.id, f"Отлично!\nМодель: {user_selections[uid]['bike']}\nРазмер: {size}\n\nНапишите имя и телефон:")

@bot.message_handler(func=lambda m: any(c.isdigit() for c in m.text) and len(m.text) > 5)
def save_order(msg):
    update_user_activity(msg.from_user.id)
    uid = msg.from_user.id
    sel = user_selections.get(uid, {})
    admin_msg = f"Новая заявка:\n\nПользователь: {msg.from_user.first_name}\nID: {uid}\nМодель: {sel.get('bike')}\nРазмер: {sel.get('frame_size')}\nКонтакты: {msg.text}"
    bot.send_message(ADMIN_ID, admin_msg)
    bot.send_message(msg.chat.id, "Спасибо! Мы свяжемся с вами.")
    if uid in user_selections:
        del user_selections[uid]

@bot.message_handler(func=lambda m: True)
def track(msg):
    update_user_activity(msg.from_user.id)

# === WEBHOOK ===
app = Flask(__name__)

@app.route('/bot', methods=['POST'])
def webhook():
    update = types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

if __name__ == "__main__":
    print("Бот запущен!")
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook: {WEBHOOK_URL}")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
