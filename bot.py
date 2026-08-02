import logging
import os
import io
import threading
import time
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import chess
import chess.engine
import chess.svg
import chess.pgn
from PIL import Image
import imageio
import cairosvg

# ----------------------------------------------------------------------
# НАСТРОЙКИ
# ----------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")

ENGINE_PATH = "./stockfish"
DEFAULT_GIF_DURATION = 1.0

logging.basicConfig(level=logging.INFO)

# ----------------------------------------------------------------------
# FLASK-СЕРВЕР ДЛЯ HEALTH-CHECK (чтобы Render не засыпал)
# ----------------------------------------------------------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "✅ Bot is running!", 200

def keep_alive():
    """Каждые 10 минут отправляет GET-запрос на свой URL, чтобы Render не усыпил бота."""
    url = os.getenv('RENDER_EXTERNAL_URL')
    if not url:
        # Если переменной нет (локальный запуск), не пингуем
        return
    while True:
        try:
            requests.get(url, timeout=10)
            print("✅ Пинг успешен")
        except Exception as e:
            print(f"❌ Ошибка пинга: {e}")
        time.sleep(600)  # 10 минут

def start_flask():
    port = int(os.getenv('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)

def start_keep_alive():
    thread = threading.Thread(target=keep_alive, daemon=True)
    thread.start()

# ----------------------------------------------------------------------
# ДЕБЮТНАЯ БАЗА (25 дебютов с названиями вариантов)
# ----------------------------------------------------------------------
OPENINGS = {
    "Испанская партия": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "f8e7"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "d7d6"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "e1g1", "f8e7", "d2d4", "e5d4"]
        ],
        "variation_names": ["Вариант с 9...d6", "Берлинская защита (3...Nf6)"],
        "description": "Классический дебют. Давление на коня c6."
    },
    "Сицилианская защита": {
        "main": ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "g7g6"],
        "variations": [
            ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e6"],
            ["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "d7d6"]
        ],
        "variation_names": ["Дракон (9...g6)", "Классическая с 2...Nc6"],
        "description": "Асимметричный ответ. Борьба за центр."
    },
    "Ферзевый гамбит": {
        "main": ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8e7", "e2e3", "e1g1"],
        "variations": [
            ["d2d4", "d7d5", "c2c4", "c7c6", "b1c3", "g8f6", "c1f4", "e7e6", "e2e3", "f8d6"],
            ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8b4", "e2e3", "e1g1"]
        ],
        "variation_names": ["Славянская защита (3...c6)", "Принятый гамбит (3...Bb4)"],
        "description": "Жертва пешки c4 за центр."
    },
    "Королевский гамбит": {
        "main": ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "g8f6", "e4e5", "f6h5", "d2d4", "d7d5"],
        "variations": [
            ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "d7d6", "d2d4", "g8f6", "f1d3", "e1g1"],
            ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "g8f6", "e4e5", "f6h5", "d2d4", "d7d5"]
        ],
        "variation_names": ["Вариант с ...d6", "Контратака ...d5"],
        "description": "Агрессивная жертва пешки f4."
    },
    "Защита Каро-Канн": {
        "main": ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "c8f5", "e4g3", "f5g6"],
        "variations": [
            ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "c8f5", "e4g3", "f5g6"],
            ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "g8f6", "e4f6", "e7f6"]
        ],
        "variation_names": ["Классическая линия", "Вариант с ...Nf6"],
        "description": "Надёжная защита."
    },
    "Защита Алехина": {
        "main": ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "f2f4", "d6e5"],
        "variations": [
            ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "f2f4", "d6e5"],
            ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "b1c3", "c8f5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Bf5"],
        "description": "Провокация пешек."
    },
    "Английское начало": {
        "main": ["c2c4", "e7e5", "g1f3", "e5e4", "d2d4", "e4f3", "d4d5", "g8e7", "e2e4", "d7d6"],
        "variations": [
            ["c2c4", "e7e5", "g1f3", "e5e4", "d2d4", "e4f3", "d4d5", "g8e7", "e2e4", "d7d6"],
            ["c2c4", "e7e5", "g1f3", "e5e4", "d2d4", "e4f3", "d4d5", "g8e7", "e2e4", "f7f5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...f5"],
        "description": "Фланговый контроль поля d5."
    },
    "Дебют четырёх коней": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6", "d2d4", "e5d4", "f3d4", "f8b4"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6", "d2d4", "e5d4", "f3d4", "f8b4"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6", "f1c4", "f8c5", "e1g1", "e1g1"]
        ],
        "variation_names": ["Главная линия", "Итальянская ветка"],
        "description": "Симметричное развитие."
    },
    "Защита двух коней": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d4", "e5d4", "e1g1", "f8c5"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d4", "e5d4", "e1g1", "f8c5"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d4", "e5d4", "c4d5", "f6d5"]
        ],
        "variation_names": ["Классическая", "Вариант с 9.Bxd5"],
        "description": "Агрессивный ответ."
    },
    "Гамбит Эванса": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "b2b4", "c5b4", "c2c3", "b4c5"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "b2b4", "c5b4", "c2c3", "b4c5"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "b2b4", "c5b4", "c2c3", "b4a5"]
        ],
        "variation_names": ["Главная линия", "Отступление на a5"],
        "description": "Жертва пешки b4."
    },
    "Русская партия": {
        "main": ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "d7d5"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "d7d5"],
            ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "f8c5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Bc5"],
        "description": "Атака на пешку e4."
    },
    "Шотландская партия": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4", "d7d5", "e4d5", "f6d5"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4", "d7d5", "e4d5", "f6d5"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4", "d7d5", "e4d5", "f6d5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Nxd5"],
        "description": "Открытый центр."
    },
    "Венская партия": {
        "main": ["e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5", "f4e5", "f6e4", "d2d3", "e4c5"],
        "variations": [
            ["e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5", "f4e5", "f6e4", "d2d3", "e4c5"],
            ["e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5", "f4e5", "f6e4", "d2d3", "e4g5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Ng5"],
        "description": "Подготовка f4."
    },
    "Французская защита": {
        "main": ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6", "c1g5", "f8e7", "e4e5", "f6d7"],
        "variations": [
            ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6", "c1g5", "f8e7", "e4e5", "f6d7"],
            ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "g8f6"]
        ],
        "variation_names": ["Классическая линия", "Вариант с разменом"],
        "description": "Укрепление центра чёрными."
    },
    "Скандинавская защита": {
        "main": ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5", "d2d4", "g8f6", "g1f3", "c8f5"],
        "variations": [
            ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5", "d2d4", "g8f6", "g1f3", "c8f5"],
            ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5", "d2d4", "g8f6", "g1f3", "c8g4"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Bg4"],
        "description": "Ранняя атака центра."
    },
    "Голландская защита": {
        "main": ["d2d4", "f7f5", "g1f3", "g8f6", "g2g3", "e7e6", "f1g2", "f8e7", "e1g1", "e8g8"],
        "variations": [
            ["d2d4", "f7f5", "g1f3", "g8f6", "g2g3", "e7e6", "f1g2", "f8e7", "e1g1", "e8g8"],
            ["d2d4", "f7f5", "g1f3", "g8f6", "g2g3", "d7d6", "f1g2", "c8d7"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...d6"],
        "description": "Атака на королевском фланге."
    },
    "Староиндийская защита": {
        "main": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6", "g1f3", "e8g8"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6", "g1f3", "e8g8"],
            ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6", "f2f4", "e8g8"]
        ],
        "variation_names": ["Главная линия", "Атака Самиша (f4)"],
        "description": "Фианкетто слона."
    },
    "Новоиндийская защита": {
        "main": ["d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6", "g2g3", "c8b7", "f1g2", "f8e7"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6", "g2g3", "c8b7", "f1g2", "f8e7"],
            ["d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6", "g2g3", "c8b7", "e1g1", "f8e7"]
        ],
        "variation_names": ["Главная линия", "Вариант с рокировкой"],
        "description": "Фианкетто ферзевого слона."
    },
    "Защита Грюнфельда": {
        "main": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5", "g1f3", "f8g7", "c4d5", "f6d5"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5", "g1f3", "f8g7", "c4d5", "f6d5"],
            ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5", "c4d5", "f6d5", "e2e4", "d5c3"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Nxc3"],
        "description": "Жертва центра."
    },
    "Защита Нимцовича": {
        "main": ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "d1c2", "d7d5", "c4d5", "e6d5"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "d1c2", "d7d5", "c4d5", "e6d5"],
            ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "d1c2", "e8g8", "a2a3", "b4c3"]
        ],
        "variation_names": ["Главная линия", "Вариант с рокировкой"],
        "description": "Связка коня c3."
    },
    "Защита Бенони": {
        "main": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6", "b1c3", "e6d5", "c4d5", "d7d6"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6", "b1c3", "e6d5", "c4d5", "d7d6"],
            ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6", "b1c3", "e6d5", "c4d5", "f8e7"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Be7"],
        "description": "Пешечный центр."
    },
    "Волжский гамбит": {
        "main": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5", "c4b5", "a7a6", "b5a6", "c8a6"],
        "variations": [
            ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5", "c4b5", "a7a6", "b5a6", "c8a6"],
            ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5", "c4b5", "a7a6", "b5a6", "d7d6"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...d6"],
        "description": "Жертва пешки b5."
    },
    "Защита Филидора": {
        "main": ["e2e4", "e7e5", "g1f3", "d7d6", "d2d4", "e5d4", "f3d4", "g8f6", "b1c3", "f8e7"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "d7d6", "d2d4", "e5d4", "f3d4", "g8f6", "b1c3", "f8e7"],
            ["e2e4", "e7e5", "g1f3", "d7d6", "d2d4", "e5d4", "f3d4", "g8f6", "b1c3", "c8d7"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Bd7"],
        "description": "Укрепление центра."
    },
    "Защита Петрова": {
        "main": ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "d7d5"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "d7d5"],
            ["e2e4", "e7e5", "g1f3", "g8f6", "d2d4", "e5d4", "e4e5", "f6e4", "f3d4", "f8c5"]
        ],
        "variation_names": ["Главная линия", "Вариант с ...Bc5"],
        "description": "Русская партия."
    }
}

