import logging
import os
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

# --- НАСТРОЙКИ ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")

ENGINE_PATH = "./stockfish"
DEFAULT_GIF_DURATION = 4.0  # секунд на кадр (по умолчанию)

logging.basicConfig(level=logging.INFO)

# ----------------------------------------------------------------------
# ДЕБЮТНАЯ БАЗА (основная линия + 2 ответвления)
# ----------------------------------------------------------------------
OPENINGS = {
    "Испанская партия": {
        "main": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "f8e7"],
        "variations": [
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "d7d6"],
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "e1g1", "f8e7", "d2d4", "e5d4"]
        ],
        "description": "Классический дебют. Давление на коня c6."
    },
    "Сицилианская защита": {
        "main": ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "g7g6"],
        "variations": [
            ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e6"],
            ["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "d7d6"]
        ],
        "description": "Асимметричный ответ. Борьба за центр."
    },
    "Ферзевый гамбит": {
        "main": ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8e7", "e2e3", "e1g1"],
        "variations": [
            ["d2d4", "d7d5", "c2c4", "c7c6", "b1c3", "g8f6", "c1f4", "e7e6", "e2e3", "f8d6"],
            ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8b4", "e2e3", "e1g1"]
        ],
        "description": "Жертва пешки c4 за центр."
    },
    # Добавьте остальные дебюты (структура та же)
    "Королевский гамбит": {
        "main": ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "g8f6", "e4e5", "f6h5", "d2d4", "d7d5"],
        "variations": [
            ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "d7d6", "d2d4", "g8f6", "f1d3", "e1g1"],
            ["e2e4", "e7e5", "f2f4", "e5f4", "g1f3", "g8f6", "e4e5", "f6h5", "d2d4", "d7d5"]
        ],
        "description": "Агрессивная жертва пешки f4."
    },
    "Защита Каро-Канн": {
        "main": ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "c8f5", "e4g3", "f5g6"],
        "variations": [
            ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "c8f5", "e4g3", "f5g6"],
            ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "g8f6", "e4f6", "e7f6"]
        ],
        "description": "Надёжная защита."
    },
    "Защита Алехина": {
        "main": ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "f2f4", "d6e5"],
        "variations": [
            ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "f2f4", "d6e5"],
            ["e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6", "c2c4", "d5b6", "b1c3", "c8f5"]
        ],
        "description": "Провокация пешек."
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
    """Генерирует GIF по списку UCI-ходов с заданной длительностью кадра."""
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

# ----------------------------------------------------------------------
# МЕНЮ
# ----------------------------------------------------------------------
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Анализ FEN", callback_data="menu_fen")],
        [InlineKeyboardButton("📖 Все дебюты (3 гифки)", callback_data="menu_openings")],
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
        [InlineKeyboardButton("🐢 Очень медленно (8 сек)", callback_data="speed_8")],
        [InlineKeyboardButton("🐢 Медленно (6 сек)", callback_data="speed_6")],
        [InlineKeyboardButton("🐢 Средне (4 сек)", callback_data="speed_4")],
        [InlineKeyboardButton("⚡ Быстро (2 сек)", callback_data="speed_2")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ----------------------------------------------------------------------
# ОБРАБОТЧИКИ
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Устанавливаем скорость по умолчанию, если не задана
    if 'gif_duration' not in context.user_data:
        context.user_data['gif_duration'] = DEFAULT_GIF_DURATION
    await update.message.reply_text(
        f"♟️ **Шахматный справочник**\n\n"
        f"Текущая скорость GIF: **{context.user_data['gif_duration']} сек/кадр**\n"
        f"Выбери дебют – получишь 3 гифки: основная линия и 2 ответвления.\n"
        f"Скорость можно изменить в меню.",
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )

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
                "🎬 **Выбери скорость GIF:**\n(в секундах на кадр)",
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
            await query.edit_message_text(f"🎬 Генерирую 3 гифки для «{opening_name}»... (скорость {duration} сек/кадр)")
            # Генерируем и отправляем по одной
            main_gif = generate_gif_from_moves(opening["main"], duration)
            var1_gif = generate_gif_from_moves(opening["variations"][0], duration)
            var2_gif = generate_gif_from_moves(opening["variations"][1], duration)
            main_san = format_variation(opening["main"])
            var1_san = format_variation(opening["variations"][0])
            var2_san = format_variation(opening["variations"][1])
            if main_gif:
                await query.message.reply_animation(
                    animation=InputFile(io.BytesIO(main_gif), filename="main.gif"),
                    caption=f"🎬 {opening_name} – Основная линия\n`{main_san}`",
                    parse_mode='Markdown'
                )
            if var1_gif:
                await query.message.reply_animation(
                    animation=InputFile(io.BytesIO(var1_gif), filename="var1.gif"),
                    caption=f"🔄 Ответвление 1\n`{var1_san}`",
                    parse_mode='Markdown'
                )
            if var2_gif:
                await query.message.reply_animation(
                    animation=InputFile(io.BytesIO(var2_gif), filename="var2.gif"),
                    caption=f"🔄 Ответвление 2\n`{var2_san}`",
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
        "/move <ход> – сделать ход (например, /move e4)\n"
        "/help – эта справка\n\n"
        "• Отправь FEN-строку для анализа позиции.\n"
        "• Загрузи PGN-файл для анализа партии.\n"
        "• Используй кнопки меню для быстрого доступа.\n\n"
        "🎬 Скорость GIF настраивается в меню."
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
        await update.message.reply_text(f"🎬 Генерирую 3 гифки для «{found}»...")
        main_gif = generate_gif_from_moves(opening["main"], duration)
        var1_gif = generate_gif_from_moves(opening["variations"][0], duration)
        var2_gif = generate_gif_from_moves(opening["variations"][1], duration)
        main_san = format_variation(opening["main"])
        var1_san = format_variation(opening["variations"][0])
        var2_san = format_variation(opening["variations"][1])
        if main_gif:
            await update.message.reply_animation(
                animation=InputFile(io.BytesIO(main_gif), filename="main.gif"),
                caption=f"🎬 {found} – Основная линия\n`{main_san}`",
                parse_mode='Markdown'
            )
        if var1_gif:
            await update.message.reply_animation(
                animation=InputFile(io.BytesIO(var1_gif), filename="var1.gif"),
                caption=f"🔄 Ответвление 1\n`{var1_san}`",
                parse_mode='Markdown'
            )
        if var2_gif:
            await update.message.reply_animation(
                animation=InputFile(io.BytesIO(var2_gif), filename="var2.gif"),
                caption=f"🔄 Ответвление 2\n`{var2_san}`",
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
    print("✅ Бот запущен (с выбором скорости).")
    app.run_polling()

if __name__ == "__main__":
    main()
