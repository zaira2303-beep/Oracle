import asyncio
import random
import os
from vk_teams_async_bot import Bot, Dispatcher, NewMessageEvent, MemoryStorage, FSMContext
from vk_teams_async_bot import CommandFilter, TextFilter, StateFilter
from vk_teams_async_bot import StatesGroup, State

from predictions import PREDICTIONS

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")"
API_URL = "https://api.internal.myteam.mail.ru/bot/v1" 
IMAGES_FOLDER = "images"

# Инициализация
bot = Bot(bot_token=TOKEN, url=API_URL)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
used_users = set() 

class PredictionStates(StatesGroup):
    waiting_for_number = State()

def get_random_image(folder_path):
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    if not os.path.exists(folder_path):
        return None
    all_images = [
        os.path.join(folder_path, f) 
        for f in os.listdir(folder_path) 
        if f.lower().endswith(valid_extensions)
    ]
    if not all_images:
        return None
    return random.choice(all_images)

# Обработчик команды /start
@dp.message(CommandFilter("start"))
async def cmd_start(event: NewMessageEvent, fsm_context: FSMContext):
    user_id = event.chat.chat_id
    
    if user_id in used_users:
        await bot.send_text(
            chat_id=user_id, 
            text="Твое будущее уже предсказано. Второй раз судьба не открывает свои тайны."
        )
        return

    await fsm_context.set_state(PredictionStates.waiting_for_number)
    await bot.send_text(
        chat_id=user_id, 
        text="Привет! Я — древний оракул. Загадай любое число от 1 до 100, и я приоткрою завесу твоего будущего."
    )

# Обработчик текстовых сообщений (чисел)
@dp.message(TextFilter(), StateFilter(PredictionStates.waiting_for_number))
async def process_number(event: NewMessageEvent, fsm_context: FSMContext):
    user_id = event.chat.chat_id
    text = event.text.strip()

    if user_id in used_users:
        await bot.send_text(chat_id=user_id, text="Твое будущее уже предсказано.")
        return

    try:
        number = int(text)
        if not (1 <= number <= 100):
            await bot.send_text(chat_id=user_id, text="Пожалуйста, введи число от 1 до 100.")
            return
    except ValueError:
        await bot.send_text(chat_id=user_id, text="Это не похоже на число. Попробуй еще раз (от 1 до 100).")
        return

    prediction_text = random.choice(PREDICTIONS)
    image_path = get_random_image(IMAGES_FOLDER)

    if image_path is None:
        await bot.send_text(chat_id=user_id, text=f"🔮 Твое предсказание: {prediction_text}")
    else:
        try:
            # В новой версии параметр для файла обычно 'file'
            await bot.send_file(
                chat_id=user_id,
                file=image_path,
                caption=f"🔮 Твое предсказание: {prediction_text}"
            )
        except Exception as e:
            print(f"Ошибка при отправке файла: {e}")
            await bot.send_text(chat_id=user_id, text=f"🔮 Твое предсказание: {prediction_text}")

    used_users.add(user_id)
    await fsm_context.clear()

async def main():
    print("Бот запущен...")
    # В новой версии используется контекстный менеджер для запуска
    async with bot:
        await bot.start_polling(dp)

if __name__ == "__main__":
    asyncio.run(main())
