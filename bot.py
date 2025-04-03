import logging
import csv
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USE_GOOGLE_SHEETS = True
GOOGLE_SHEET_NAME = "Test Anxiety Responses"
SURVEY_EXPIRY_TIME = 180  # 3 minutes

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

if USE_GOOGLE_SHEETS:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(GOOGLE_SHEET_NAME).sheet1

CSV_FILE = "responses.csv"
questions = [
    "I feel anxious before a test.",
    "During a test, I have difficulty concentrating.",
    "I worry about failing tests.",
    "I feel my heart racing during exams.",
    "I feel confident while taking a test."
]
user_responses = {}

def create_rating_keyboard():
    buttons = [InlineKeyboardButton(text=str(i), callback_data=str(i)) for i in range(5, 0, -1)]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    user_responses[user_id] = {"responses": [], "start_time": time.time()}
    await message.answer("Please enter your age:")

@dp.message()
async def handle_age(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_responses and "age" not in user_responses[user_id]:
        if message.text.isdigit():
            user_responses[user_id]["age"] = int(message.text)
            await message.answer("Please select your sex:", reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Male", callback_data="male"),
                     InlineKeyboardButton(text="Female", callback_data="female"),
                     InlineKeyboardButton(text="Other", callback_data="other")]
                ]
            ))
        else:
            await message.answer("Invalid input. Please enter a valid age:")

@dp.callback_query(lambda call: call.data in ["male", "female", "other"])
async def handle_sex(call: types.CallbackQuery):
    user_id = call.from_user.id
    user_responses[user_id]["sex"] = call.data
    await call.answer()
    await call.message.answer("Thank you! Now let's start the test.")
    await ask_question(user_id, 0)

async def ask_question(user_id, index):
    if user_id not in user_responses or time.time() - user_responses[user_id]["start_time"] > SURVEY_EXPIRY_TIME:
        user_responses.pop(user_id, None)
        await bot.send_message(user_id, "Your session has expired. Please restart with /start.")
        return
    
    if index < len(questions):
        await bot.send_message(user_id, f"Q{index+1}: {questions[index]}", reply_markup=create_rating_keyboard())
    else:
        await save_response(user_id)

@dp.callback_query(lambda call: call.data in ["1", "2", "3", "4", "5"])
async def handle_response(call: types.CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_responses or time.time() - user_responses[user_id]["start_time"] > SURVEY_EXPIRY_TIME:
        user_responses.pop(user_id, None)
        await call.answer("Your session has expired. Please restart with /start.")
        return
    
    user_responses[user_id]["responses"].append(call.data)
    await call.answer()
    if len(user_responses[user_id]["responses"]) < len(questions):
        await ask_question(user_id, len(user_responses[user_id]["responses"]))
    else:
        await save_response(user_id)

async def save_response(user_id):
    if user_id not in user_responses or time.time() - user_responses[user_id]["start_time"] > SURVEY_EXPIRY_TIME:
        user_responses.pop(user_id, None)
        await bot.send_message(user_id, "Your session has expired. Please restart with /start.")
        return
    
    completion_time = time.time() - user_responses[user_id]["start_time"]
    response_data = [
        str(user_id),
        str(user_responses[user_id].get("age", "N/A")),
        str(user_responses[user_id].get("sex", "N/A"))
    ] + user_responses[user_id]["responses"] + [str(completion_time)]
    
    if USE_GOOGLE_SHEETS:
        try:
            cell = sheet.find(str(user_id))
            if cell:
                sheet.update(f"A{cell.row}:K{cell.row}", [response_data])
            else:
                sheet.append_row(response_data)
        except gspread.exceptions.CellNotFound:
            sheet.append_row(response_data)
    else:
        with open(CSV_FILE, mode="a", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(response_data)
    
    del user_responses[user_id]
    await bot.send_message(user_id, "Thank you for completing the test! Your responses have been saved.")

async def cleanup_expired_sessions():
    """Removes expired survey sessions every 10 seconds."""
    while True:
        current_time = time.time()
        expired_users = [user_id for user_id, data in user_responses.items() if current_time - data["start_time"] > SURVEY_EXPIRY_TIME]

        for user_id in expired_users:
            del user_responses[user_id]
            try:
                await bot.send_message(user_id, "Your session has expired. Please restart with /start.")
            except Exception:
                pass  # Ignore errors if the user is unavailable

        await asyncio.sleep(10)  # Check every 10 seconds

async def main():
    asyncio.create_task(cleanup_expired_sessions())  # Start cleanup task
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
