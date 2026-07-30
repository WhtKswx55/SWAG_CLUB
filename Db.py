import logging
import os
import json
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import db
from security import extract_tg_user

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


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


# ---------------------------------------------------------------------------
# Команды бота
# ---------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
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


@dp.message(Command("mystatus"))
async def cmd_mystatus(message: Message) -> None:
    status = await db.get_status(message.from_user.id)
    if status["has_access"]:
        await message.answer(
            f"Твой уровень: **{status['level_name']}**\n"
            f"Доступ к товарам открыт ✅",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "У тебя пока нет доступа к дропам.\n"
            "Введи код раннего доступа в приложении, чтобы открыть каталог."
        )


@dp.message(Command("gencode"))
async def cmd_gencode(message: Message) -> None:
    """Админ-команда: /gencode <level> [название дропа]
    level: 1 = Early Access, 2 = VIP, 3 = Inner Circle
    Пример: /gencode 1 Хапаровск дроп 02
    """
    if not is_admin(message.from_user.id):
        await message.answer("Команда недоступна.")
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Формат: /gencode <уровень 1-3> [название дропа]\n"
            "1 — Early Access, 2 — VIP, 3 — Inner Circle\n"
            "Пример: /gencode 1 Хапаровск дроп 02"
        )
        return

    level = int(parts[1])
    drop_name = parts[2].strip() if len(parts) > 2 else None

    if level not in (1, 2, 3):
        await message.answer("Уровень должен быть 1, 2 или 3.")
        return

    try:
        code = await db.create_code(level, drop_name)
    except Exception as e:
        log.error("Ошибка генерации кода: %s", e)
        await message.answer("Не получилось сгенерировать код, попробуй ещё раз.")
        return

    level_name = db.LEVELS[level]
    label = f" ({drop_name})" if drop_name else ""
    await message.answer(
        f"Новый код{label}\n"
        f"Уровень: **{level_name}**\n"
        f"Код: `{code}`\n\n"
        f"Одноразовый — сгорает после первого ввода.",
        parse_mode="Markdown",
    )


@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message) -> None:
    # Основная логика кодов теперь идёт через /api/redeem (fetch из WebApp),
    # этот хендлер оставлен как запасной путь и для события успешного входа
    # через Telegram-кнопку (без кода).
    try:
        raw_data = message.web_app_data.data
        data = json.loads(raw_data)
        via = data.get("via")

        if via == "telegram":
            await db.get_or_create_user(
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
            )
            user_name = message.from_user.first_name if message.from_user else "друг"
            await message.answer(
                f"**Добро пожаловать в закрытый фан-клуб, {user_name}!**",
                parse_mode="Markdown",
            )
    except Exception as e:
        log.error("Ошибка при разборе web_app_data: %s", e)


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Набери /start, чтобы открыть SWAG CLUB.")


# ---------------------------------------------------------------------------
# HTTP API для WebApp (проверка статуса, погашение кода)
# ---------------------------------------------------------------------------

def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "message": message}, status=status)


async def api_status(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    init_data = body.get("initData", "")
    tg_user = extract_tg_user(init_data, BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    status = await db.get_status(tg_user["id"])
    return web.json_response({"ok": True, **status})


async def api_redeem(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    init_data = body.get("initData", "")
    code = (body.get("code") or "").strip()

    if not code:
        return _json_error("Введите код")

    tg_user = extract_tg_user(init_data, BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    result = await db.redeem_code(
        tg_user["id"],
        code,
        tg_user.get("username"),
        tg_user.get("first_name"),
    )
    return web.json_response(result)


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


# ---------------------------------------------------------------------------
# Настройка приложения
# ---------------------------------------------------------------------------

async def on_startup(app: web.Application) -> None:
    await db.init_db()
    log.info("Установка Webhook на адрес: %s", WEBHOOK_URL)
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )


async def on_shutdown(app: web.Application) -> None:
    log.info("Завершение работы: закрываем сессию бота...")
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/api/status", api_status)
    app.router.add_post("/api/redeem", api_redeem)

    web_dir = Path(__file__).parent / "WEB"
    if web_dir.exists():
        app.router.add_static("/WEB/", path=web_dir, name="web")
    else:
        log.warning("Папка WEB не найдена! WebApp не сможет загрузить HTML.")

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)