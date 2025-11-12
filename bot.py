import os
import logging
import json
import datetime
import time
from telebot import TeleBot, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage

# ======== ЛОГИРОВАНИЕ ========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"
ADMIN_ID = int(os.getenv("ADMIN_ID") or "ВАШ_ADMIN_ID")

storage = StateMemoryStorage()
bot = TeleBot(TOKEN, state_storage=storage)

USERS_FILE = "users.json"

# ======== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ========
def ensure_users_file():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

def load_users():
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f) if f.read().strip() else {}
            return data
    except:
        return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user_id, username, first_name, last_name):
    users = load_users()
    user_key = str(user_id)
    now = datetime.datetime.now().isoformat()
    if user_key in users:
        users[user_key].update({
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name or ''}".strip(),
            "last_activity": now,
            "messages_count": users[user_key].get("messages_count", 0) + 1
        })
    else:
        users[user_key] = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name or ''}".strip(),
            "first_seen": now,
            "last_activity": now,
            "messages_count": 1
        }
    save_users(users)

def update_user_activity(user_id):
    users = load_users()
    user_key = str(user_id)
    if user_key in users:
        users[user_key]["last_activity"] = datetime.datetime.now().isoformat()
        users[user_key]["messages_count"] = users[user_key].get("messages_count", 0) + 1
        save_users(users)

def get_all_users():
    return load_users()

# ======== FSM STATES ========
class ContactForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()

class AdminForm(StatesGroup):
    waiting_for_broadcast_message = State()

# ======== КАТАЛОГ ========
bikes = {
    "PRIMO": {
        "description": "🚴‍♂️ <b>PRIMO</b>\nМаневренная модель для холмистой местности.\nЦена: 50 000 руб.",
        "photos": [
            "https://optim.tildacdn.com/tild6336-3032-4434-b935-346363326131/-/format/webp/Photo-70.webp",
            "https://optim.tildacdn.com/tild6536-6564-4661-b563-323737643733/-/format/webp/Photo-45.webp"
        ],
        "specs": {"Вилка":"UDING DS HLO","Тормоза":"SHIMANO MT 200"}
    },
    "TERZO": {
        "description": "🚴‍♂️ <b>TERZO</b>\nЭффективная модель для прогрессирующих райдеров.\nЦена: 65 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3531-3036-4463-b536-303235326633/-/format/webp/Photo-71.webp"],
        "specs": {"Вилка":"UDING DS HLO","Тормоза":"SHIMANO MT 200"}
    },
    "ULTIMO": {
        "description": "🚴‍♂️ <b>ULTIMO</b>\nТоповый велосипед для трейлов.\nЦена: 75 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3637-6439-4237-b638-303336613863/-/format/webp/Photo-69.webp"],
        "specs": {"Вилка":"UDING DS HLO","Тормоза":"SHIMANO MT 200"}
    },
    "TESORO": {
        "description": "🚴‍♂️ <b>TESORO</b>\nСбалансированный аппарат для катания в горах.\nЦена: 85 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3932-3166-4537-b837-386365666162/-/format/webp/Photo-72.webp"],
        "specs": {"Вилка":"ZOOM 868 AIR BOOST","Тормоза":"SHIMANO MT 200"}
    },
    "OTTIMO": {
        "description": "🚴‍♂️ <b>OTTIMO</b>\nДля кросс-кантрийных марафонов.\nЦена: 95 000 руб.",
        "photos": ["https://optim.tildacdn.com/tild3662-3335-4362-a665-303137396364/-/format/webp/Photo-73.webp"],
        "specs": {"Вилка":"ROCK SHOX FS RECON 29F","Тормоза":"SHIMANO MT 200"}
    }
}

frame_sizes = {"M (17\")":"163-177 см","L (19\")":"173-187 см","XL (21\")":"182-197 см"}
user_photo_index = {}
user_selections = {}

# ======== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ========
def show_photo(message, user_id, bike_name, index):
    bike_data = bikes[bike_name]
    photos = bike_data["photos"]
    kb = types.InlineKeyboardMarkup()
    if len(photos) > 1:
        row = []
        if index > 0: row.append(types.InlineKeyboardButton("⬅️", callback_data=f"prev_photo_{bike_name}"))
        row.append(types.InlineKeyboardButton(f"{index+1}/{len(photos)}", callback_data="photo_counter"))
        if index < len(photos)-1: row.append(types.InlineKeyboardButton("➡️", callback_data=f"next_photo_{bike_name}"))
        kb.row(*row)
    kb.add(types.InlineKeyboardButton("📋 Спецификация", callback_data=f"specs_{bike_name}"))
    kb.add(types.InlineKeyboardButton("🛒 Заказать", callback_data=f"order_{bike_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад в каталог", callback_data="back_to_catalog"))
    caption = bike_data["description"] if index == 0 else f"Фото {index+1} из {len(photos)}"
    bot.send_photo(message.chat.id, photos[index], caption=caption, parse_mode="HTML", reply_markup=kb)

