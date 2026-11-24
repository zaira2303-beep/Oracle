import asyncio
import json
import logging
import os
import random

from vk_teams_async_bot import (
    Bot,
    CommandFilter,
    Dispatcher,
    FSMContext,
    MemoryStorage,
    NewMessageEvent,
    State,
    StateFilter,
    StatesGroup,
)
from vk_teams_async_bot.errors import APIError

from predictions import PREDICTIONS

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("oracle")

# --- НАСТРОЙКИ ---
IMAGES_FOLDER = "images"
USED_USERS_FILE = "used_users.json"


def load_dotenv(path=".env"):
    """Минимальная загрузка .env без внешних зависимостей."""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError as e:
        log.warning("Не удалось прочитать %s: %s", path, e)


def normalize_api_url(url):
    """Библиотека сама добавляет /bot/v1, поэтому убираем хвост из URL."""
    if not url:
        return url
    url = url.rstrip("/")
    if url.endswith("/bot/v1"):
        url = url[: -len("/bot/v1")]
    return url


def clean_env_value(value):
    """Убирает кавычки и пробелы, которые попадают из .env / docker-compose."""
    value = (value or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value.replace("\n", "").replace("\r", "").strip()


load_dotenv()

BOT_TOKEN = clean_env_value(os.getenv("BOT_TOKEN"))
if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан: добавь BOT_TOKEN=<токен Метабота> в .env "
        "или передай его переменной окружения контейнера."
    )
if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА" or len(BOT_TOKEN) < 20:
    raise SystemExit(
        "BOT_TOKEN выглядит как заглушка или обрезан "
        f"(длина {len(BOT_TOKEN)}, ожидается полный токен из Метабота)."
    )

BOT_API_URL = normalize_api_url(
    clean_env_value(os.getenv("BOT_API_URL")) or "https://api.internal.myteam.mail.ru"
)

bot = Bot(bot_token=BOT_TOKEN, url=BOT_API_URL)
log.info(
    "Сервер: %s, токен: длина %d, начинается на %s…",
    BOT_API_URL, len(BOT_TOKEN), BOT_TOKEN[:4],
)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЕ «УЖЕ ГАДАЛИ» (переживает рестарт) ---
def load_used_users():
    try:
        with open(USED_USERS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as e:
        log.warning("Не удалось прочитать %s: %s", USED_USERS_FILE, e)
        return set()


def save_used_users(users):
    try:
        with open(USED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(users), f, ensure_ascii=False)
    except OSError as e:
        log.warning("Не удалось сохранить %s: %s", USED_USERS_FILE, e)


used_users = load_used_users()


class PredictionStates(StatesGroup):
    waiting_for_number = State()


def get_random_image(folder_path):
    valid_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    if not os.path.isdir(folder_path):
        log.warning("Папка с картинками не найдена: %s", folder_path)
        return None
    all_images = [
        os.path.join(folder_path, name)
        for name in os.listdir(folder_path)
        if name.lower().endswith(valid_extensions)
    ]
    if not all_images:
        log.warning("В папке %s нет изображений", folder_path)
        return None
    return random.choice(all_images)


@dp.message(CommandFilter("start"))
async def cmd_start(event: NewMessageEvent, fsm_context: FSMContext):
    user_id = event.from_.user_id
    log.info("/start от %s (chat_id=%s)", user_id, event.chat.chat_id)

    if user_id in used_users:
        await bot.send_text(
            chat_id=event.chat.chat_id,
            text="Твое будущее уже предсказано. Второй раз судьба не открывает свои тайны.",
        )
        return

    await fsm_context.set_state(PredictionStates.waiting_for_number)
    await bot.send_text(
        chat_id=event.chat.chat_id,
        text="Привет! Я — древний оракул. Загадай любое число от 1 до 100, и я приоткрою завесу твоего будущего.",
    )


@dp.message(StateFilter(PredictionStates.waiting_for_number))
async def process_number(event: NewMessageEvent, fsm_context: FSMContext):
    user_id = event.from_.user_id
    text = (event.text or "").strip()

    if user_id in used_users:
        await bot.send_text(chat_id=event.chat.chat_id, text="Твое будущее уже предсказано.")
        return

    try:
        number = int(text)
        if not 1 <= number <= 100:
            raise ValueError
    except ValueError:
        await bot.send_text(
            chat_id=event.chat.chat_id,
            text="Пожалуйста, введи число от 1 до 100.",
        )
        return

    prediction_text = random.choice(PREDICTIONS)
    image_path = get_random_image(IMAGES_FOLDER)

    if image_path is None:
        await bot.send_text(
            chat_id=event.chat.chat_id, text=f"🔮 Твое предсказание: {prediction_text}"
        )
    else:
        try:
            await bot.send_file(
                chat_id=event.chat.chat_id,
                file=image_path,
                caption=f"🔮 Твое предсказание: {prediction_text}",
            )
        except Exception as e:
            log.warning("Не удалось отправить файл %s: %s", image_path, e)
            await bot.send_text(
                chat_id=event.chat.chat_id, text=f"🔮 Твое предсказание: {prediction_text}"
            )

    used_users.add(user_id)
    save_used_users(used_users)
    await fsm_context.clear()


@dp.message(StateFilter(None))
async def ask_to_start(event: NewMessageEvent):
    await bot.send_text(
        chat_id=event.chat.chat_id,
        text="Напиши /start, чтобы узнать предсказание.",
    )


async def main():
    log.info("Бот запущен")
    async with bot:
        try:
            me = await bot.get_self()
        except APIError as e:
            log.error(
                "Сервер %s отклонил токен: %s\n"
                "Проверь: 1) это токен именно этого бота; 2) бот создан на том же сервере "
                "(BOT_API_URL); 3) токен не отозван и скопирован без кавычек и переносов.",
                BOT_API_URL, e,
            )
            raise SystemExit(1) from e
        log.info("Подключён как %s (%s)", me.nick, me.user_id)
        log.info("Ожидание сообщений")
        await bot.start_polling(dp)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        log.error("Остановка: %s", e)
