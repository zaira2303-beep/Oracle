import asyncio
import random
import os
from vk_teams_async_bot.bot import Bot
from vk_teams_async_bot.events import Event
from vk_teams_async_bot.filter import Filter
from vk_teams_async_bot.handler import CommandHandler, MessageHandler
from vk_teams_async_bot.fsm.storage.memory import MemoryStorage
from vk_teams_async_bot.fsm.context import FSMContext
from vk_teams_async_bot.fsm.state import State, StatesGroup

from predictions import PREDICTIONS  # Импортируем список предсказаний

# --- НАСТРОЙКИ ---
TOKEN = "ВАШ_ТОКЕН_БОТА"
API_URL = "https://myteam.mail.ru" 
IMAGES_FOLDER = "images" # Папка с картинками

storage = MemoryStorage()
used_users = set() 

bot = Bot(bot_token=TOKEN, url=API_URL)

class PredictionStates(StatesGroup):
    waiting_for_number = State()

# Функция для получения случайной картинки
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

@bot.dispatcher.message(CommandHandler("start"))
async def cmd_start(event: Event, state: FSMContext):
    user_id = event.chat.chatId
    
    if user_id in used_users:
        await bot.send_text(
            chat_id=user_id, 
            text="Твое будущее уже предсказано. Второй раз судьба не открывает свои тайны."
        )
        return

    await state.set_state(PredictionStates.waiting_for_number)
    await bot.send_text(
        chat_id=user_id, 
        text="Привет! Я — древний оракул. Загадай любое число от 1 до 100, и я приоткрою завесу твоего будущего."
    )

@bot.dispatcher.message(MessageHandler(), state=PredictionStates.waiting_for_number)
async def process_number(event: Event, state: FSMContext):
    user_id = event.chat.chatId
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

    # --- ВЫБОР ПРЕДСКАЗАНИЯ И КАРТИНКИ ---
    prediction_text = random.choice(PREDICTIONS)
    image_path = get_random_image(IMAGES_FOLDER)

    if image_path is None:
        # Если картинок нет, отправляем только текст
        await bot.send_text(chat_id=user_id, text=f"🔮 Твое предсказание: {prediction_text}")
    else:
        try:
            await bot.send_file(
                chat_id=user_id,
                file=image_path, # Библиотека принимает путь к файлу
                caption=f"🔮 Твое предсказание: {prediction_text}"
            )
        except Exception as e:
            print(f"Ошибка при отправке файла: {e}")
            await bot.send_text(chat_id=user_id, text=f"🔮 Твое предсказание: {prediction_text}")

    used_users.add(user_id)
    await state.clear()

async def main():
    print("Бот запущен...")
    await bot.start_polling()

if __name__ == "__main__":
    asyncio.run(main())