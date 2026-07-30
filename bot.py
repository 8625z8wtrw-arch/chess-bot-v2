import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import chess
import chess.engine
from config import TELEGRAM_TOKEN

logging.basicConfig(level=logging.INFO)

# Путь к Stockfish (проверь!)
ENGINE_PATH = "/opt/homebrew/bin/stockfish"

async def analyze_position(fen: str) -> str:
    try:
        board = chess.Board(fen)
        with chess.engine.SimpleEngine.popen_uci(ENGINE_PATH) as engine:
            info = engine.analyse(board, chess.engine.Limit(time=2.0))
            score = info.get("score")
            if score is None:
                eval_text = "Оценка не определена"
            elif score.is_mate():
                eval_text = f"Мат {'за' if score.mate() > 0 else 'против'} белых в {abs(score.mate())} ходов"
            else:
                cp = score.relative.score()
                if cp is None:
                    eval_text = "Оценка не определена"
                else:
                    eval_text = f"{cp / 100:.2f} пешки {'в пользу белых' if cp >= 0 else 'в пользу чёрных'}"
            best_move = info.get("pv")[0] if info.get("pv") else None
            best_move_san = board.san(best_move) if best_move else "не найден"
            return f"📊 **Оценка**: {eval_text}\n🏆 **Лучший ход**: {best_move_san}"
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return f"❌ Ошибка: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я шахматный бот. ♟️\n"
        "Отправь мне FEN-строку, и я проанализирую позицию движком Stockfish."
    )

async def handle_fen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fen_text = update.message.text.strip()
    try:
        chess.Board(fen_text)
    except ValueError:
        await update.message.reply_text("❌ Неверный формат FEN.")
        return
    await update.message.reply_text("🤔 Анализирую...")
    result = await analyze_position(fen_text)
    await update.message.reply_text(result, parse_mode='Markdown')

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fen))
    print("✅ Бот запущен с движком Stockfish.")
    app.run_polling()

if __name__ == "__main__":
    main()


