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
# Читаем токен из переменной окружения (на Render) или из переменной окружения локально
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")

ENGINE_PATH = "./stockfish"      # для Render (бинарник в корне проекта)
GIF_DURATION = 4.0               # длительность каждого кадра в секундах

logging.basicConfig(level=logging.INFO)

# --- ДЕБЮТНАЯ БАЗА (25 дебютов с описаниями) ---
OPENINGS = {
    "Испанская партия": {
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
        "description": "Классика. Белые оказывают давление на коня c6, готовят рокировку и центральный прорыв d4."
    },
    "Сицилианская защита": {
        "moves": ["e2e4", "c7c5"],
        "description": "Асимметричный ответ. Чёрные борются за центр через ферзевый фланг."
    },
    "Ферзевый гамбит": {
        "moves": ["d2d4", "d7d5", "c2c4"],
        "description": "Белые жертвуют пешку c4 за центр и развитие."
    },
    "Королевский гамбит": {
        "moves": ["e2e4", "e7e5", "f2f4"],
        "description": "Агрессивная жертва пешки f4 для быстрой атаки."
    },
    "Защита Каро-Канн": {
        "moves": ["e2e4", "c7c6", "d2d4", "d7d5"],
        "description": "Надёжная защита с укреплением центра."
    },
    "Защита Алехина": {
        "moves": ["e2e4", "g8f6"],
        "description": "Чёрные провоцируют пешки белых вперёд."
    },
    "Английское начало": {
        "moves": ["c2c4"],
        "description": "Фланговый контроль поля d5."
    },
    "Дебют четырёх коней": {
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6"],
        "description": "Симметричное развитие, спокойная игра."
    },
    "Защита двух коней": {
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"],
        "description": "Агрессивный ответ на итальянскую партию."
    },
    "Гамбит Эванса": {
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "b2b4"],
        "description": "Жертва пешки b4 за преимущество в развитии."
    },
    "Русская партия": {
        "moves": ["e2e4", "e7e5", "g1f3", "g8f6"],
        "description": "Чёрные немедленно атакуют пешку e4."
    },
    "Шотландская партия": {
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4"],
        "description": "Белые открывают центр, возникают острые позиции."
    },
    "Венская партия": {
        "moves": ["e2e4", "e7e5", "b1c3"],
        "description": "Белые подготавливают f4."
    },
    "Французская защита": {
        "moves": ["e2e4", "e7e6", "d2d4", "d7d5"],
        "description": "Чёрные укрепляют центр пешкой d5."
    },
    "Скандинавская защита": {
        "moves": ["e2e4", "d7d5"],
        "description": "Чёрные сразу атакуют центр, ферзь выходит рано."
    },
    "Защита Пирца": {
        "moves": ["e2e4", "d7d6", "d2d4", "g8f6", "b1c3", "g7g6"],
        "description": "Чёрные строят фианкетто королевского слона."
    },
    "Голландская защита": {
        "moves": ["d2d4", "f7f5"],
        "description": "Чёрные атакуют на королевском фланге."
    },
    "Староиндийская защита": {
        "moves": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7"],
        "description": "Чёрные фианкеттируют слона, готовят контригру."
    },
    "Новоиндийская защита": {
        "moves": ["d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6"],
        "description": "Чёрные фианкеттируют ферзевого слона."
    },
    "Защита Грюнфельда": {
        "moves": ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5"],
        "description": "Чёрные жертвуют центр, стремясь к контригре."
    },
    "Защита Нимцовича": {
        "moves": ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"],
        "description": "Чёрные связывают коня c3."
    },
    "Защита Бенони": {
        "moves": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6"],
        "description": "Чёрные создают пешечный центр."
    },
    "Волжский гамбит": {
        "moves": ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5"],
        "description": "Жертва пешки b5 за инициативу."
    },
    "Защита Филидора": {
        "moves": ["e2e4", "e7e5", "g1f3", "d7d6"],
        "description": "Укрепление центра чёрными."
    },
    "Защита Петрова": {
        "moves": ["e2e4", "e7e5", "g1f3", "g8f6"],
        "description": "Русская партия, чёрные атакуют e4."
    }
}

# --- МЕНЮ (ИНЛАЙН-КНОПКИ) ---
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Анализ FEN", callback_data="menu_fen")],
        [InlineKeyboardButton("📖 Все дебюты", callback_data="menu_openings")],
        [InlineKeyboardButton("📋 Советы по позиции", callback_data="menu_plan")],
        [InlineKeyboardButton("⚡ Тактика", callback_data="menu_tactics")],
        [InlineKeyboardButton("🎬 GIF дебюта", callback_data="menu_gif")],
        [InlineKeyboardButton("📂 Загрузить PGN", callback_data="menu_pgn")],
        [InlineKeyboardButton("🔄 Пример FEN", callback_data="menu_example_fen")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="menu_main")]])

# --- ГЕНЕРАЦИЯ GIF ---
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