# ----------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ----------------------------------------------------------------------
def uci_to_san(moves_uci, start_fen=None):
    board = chess.Board(start_fen) if start_fen else chess.Board()
    san_moves = []
    for uci in moves_uci:
        try:
            move = chess.Move.from_uci(uci)
            san = board.san(move)
            board.push(move)
            san_moves.append(san)
        except:
            continue
    return " ".join(san_moves)

def generate_gif_from_moves(moves_uci, duration):
    board = chess.Board()
    frames = [chess.svg.board(board, size=400)]
    for uci in moves_uci:
        try:
            move = chess.Move.from_uci(uci)
            board.push(move)
            frames.append(chess.svg.board(board, size=400))
        except:
            continue
    if not frames:
        return None
    images = []
    for svg in frames:
        try:
            png_data = cairosvg.svg2png(bytestring=svg.encode('utf-8'))
            images.append(Image.open(io.BytesIO(png_data)))
        except:
            continue
    if not images:
        return None
    gif_buffer = io.BytesIO()
    imageio.mimsave(gif_buffer, images, format='GIF', duration=duration, loop=0)
    gif_buffer.seek(0)
    return gif_buffer.getvalue()

def format_variation(moves_uci):
    return uci_to_san(moves_uci)

def get_variation_name(opening, idx):
    names = opening.get("variation_names", [])
    if names and idx <= len(names):
        return names[idx-1]
    return f"Ответвление {idx}"

