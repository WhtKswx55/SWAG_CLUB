import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8860971431:AAH3FMBFI_8SydrjDAOUapNdVnOrgSemDmM")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-app.vercel.app")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть SWAG CLUB",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "Добро пожаловать в SWAG CLUB.\n\n"
        "Жми кнопку ниже, чтобы попасть в закрытый каталог.",
        reply_markup=kb,
    )


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Набери /start, чтобы открыть SWAG CLUB.")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())