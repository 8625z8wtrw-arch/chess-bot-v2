import logging
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import chess
import chess.engine
import chess.svg
import chess.pgn
from PIL import Image
import imageio
import cairosvg
import os

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")

logging.basicConfig(level=logging.INFO)
ENGINE_PATH = "./stockfish"
GIF_DURATION = 2.5

OPENINGS = {
    "Испанская партия": {"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"], "description": "Классика."},
    "Сицилианская защита": {"moves": ["e2e4", "c7c5"], "description": "Асимметричный ответ."},
    "Ферзевый гамбит": {"moves": ["d2d4", "d7d5", "c2c4"], "description": "Жертва пешки."},
    "Королевский гамбит": {"moves": ["e2e4", "e7e5", "f2f4"], "description": "Агрессивный."},
    "Защита Каро-Канн": {"moves": ["e2e4", "c7c6", "d2d4", "d7d5"], "description": "Надёжная."},
    "Защита Алехина": {"moves": ["e2e4", "g8f6"], "description": "Провокация."},
    "Английское начало": {"moves": ["c2c4"], "description": "Фланговый."},
    "Дебют четырёх коней": {"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6"], "description": "Симметричный."},
    "Защита двух коней": {"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"], "description": "Агрессивный ответ."},
    "Гамбит Эванса": {"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "b2b4"], "description": "Жертва b4."},
    "Русская партия": {"moves": ["e2e4", "e7e5", "g1f3", "g8f6"], "description": "Атака на e4."},
    "Шотландская партия": {"moves": ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4"], "description": "Открытый центр."},
    "Венская партия": {"moves": ["e2e4", "e7e5", "b1c3"], "description": "Подготовка f4."},
    "Французская защита": {"moves": ["e2e4", "e7e6", "d2d4", "d7d5"], "description": "Укрепление центра."},
    "Скандинавская защита": {"moves": ["e2e4", "d7d5"], "description": "Ранняя атака."},
    "Защита Пирца": {"moves": ["e2e4", "d7d6", "d2d4", "g8f6", "b1c3", "g7g6"], "description": "Фианкетто."},
    "Голландская защита": {"moves": ["d2d4", "f7f5"], "description": "Атака на королевском."},
    "Староиндийская защита": {"moves": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7"], "description": "Фианкетто слона."},
    "Новоиндийская защита": {"moves": ["d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6"], "description": "Фианкетто ферзя."},
    "Защита Грюнфельда": {"moves": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5"], "description": "Жертва центра."},
    "Защита Нимцовича": {"moves": ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"], "description": "Связка коня."},
    "Защита Бенони": {"moves": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6"], "description": "Пешечный центр."},
    "Волжский гамбит": {"moves": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5"], "description": "Жертва b5."},
    "Защита Филидора": {"moves": ["e2e4", "e7e5", "g1f3", "d7d6"], "description": "Укрепление."},
    "Защита Петрова": {"moves": ["e2e4", "e7e5", "g1f3", "g8f6"], "description": "Русская партия."},
}

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Анализ FEN", callback_data="menu_fen")],
        [InlineKeyboardButton("📖 Дебюты", callback_data="menu_openings")],
        [InlineKeyboardButton("🎬 GIF дебюта", callback_data="menu_gif")],
        [InlineKeyboardButton("📂 Загрузить PGN", callback_data="menu_pgn")],
        [InlineKeyboardButton("🔄 Пример FEN", callback_data="menu_example_fen")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="menu_main")]])

def generate_opening_gif(opening_name: str) -> bytes:
    if opening_name not in OPENINGS:
        return None
    moves = OPENINGS[opening_name]["moves"]
    board = chess.Board()
    frames = [chess.svg.board(board, size=400)]
    for move_uci in moves:
        try:
            board.push(chess.Move.from_uci(move_uci))
            frames.append(chess.svg.board(board, size=400))
        except:
            continue
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
    imageio.mimsave(gif_buffer, images, format='GIF', duration=GIF_DURATION, loop=0)
    gif_buffer.seek(0)
    return gif_buffer.getvalue()

async def analyze_position(fen: str) -> str:
    try:
        board = chess.Board(fen)
        with chess.engine.SimpleEngine.popen_uci(ENGINE_PATH) as engine:
            analysis = engine.analyse(board, chess.engine.Limit(time=2.0), multipv=3)
            if not analysis:
                return "❌ Не удалось найти ходы."
            result_text = "📊 **Топ-3 хода:**\n"
            for i, info in enumerate(analysis, 1):
                best_move = info.get("pv")[0] if info.get("pv") else None
                best_move_san = board.san(best_move) if best_move else "не найден"
                pv = info.get("pv", [])
                line_moves = [board.san(m) for m in pv[:3]]
                line_str = " ".join(line_moves) if line_moves else "нет продолжения"
                result_text += f"{i}. **{best_move_san}**\n   Линия: {line_str}\n"
            return result_text
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return f"❌ Ошибка: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("♟️ Привет! Отправь FEN или выбери действие:", reply_markup=get_main_menu())

async def handle_fen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fen_text = update.message.text.strip()
    try:
        chess.Board(fen_text)
    except ValueError:
        await update.message.reply_text("❌ Неверный FEN.", reply_markup=get_back_button())
        return
    await update.message.reply_text("🤔 Анализирую...")
    result = await analyze_position(fen_text)
    await update.message.reply_text(result, parse_mode='Markdown', reply_markup=get_back_button())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📘 Команды: /start, /opening_gif <название>, /move <ход>, /help"
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=get_back_button())
        except:
            await update.callback_query.message.reply_text(text, reply_markup=get_back_button())
    else:
        await update.message.reply_text(text, reply_markup=get_back_button())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "menu_main":
            await query.edit_message_text("♟️ Выбери действие:", reply_markup=get_main_menu())
        elif query.data == "menu_fen":
            await query.edit_message_text("📊 Отправь FEN-строку.", reply_markup=get_back_button())
        elif query.data == "menu_openings":
            list_text = "📖 Дебюты:\n" + "\n".join(f"• {key}" for key in OPENINGS.keys())
            await query.edit_message_text(list_text, reply_markup=get_back_button())
        elif query.data == "menu_gif":
            await query.edit_message_text("🎬 Введи: /opening_gif Испанская партия", reply_markup=get_back_button())
        elif query.data == "menu_pgn":
            await query.edit_message_text("📂 Отправь .pgn файл.", reply_markup=get_back_button())
        elif query.data == "menu_example_fen":
            example = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            await query.edit_message_text(f"🔄 Пример: `{example}`", parse_mode='Markdown', reply_markup=get_back_button())
        elif query.data == "menu_help":
            await help_command(update, context)
    except Exception as e:
        logging.error(f"Callback error: {e}")

async def opening_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args) if context.args else None
    if not name:
        await update.message.reply_text("Укажи название: /opening_gif Испанская партия")
        return
    found = None
    for key in OPENINGS:
        if name.lower() in key.lower():
            found = key
            break
    if not found:
        await update.message.reply_text("❌ Не найден.")
        return
    try:
        await update.message.reply_text(f"🎬 Генерирую...")
        gif_data = generate_opening_gif(found)
        if gif_data:
            await update.message.reply_animation(animation=InputFile(io.BytesIO(gif_data), filename="opening.gif"), caption=f"🎬 {found} ({GIF_DURATION} сек/кадр)", reply_markup=get_back_button())
        else:
            await update.message.reply_text("❌ Ошибка GIF.", reply_markup=get_back_button())
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=get_back_button())