# ----------------------------------------------------------------------
# МЕНЮ
# ----------------------------------------------------------------------
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Анализ FEN", callback_data="menu_fen")],
        [InlineKeyboardButton("📖 Все дебюты", callback_data="menu_openings")],
        [InlineKeyboardButton("🎬 Настроить скорость", callback_data="menu_speed")],
        [InlineKeyboardButton("📂 Загрузить PGN", callback_data="menu_pgn")],
        [InlineKeyboardButton("🔄 Пример FEN", callback_data="menu_example_fen")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="menu_main")]])

def get_speed_menu():
    keyboard = [
        [InlineKeyboardButton("⚡ 0.1 сек", callback_data="speed_0.1"),
         InlineKeyboardButton("⚡ 0.2 сек", callback_data="speed_0.2"),
         InlineKeyboardButton("⚡ 0.4 сек", callback_data="speed_0.4")],
        [InlineKeyboardButton("⚡ 0.6 сек", callback_data="speed_0.6"),
         InlineKeyboardButton("⚡ 0.8 сек", callback_data="speed_0.8"),
         InlineKeyboardButton("🐢 1.0 сек", callback_data="speed_1.0")],
        [InlineKeyboardButton("🐢 1.2 сек", callback_data="speed_1.2"),
         InlineKeyboardButton("🐢 1.5 сек", callback_data="speed_1.5"),
         InlineKeyboardButton("🐢 2.0 сек", callback_data="speed_2.0")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ----------------------------------------------------------------------
# ОБРАБОТЧИКИ
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'gif_duration' not in context.user_data:
        context.user_data['gif_duration'] = DEFAULT_GIF_DURATION
    await update.message.reply_text(
        f"♟️ **Шахматный справочник**\n\n"
        f"Текущая скорость GIF: **{context.user_data['gif_duration']} сек/кадр**\n"
        f"Выбери дебют – получишь гифки (основная линия + варианты).\n"
        f"Скорость можно изменить в меню или командой `/speed <секунды>` (0.1–2.0).",
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )

async def speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: `/speed 0.5` (от 0.1 до 2.0)", parse_mode='Markdown')
        return
    try:
        val = float(context.args[0])
        if val < 0.1 or val > 2.0:
            await update.message.reply_text("Скорость должна быть от 0.1 до 2.0 секунд.")
            return
        context.user_data['gif_duration'] = val
        await update.message.reply_text(f"✅ Скорость установлена: **{val} сек/кадр**", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Введите число (например, 0.5)")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "menu_main":
            await query.edit_message_text(
                f"♟️ Выбери действие:\nСкорость: {context.user_data.get('gif_duration', DEFAULT_GIF_DURATION)} сек/кадр",
                reply_markup=get_main_menu()
            )
        elif query.data == "menu_fen":
            await query.edit_message_text(
                "📊 **Анализ позиции по FEN**\nОтправь мне FEN-строку.\nПример:\n`rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`",
                parse_mode='Markdown',
                reply_markup=get_back_button()
            )
        elif query.data == "menu_openings":
            buttons = []
            for name in OPENINGS:
                buttons.append([InlineKeyboardButton(name, callback_data=f"gif_{name}")])
            buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_main")])
            await query.edit_message_text(
                "📖 Выбери дебют:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        elif query.data == "menu_speed":
            await query.edit_message_text(
                "🎬 **Выбери скорость GIF:** (секунд на кадр)\nМожно также использовать `/speed <число>`",
                reply_markup=get_speed_menu()
            )
        elif query.data.startswith("speed_"):
            speed = float(query.data.split("_")[1])
            context.user_data['gif_duration'] = speed
            await query.edit_message_text(
                f"✅ Скорость установлена: **{speed} сек/кадр**",
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        elif query.data == "menu_pgn":
            await query.edit_message_text(
                "📂 **Загрузка PGN**\nОтправь мне файл с расширением `.pgn`.",
                reply_markup=get_back_button()
            )
        elif query.data == "menu_example_fen":
            example = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            await query.edit_message_text(
                f"🔄 **Пример FEN**\nСкопируй и отправь мне:\n`{example}`",
                parse_mode='Markdown',
                reply_markup=get_back_button()
            )
        elif query.data == "menu_help":
            await help_command(update, context)
        elif query.data.startswith("gif_"):
            opening_name = query.data[4:]
            opening = OPENINGS.get(opening_name)
            if not opening:
                await query.message.reply_text("❌ Дебют не найден.", reply_markup=get_back_button())
                return
            duration = context.user_data.get('gif_duration', DEFAULT_GIF_DURATION)
            await query.edit_message_text(f"🎬 Генерирую гифки для «{opening_name}»... (скорость {duration} сек/кадр)")

            main_gif = generate_gif_from_moves(opening["main"], duration)
            main_san = format_variation(opening["main"])
            if main_gif:
                await query.message.reply_animation(
                    animation=InputFile(io.BytesIO(main_gif), filename="main.gif"),
                    caption=f"🎬 {opening_name} – Основная линия\n`{main_san}`",
                    parse_mode='Markdown'
                )

            if opening.get("variations"):
                for idx, var_moves in enumerate(opening["variations"], 1):
                    var_gif = generate_gif_from_moves(var_moves, duration)
                    var_san = format_variation(var_moves)
                    var_name = get_variation_name(opening, idx)
                    if var_gif:
                        await query.message.reply_animation(
                            animation=InputFile(io.BytesIO(var_gif), filename=f"var{idx}.gif"),
                            caption=f"🔄 {var_name}\n`{var_san}`",
                            parse_mode='Markdown'
                        )

            await query.message.reply_text(
                f"📖 {opening['description']}\n⏱️ Скорость: {duration} сек/кадр",
                reply_markup=get_back_button()
            )
    except Exception as e:
        logging.error(f"Callback error: {e}")
        try:
            await query.message.reply_text("⚠️ Произошла ошибка, попробуй снова.", reply_markup=get_main_menu())
        except:
            pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📘 **Команды:**\n"
        "/start – главное меню\n"
        "/opening_gif <название> – GIF дебюта (можно часть названия)\n"
        "/speed <секунды> – установить скорость (0.1..2.0)\n"
        "/move <ход> – сделать ход (например, /move e4)\n"
        "/help – эта справка\n\n"
        "• Отправь FEN-строку для анализа позиции.\n"
        "• Загрузи PGN-файл для анализа партии.\n"
        "• Используй кнопки меню для быстрого доступа."
    )
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_back_button())
        except:
            await update.callback_query.message.reply_text(text, parse_mode='Markdown', reply_markup=get_back_button())
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_back_button())

async def opening_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args) if context.args else None
    if not name:
        await update.message.reply_text(
            "Укажи название дебюта (можно часть слова).\nПример: `/opening_gif Испанская партия`",
            parse_mode='Markdown',
            reply_markup=get_back_button()
        )
        return
    found = None
    for key in OPENINGS:
        if name.lower() in key.lower():
            found = key
            break
    if not found:
        await update.message.reply_text("❌ Дебют не найден.", reply_markup=get_back_button())
        return
    opening = OPENINGS[found]
    duration = context.user_data.get('gif_duration', DEFAULT_GIF_DURATION)
    try:
        await update.message.reply_text(f"🎬 Генерирую гифки для «{found}»...")
        main_gif = generate_gif_from_moves(opening["main"], duration)
        main_san = format_variation(opening["main"])
        if main_gif:
            await update.message.reply_animation(
                animation=InputFile(io.BytesIO(main_gif), filename="main.gif"),
                caption=f"🎬 {found} – Основная линия\n`{main_san}`",
                parse_mode='Markdown'
            )
        if opening.get("variations"):
            for idx, var_moves in enumerate(opening["variations"], 1):
                var_gif = generate_gif_from_moves(var_moves, duration)
                var_san = format_variation(var_moves)
                var_name = get_variation_name(opening, idx)
                if var_gif:
                    await update.message.reply_animation(
                        animation=InputFile(io.BytesIO(var_gif), filename=f"var{idx}.gif"),
                        caption=f"🔄 {var_name}\n`{var_san}`",
                        parse_mode='Markdown'
                    )
        await update.message.reply_text(
            f"📖 {opening['description']}\n⏱️ Скорость: {duration} сек/кадр",
            reply_markup=get_back_button()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_back_button())

async def move_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: `/move e4`", parse_mode='Markdown', reply_markup=get_back_button())
        return
    user_data = context.user_data
    fen = user_data.get("last_fen")
    if not fen:
        await update.message.reply_text("Сначала отправь FEN-строку позиции.", reply_markup=get_back_button())
        return
    try:
        board = chess.Board(fen)
    except:
        await update.message.reply_text("Ошибка в сохранённой позиции, отправь FEN заново.", reply_markup=get_back_button())
        return
    move_str = " ".join(context.args)
    try:
        move = board.parse_san(move_str)
        board.push(move)
        new_fen = board.fen()
        user_data["last_fen"] = new_fen
        result = await analyze_position(new_fen)
        await update.message.reply_text(f"✅ Ход {move_str} сделан. Новая позиция:\n{result}", parse_mode='Markdown', reply_markup=get_back_button())
    except ValueError:
        await update.message.reply_text(f"❌ Неверный ход '{move_str}'. Попробуй снова.", reply_markup=get_back_button())

async def handle_fen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fen_text = update.message.text.strip()
    try:
        chess.Board(fen_text)
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный FEN. Проверь строку.\nПример: `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`",
            parse_mode='Markdown',
            reply_markup=get_back_button()
        )
        return
    await update.message.reply_text("🤔 Анализирую позицию...")
    result = await analyze_position(fen_text)
    await update.message.reply_text(result, parse_mode='Markdown', reply_markup=get_back_button())