# ======== ОСНОВНЫЕ ОБРАБОТЧИКИ ========
@bot.message_handler(commands=['start'])
def start(msg):
    add_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Каталог 🚲","Позвать специалиста 👨‍💼","О нас ℹ️")
    bot.send_message(msg.chat.id, "👋 Добро пожаловать! Выберите действие:", reply_markup=kb)

@bot.message_handler(func=lambda m: "Каталог" in m.text)
def catalog(msg):
    update_user_activity(msg.from_user.id)
    kb = types.InlineKeyboardMarkup()
    for bike in bikes: kb.add(types.InlineKeyboardButton(bike, callback_data=f"bike_{bike}"))
    bot.send_message(msg.chat.id, "Выберите модель:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    update_user_activity(call.from_user.id)
    data = call.data
    uid = call.from_user.id

    # Показ модели
    if data.startswith("bike_"):
        bike_name = data.replace("bike_","")
        user_photo_index[uid] = {"bike":bike_name,"index":0}
        show_photo(call.message, uid, bike_name, 0)
        bot.answer_callback_query(call.id)
        return

    # Навигация по фото
    if data.startswith("prev_photo_") or data.startswith("next_photo_"):
        if uid not in user_photo_index: bot.answer_callback_query(call.id,"Сессия устарела"); return
        bike_name = user_photo_index[uid]["bike"]
        index = user_photo_index[uid]["index"]
        max_index = len(bikes[bike_name]["photos"])-1
        if data.startswith("prev_photo_"): index=max(0,index-1)
        else: index=min(max_index,index+1)
        user_photo_index[uid]["index"]=index
        try: bot.delete_message(call.message.chat.id,call.message.message_id)
        except: pass
        show_photo(call.message, uid, bike_name, index)
        bot.answer_callback_query(call.id)
        return

    # Спецификация
    if data.startswith("specs_"):
        bike_name = data.replace("specs_","")
        specs_text=f"🔧 <b>Спецификация {bike_name}</b>\n\n"
        for k,v in bikes[bike_name]["specs"].items(): specs_text+=f"• <b>{k}:</b> {v}\n"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад к модели",callback_data=f"bike_{bike_name}"))
        kb.add(types.InlineKeyboardButton("🛒 Заказать",callback_data=f"order_{bike_name}"))
        bot.send_message(call.message.chat.id,specs_text,parse_mode="HTML",reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    # Заказ
    if data.startswith("order_"):
        bike_name=data.replace("order_","")
        user_selections[uid]={"bike":bike_name}
        kb=types.InlineKeyboardMarkup()
        for s,h in frame_sizes.items(): kb.add(types.InlineKeyboardButton(f"{s} ({h})",callback_data=f"size_{s}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад к модели",callback_data=f"bike_{bike_name}"))
        bot.send_message(call.message.chat.id,f"Вы выбрали {bike_name}. Выберите размер рамы:",reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    # Сохранение размера
    if data.startswith("size_"):
        size=data.replace("size_","")
        if uid in user_selections:
            user_selections[uid]["frame_size"]=size
            user_selections[uid]["height_range"]=frame_sizes.get(size,"")
            bike_name=user_selections[uid]["bike"]
            bot.send_message(call.message.chat.id,f"Размер {size} выбран для модели {bike_name}. Введите имя и телефон:")
        bot.answer_callback_query(call.id)
        return

    # Назад в каталог
    if data=="back_to_catalog":
        kb=types.InlineKeyboardMarkup()
        for bike in bikes: kb.add(types.InlineKeyboardButton(bike,callback_data=f"bike_{bike}"))
        bot.send_message(call.message.chat.id,"Выберите модель:",reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

# ======== Ввод контактов ========
@bot.message_handler(func=lambda m:any(x.isdigit() for x in m.text) and len(m.text)>5)
def save_order(msg):
    update_user_activity(msg.from_user.id)
    uid=msg.from_user.id
    user_data=user_selections.get(uid,{})
    bike=user_data.get("bike","Неизвестная модель")
    frame=user_data.get("frame_size","Не выбран")
    height=user_data.get("height_range","")
    admin_msg=f"📩 Новая заявка:\n👤 {msg.from_user.full_name}\nID:{uid}\n🚲 {bike}\n📏 {frame} ({height})\n📞 {msg.text}"
    bot.send_message(ADMIN_ID,admin_msg)
    bot.send_message(msg.chat.id,"Спасибо! Мы свяжемся с вами в ближайшее время.")
    if uid in user_selections: del user_selections[uid]

# ======== Запуск бота ========
if __name__=="__main__":
    ensure_users_file()
    print("Бот запущен")
    bot.infinity_polling()