# --- СОВЕТЫ ПО ПОЗИЦИИ ---
def get_position_advice(board: chess.Board) -> str:
    advice = []
    turn = "Белые" if board.turn == chess.WHITE else "Чёрные"
    advice.append(f"Сейчас ход {turn}.")
    if board.is_check():
        advice.append("⚠️ Король под шахом!")
    if board.is_checkmate():
        advice.append("🏆 МАТ! Игра окончена.")
    if board.is_stalemate():
        advice.append("⚖️ Пат! Ничья.")
    if board.turn == chess.WHITE:
        knights = board.knights(chess.WHITE)
        bishops = board.bishops(chess.WHITE)
        developed = sum(1 for sq in knights if sq not in [chess.B1, chess.G1]) + sum(1 for sq in bishops if sq not in [chess.C1, chess.F1])
        if developed < 2:
            advice.append("🐴 Развивайте коней и слонов.")
    else:
        knights = board.knights(chess.BLACK)
        bishops = board.bishops(chess.BLACK)
        developed = sum(1 for sq in knights if sq not in [chess.B8, chess.G8]) + sum(1 for sq in bishops if sq not in [chess.C8, chess.F8])
        if developed < 2:
            advice.append("🐴 Развивайте коней и слонов.")
    return "\n".join(advice) if advice else "Позиция сбалансирована."

# --- ТАКТИКА ---
def find_tactics(board: chess.Board) -> str:
    tactics = []
    for move in board.legal_moves:
        if board.gives_check(move):
            tactics.append(f"⚡ Ход {board.san(move)} даёт шах.")
    if board.is_checkmate():
        tactics.append("🏆 МАТ!")
    if board.is_stalemate():
        tactics.append("⚖️ Пат.")
    return "\n".join(tactics[:5]) if tactics else "⚠️ Явных тактических угроз не обнаружено."

# --- АНАЛИЗ ПОЗИЦИИ (ТОП-3 ХОДА) ---
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
            advice = get_position_advice(board)
            if advice:
                result_text += f"\n📋 {advice}"
            return result_text
    except Exception as e:
        logging.error(f"Ошибка анализа: {e}")
        return f"❌ Ошибка: {e}"

# --- ОБРАБОТЧИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "♟️ **Шахматный справочник**\n\n"
        "Здесь ты найдёшь анализ позиций, дебюты и тактические советы.\n"
        "Выбери действие:",
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📘 **Команды и возможности:**\n"
        "/start – главное меню\n"
        "/opening_gif <название> – GIF-анимация дебюта (можно часть названия)\n"
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "menu_main":
            await query.edit_message_text("♟️ Выбери действие:", reply_markup=get_main_menu())
        elif query.data == "menu_fen":
            await query.edit_message_text(
                "📊 **Анализ позиции по FEN**\nОтправь мне FEN-строку.\nПример:\n`rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`",
                parse_mode='Markdown',
                reply_markup=get_back_button()
            )
        elif query.data == "menu_openings":
            list_text = "📖 **Все дебюты:**\n\n"
            for name, data in OPENINGS.items():
                list_text += f"• **{name}** — {data['description']}\n"
            if len(list_text) > 4000:
                list_text = "📖 Слишком много дебютов, вот названия:\n" + "\n".join(f"• {key}" for key in OPENINGS.keys())
            await query.edit_message_text(list_text, parse_mode='Markdown', reply_markup=get_back_button())
        elif query.data == "menu_plan":
            await query.edit_message_text(
                "📋 **Советы по позиции**\nОтправь FEN-строку.",
                reply_markup=get_back_button()
            )
        elif query.data == "menu_tactics":
            await query.edit_message_text(
                "⚡ **Тактический анализ**\nОтправь FEN-строку.",
                reply_markup=get_back_button()
            )
        elif query.data == "menu_gif":
            list_text = "🎬 **Выбери дебют для GIF:**\n\n"
            for name in OPENINGS:
                list_text += f"• `{name}` — {OPENINGS[name]['description'][:60]}...\n"
            list_text += "\nВведи команду: `/opening_gif Название`\n(можно писать часть названия)"
            await query.edit_message_text(list_text, parse_mode='Markdown', reply_markup=get_back_button())
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
    except Exception as e:
        logging.error(f"Callback error: {e}")
        try:
            await query.message.reply_text("⚠️ Произошла ошибка, попробуй снова.", reply_markup=get_main_menu())
        except:
            pass

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
    try:
        await update.message.reply_text(f"🎬 Генерирую GIF для «{found}»...")
        gif_data = generate_opening_gif(found)
        if gif_data:
            await update.message.reply_animation(
                animation=InputFile(io.BytesIO(gif_data), filename="opening.gif"),
                caption=f"🎬 Дебют: **{found}**\n📖 {OPENINGS[found]['description']}\n(каждый ход показывается {GIF_DURATION} сек)",
                parse_mode='Markdown',
                reply_markup=get_back_button()
            )
        else:
            await update.message.reply_text("❌ Ошибка генерации GIF. Убедись, что установлен cairosvg.", reply_markup=get_back_button())
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
            if data["moves"][0] == first_move:
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
    app.add_handler(CommandHandler("m", move_command))   # сокращение
    app.add_handler(CommandHandler("opening_gif", opening_gif))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fen))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pgn))
    print("✅ Бот запущен (финальная версия).")
    app.run_polling()

if __name__ == "__main__":
    main()