async def analyze_position(fen: str) -> str:
    try:
        board = chess.Board(fen)
        with chess.engine.SimpleEngine.popen_uci(ENGINE_PATH) as engine:
            analysis = engine.analyse(board, chess.engine.Limit(time=2.0), multipv=3)
            if not analysis:
                return "❌ Не удалось найти ходы."
            result_text = "📊 **Топ-3 рекомендуемых хода:**\n"
            for i, info in enumerate(analysis, 1):
                best_move = info.get("pv")[0] if info.get("pv") else None
                best_move_san = board.san(best_move) if best_move else "не найден"
                pv = info.get("pv", [])
                line_moves = [board.san(m) for m in pv[:3]]
                line_str = " ".join(line_moves) if line_moves else "нет продолжения"
                result_text += f"{i}. **{best_move_san}**\n   Линия: {line_str}\n"
            return result_text
    except Exception as e:
        logging.error(f"Ошибка анализа: {e}")
        return f"❌ Ошибка: {e}"

async def handle_pgn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(('.pgn', '.PGN')):
        await update.message.reply_text("❌ Отправь файл с расширением .pgn.", reply_markup=get_back_button())
        return
    try:
        await update.message.reply_text("📂 Загружаю и анализирую PGN...")
        file = await doc.get_file()
        pgn_bytes = await file.download_as_bytearray()
        pgn_str = pgn_bytes.decode('utf-8')
        pgn_io = io.StringIO(pgn_str)
        game = chess.pgn.read_game(pgn_io)
        if not game:
            await update.message.reply_text("❌ Не удалось прочитать PGN.", reply_markup=get_back_button())
            return
        board = game.board()
        moves = list(game.mainline_moves())
        if not moves:
            await update.message.reply_text("❌ В партии нет ходов.", reply_markup=get_back_button())
            return
        first_move = board.san(moves[0])
        opening_name = "Неизвестный"
        for name, data in OPENINGS.items():
            if data["main"][0] == first_move:
                opening_name = name
                break
        await update.message.reply_text(
            f"📂 **PGN загружен**\n♟️ Дебют: {opening_name}\n📊 Всего ходов: {len(moves)}",
            parse_mode='Markdown',
            reply_markup=get_back_button()
        )
        board = game.board()
        for move in moves:
            board.push(move)
        context.user_data["last_fen"] = board.fen()
        result = await analyze_position(board.fen())
        await update.message.reply_text(result, parse_mode='Markdown', reply_markup=get_back_button())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка обработки PGN: {e}", reply_markup=get_back_button())

# ----------------------------------------------------------------------
# ЗАПУСК
# ----------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("speed", speed_command))
    app.add_handler(CommandHandler("move", move_command))
    app.add_handler(CommandHandler("m", move_command))
    app.add_handler(CommandHandler("opening_gif", opening_gif))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fen))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pgn))

    # Запускаем Flask-сервер в фоновом потоке (для health-check)
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Запускаем самопинг (чтобы Render не усыпил бота)
    start_keep_alive()

    print("✅ Бот запущен (с самопингом и Flask).")
    app.run_polling()

if __name__ == "__main__":
    main()
