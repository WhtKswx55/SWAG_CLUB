import logging
import os
import json
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# cnfg
BOT_TOKEN = os.getenv("BOT_TOKEN", "8860971431:AAH3FMBFI_8SydrjDAOUapNdVnOrgSemDmM")
BASE_URL = os.getenv("BASE_URL", "https://swagclubea-bot.onrender.com").rstrip("/")
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://swagclubea-bot.onrender.com/WEB/index2.html"
)

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "7240769536").split(",")
    if x.strip().isdigit()
]

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}" if BOT_TOKEN else "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("swagclub-bot")

if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не установлена!")

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


# === НОВЫЙ БЛОК: ОБРАБОТКА ДАННЫХ ИЗ WEBAPP ===
@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message) -> None:
    try:
        raw_data = message.web_app_data.data
        data = json.loads(raw_data)

        via = data.get('via')  # 'telegram' или 'code'

        if via == 'code':
            drop = data.get('drop', 'Эксклюзивный дроп')
            code = data.get('code')
            await message.answer(
                f"✅ **Код {code} успешно активирован!**\n\n"
                f"Вам открыт доступ к: **{drop}**",
                parse_mode="Markdown"
            )
        else:
            user_name = message.from_user.first_name
            await message.answer(
                f"🔥 **Добро пожаловать в закрытый фан-клуб, {user_name}!**\n\n"
                f"Вы успешно авторизовались.",
                parse_mode="Markdown"
            )
    except Exception as e:
        log.error("Ошибка при разборе web_app_data: %s", e)
        await message.answer("Произошла ошибка при обработке данных.")


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Набери /start, чтобы открыть SWAG CLUB.")


async def on_startup(app: web.Application) -> None:
    if not BASE_URL:
        log.warning("BASE_URL не задан, вебхук не зарегистрирован!")
        return

    try:
        await bot.set_webhook(
            WEBHOOK_URL,
            drop_pending_updates=True,
        )
        log.info("Webhook успешно установлен: %s", WEBHOOK_URL)
    except Exception as e:
        log.error("Ошибка при установке Webhook: %s", e)


async def on_shutdown(app: web.Application) -> None:
    try:
        await bot.delete_webhook()
        log.info("Webhook удален")
    except Exception as e:
        log.error("Ошибка при удалении Webhook: %s", e)


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)

    web_dir = Path(__file__).parent / "WEB"
    if web_dir.exists():
        app.router.add_static("/WEB/", path=web_dir, name="web")
    else:
        log.warning("Папка WEB не найдена! WebApp не сможет загрузить HTML.")

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)