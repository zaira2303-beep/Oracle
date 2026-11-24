import asyncio
import json
import logging
import os
import random

from vkworkspace import Bot, Dispatcher, Router
from vkworkspace.exceptions import InvalidToken, VKTeamsAPIError
from vkworkspace.filters import Command
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.fsm.storage.memory import MemoryStorage
from vkworkspace.types import InputFile, Message

from predictions import PREDICTIONS

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("oracle")

IMAGES_FOLDER = "images"
USED_USERS_FILE = "used_users.json"

PREDICTION_EMOJI = ["🔮", "✨", "🌟", "🎁", "🍀", "🪄", "💫", "🌠"]
GREETING_EMOJI = ["👋", "🔮", "✨", "🌟"]


def load_dotenv(path=".env"):
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


def clean_env_value(value):
    value = (value or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value.replace("\n", "").replace("\r", "").strip()


def build_api_url(raw):
    """vkworkspace ждёт базовый URL вместе с /bot/v1."""
    url = clean_env_value(raw) or "https://api.internal.myteam.mail.ru"
    url = url.rstrip("/")
    if url.endswith("/bot/v1"):
        return url
    if url.endswith("/botapi"):
        url = url[: -len("/botapi")]
    return url + "/bot/v1"


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

BOT_API_URL = build_api_url(os.getenv("BOT_API_URL"))
used_users = load_used_users()

router = Router(name="oracle")


class PredictionStates(StatesGroup):
    waiting_for_number = State()


async def deliver_prediction(message: Message, user_id: str) -> None:
    prediction_text = random.choice(PREDICTIONS)
    caption = f"{random.choice(PREDICTION_EMOJI)} Твое предсказание: {prediction_text}"
    image_path = get_random_image(IMAGES_FOLDER)

    if image_path is None:
        await message.answer(caption)
    else:
        try:
            await message.answer_file(file=InputFile(image_path), caption=caption)
        except Exception as e:
            log.warning("Не удалось отправить файл %s: %s", image_path, e)
            await message.answer(caption)

    used_users.add(user_id)
    save_used_users(used_users)


async def start_dialogue(message: Message, state: FSMContext, user_id: str) -> None:
    if user_id in used_users:
        await message.answer(
            "Твое будущее уже предсказано. Второй раз судьба не открывает свои тайны."
        )
        return

    await state.set_state(PredictionStates.waiting_for_number)
    await message.answer(
        f"{random.choice(GREETING_EMOJI)} Привет! Я — древний оракул. "
        "Загадай любое число от 1 до 100, и я приоткрою завесу твоего будущего."
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.user_id if message.from_user else message.chat.chat_id
    log.info("/start от %s (chat_id=%s)", user_id, message.chat.chat_id)
    await start_dialogue(message, state, user_id)


@router.message(StateFilter(PredictionStates.waiting_for_number))
async def process_number(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.user_id if message.from_user else message.chat.chat_id
    text = (message.text or "").strip()

    if user_id in used_users:
        await message.answer("Твое будущее уже предсказано.")
        return

    try:
        number = int(text)
        if not 1 <= number <= 100:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи число от 1 до 100.")
        return

    await deliver_prediction(message, user_id)
    await state.clear()


@router.message(StateFilter(None))
async def first_contact(message: Message, state: FSMContext) -> None:
    """Любое первое сообщение пользователя запускает диалог — /start не обязателен."""
    user_id = message.from_user.user_id if message.from_user else message.chat.chat_id
    text = (message.text or "").strip()

    if user_id not in used_users and text.isdigit() and 1 <= int(text) <= 100:
        log.info("Первое сообщение числом %s от %s — сразу выдаю предсказание", text, user_id)
        await deliver_prediction(message, user_id)
        return

    await start_dialogue(message, state, user_id)


@router.error()
async def on_error(event, error: Exception) -> None:
    log.exception("Ошибка обработки события: %s", error)


async def main():
    bot = Bot(token=BOT_TOKEN, api_url=BOT_API_URL)
    dp = Dispatcher(storage=MemoryStorage(), session_timeout=3600)
    dp.include_router(router)

    @dp.on_startup
    async def on_startup():
        log.info("Бот запущен")
        log.info("Сервер: %s, токен: длина %d, начинается на %s…",
                 BOT_API_URL, len(BOT_TOKEN), BOT_TOKEN[:4])
        try:
            me = await bot.get_me()
        except (InvalidToken, VKTeamsAPIError) as e:
            log.error(
                "Сервер %s отклонил токен: %s\n"
                "Проверь: 1) это токен именно этого бота; 2) бот создан на том же сервере "
                "(BOT_API_URL); 3) токен не отозван и скопирован без кавычек и переносов.",
                BOT_API_URL, e,
            )
            raise SystemExit(1) from e
        log.info("Подключён как %s (%s)", me.nick, me.user_id)
        log.info("Ожидание сообщений")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        log.error("Остановка: %s", e)