async def move_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /move e4")
        return
    user_data = context.user_data
    fen = user_data.get("last_fen")
    if not fen:
        await update.message.reply_text("Сначала отправь FEN.")
        return
    try:
        board = chess.Board(fen)
    except:
        await update.message.reply_text("Ошибка в позиции.")
        return
    move_str = " ".join(context.args)
    try:
        move = board.parse_san(move_str)
        board.push(move)
        new_fen = board.fen()
        user_data["last_fen"] = new_fen
        result = await analyze_position(new_fen)
        await update.message.reply_text(f"✅ Ход {move_str}:\n{result}", parse_mode='Markdown', reply_markup=get_back_button())
    except ValueError:
        await update.message.reply_text(f"❌ Неверный ход.", reply_markup=get_back_button())

async def handle_pgn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(('.pgn', '.PGN')):
        await update.message.reply_text("❌ Отправь .pgn файл.")
        return
    try:
        await update.message.reply_text("📂 Загружаю...")
        file = await doc.get_file()
        pgn_bytes = await file.download_as_bytearray()
        pgn_str = pgn_bytes.decode('utf-8')
        pgn_io = io.StringIO(pgn_str)
        game = chess.pgn.read_game(pgn_io)
        if not game:
            await update.message.reply_text("❌ Ошибка PGN.")
            return
        board = game.board()
        moves = list(game.mainline_moves())
        if not moves:
            await update.message.reply_text("❌ Нет ходов.")
            return
        await update.message.reply_text(f"📂 **PGN загружен**\nХодов: {len(moves)}", parse_mode='Markdown', reply_markup=get_back_button())
        board = game.board()
        for move in moves:
            board.push(move)
        context.user_data["last_fen"] = board.fen()
        result = await analyze_position(board.fen())
        await update.message.reply_text(result, parse_mode='Markdown', reply_markup=get_back_button())
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=get_back_button())

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("move", move_command))
    app.add_handler(CommandHandler("m", move_command))
    app.add_handler(CommandHandler("opening_gif", opening_gif))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fen))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pgn))
    print("✅ Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
