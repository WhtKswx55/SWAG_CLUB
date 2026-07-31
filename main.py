import logging
import os
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
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

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "300"))
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "150"))

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


def invoice_params(months: int) -> dict:
    if PAYMENT_PROVIDER_TOKEN:
        amount = SUBSCRIPTION_PRICE_RUB * months
        return {
            "provider_token": PAYMENT_PROVIDER_TOKEN,
            "currency": "RUB",
            "prices": [LabeledPrice(label=f"Подписка SWAG CLUB — {months} мес.", amount=amount * 100)],
        }
    amount = SUBSCRIPTION_PRICE_STARS * months
    return {
        "provider_token": "",
        "currency": "XTR",
        "prices": [LabeledPrice(label=f"Подписка SWAG CLUB — {months} мес.", amount=amount)],
    }


def status_text(status: dict) -> str:
    if not status["has_access"]:
        return "Статус: **ZERO ACCESS**\nПодписки нет. Оформи, чтобы открыть каталог."

    lines = [
        f"Уровень: **{status['level_name']}**",
        f"Стаж подписки: {status['tenure_months']} мес.",
        f"Активна до: {status['active_until'][:10]} ({status['days_left']} дн. осталось)",
    ]
    if status["next_level"]:
        lines.append(f"До уровня «{status['next_level']}»: {status['months_to_next_level']} мес.")
    else:
        lines.append("Это максимальный уровень.")
    return "\n".join(lines)

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
    status = await db.get_status(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    await message.answer(status_text(status), parse_mode="Markdown")


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    params = invoice_params(months=1)
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Подписка SWAG CLUB — 1 месяц",
        description=(
            "Открывает программу лояльности: ранний доступ к каталогу, "
            "бронь серийных номеров, секретные дропы и статусы — по мере стажа подписки."
        ),
        payload="sub_1",
        **params,
    )


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    payload = payment.invoice_payload or "sub_1"
    try:
        months = int(payload.split("_")[1])
    except (IndexError, ValueError):
        months = 1

    status = await db.extend_subscription(
        message.from_user.id,
        months=months,
        amount=payment.total_amount,
        currency=payment.currency,
        charge_id=payment.telegram_payment_charge_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    streak_note = "" if status.get("streak_kept", True) else "\n_(стаж начат заново — подписка стояла дольше грейс-периода)_"
    await message.answer(
        f"Оплата прошла ✅\n\n{status_text(status)}{streak_note}",
        parse_mode="Markdown",
    )


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Набери /start, чтобы открыть SWAG CLUB, или /subscribe, чтобы оформить подписку.")

def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "message": message}, status=status)


async def api_status(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    status = await db.get_status(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
    pricing = {
        "uses_stars": not bool(PAYMENT_PROVIDER_TOKEN),
        "price_rub": SUBSCRIPTION_PRICE_RUB,
        "price_stars": SUBSCRIPTION_PRICE_STARS,
    }
    return web.json_response({"ok": True, **status, **pricing})


async def api_create_invoice_link(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    months = int(body.get("months", 1) or 1)
    params = invoice_params(months)

    try:
        link = await bot.create_invoice_link(
            title=f"Подписка SWAG CLUB — {months} мес.",
            description=(
                "Открывает программу лояльности: ранний доступ к каталогу, "
                "бронь серийных номеров, секретные дропы и статусы."
            ),
            payload=f"sub_{months}",
            **params,
        )
    except Exception as e:
        log.error("Ошибка создания инвойса: %s", e)
        return _json_error("Не получилось создать счёт на оплату", status=500)

    return web.json_response({"ok": True, "link": link})


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")

async def on_startup(app: web.Application) -> None:
    await db.init_db()
    log.info("Установка Webhook на адрес: %s", WEBHOOK_URL)
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
        allowed_updates=["message", "pre_checkout_query"],
    )


async def on_shutdown(app: web.Application) -> None:
    log.info("Завершение работы: закрываем сессию бота...")
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/api/status", api_status)
    app.router.add_post("/api/create-invoice-link", api_create_invoice_link)

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