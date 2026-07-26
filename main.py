import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


BOT_TOKEN = os.getenv("BOT_TOKEN", "8860971431:AAH3FMBFI_8SydrjDAOUapNdVnOrgSemDmM")

BASE_URL = os.getenv("BASE_URL", "https://swagclubea-bot.onrender.com").rstrip("/")

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://swagclubea-bot.onrender.com/WEB/index.html")

ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "7240769536").split(",") if x.strip().isdigit()
]
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("swagclub-bot")

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


async def on_startup(app: web.Application) -> None:
    if not BASE_URL:
        log.warning(
            "BASE_URL is not set — webhook will NOT be registered. "
            "Set it to your Render service URL after first deploy."
        )
        return

    await bot.set_webhook(
        WEBHOOK_URL,
        drop_pending_updates=True,
    )
    log.info("Webhook set to %s", WEBHOOK_URL)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "Бот запущен и слушает webhook.")
        except Exception as e:
            log.warning("Could not notify admin %s: %s", admin_id, e)


async def on_shutdown(app: web.Application) -> None:
    await bot.delete_webhook()
    log.info("Webhook removed")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)