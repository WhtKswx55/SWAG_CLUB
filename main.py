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
    CallbackQuery,
    BotCommand,
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


def status_text(status: dict) -> str:
    if not status or not status.get("has_access"):
        return "❌ **Подписка не активна**\nСтатус: `ZERO ACCESS`\n\nОформи подписку, чтобы открыть каталог."

    return (
        f"✅ **Подписка активна**\n"
        f"Уровень: **{status.get('level_name', 'Member')}**\n"
        f"Стаж подписки: {status.get('tenure_months', 0)} мес.\n"
        f"Активна до: {str(status.get('active_until', ''))[:10]} ({status.get('days_left', 0)} дн. осталось)"
    )


def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 месяц — 150 ⭐", callback_data="buy_1")],
            [InlineKeyboardButton(text="3 месяца — 420 ⭐", callback_data="buy_3")],
            [InlineKeyboardButton(text="6 месяцев — 800 ⭐", callback_data="buy_6")],
            [InlineKeyboardButton(text="12 месяцев — 1500 ⭐", callback_data="buy_12")],
        ]
    )


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="🏠 Главное меню и каталог"),
        BotCommand(command="subscribe", description="💎 Оформить или продлить подписку"),
        BotCommand(command="mystatus", description="📊 Мой статус и уровень в клубе"),
    ]
    await bot.set_my_commands(commands)


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
                    text="**Открыть SWAG CLUB**",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Подписка",
                    callback_data="menu_subscribe",
                ),
                InlineKeyboardButton(
                    text="Мой статус",
                    callback_data="menu_status",
                ),
            ],
        ]
    )
    await message.answer(
        "Добро пожаловать в **SWAG CLUB**.\n\n"
        "Жми кнопку ниже, чтобы попасть в закрытый каталог.",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(Command("mystatus"))
async def cmd_mystatus(message: Message) -> None:
    status = await db.get_status(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    await message.answer(status_text(status), parse_mode="Markdown")


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await message.answer(
        "💎 **Оформление подписки SWAG CLUB**\n\nВыберите срок подписки:",
        reply_markup=get_subscribe_keyboard(),
        parse_mode="Markdown",
    )


@dp.message(Command("testsub"))
async def cmd_testsub(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    months = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1

    status = await db.extend_subscription(
        tg_id=message.from_user.id,
        months=months,
        amount=0,
        currency="TEST",
        charge_id="test_charge",
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(
        f"🛠 **Тестовая подписка выдана на {months} мес.**\n\n{status_text(status)}",
        parse_mode="Markdown",
    )


@dp.callback_query(F.data == "menu_subscribe")
async def cb_menu_subscribe(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "💎 **Оформление подписки SWAG CLUB**\n\nВыберите срок подписки:",
        reply_markup=get_subscribe_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_status")
async def cb_menu_status(callback: CallbackQuery) -> None:
    status = await db.get_status(
        callback.from_user.id, callback.from_user.username, callback.from_user.first_name
    )
    await callback.message.answer(status_text(status), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy(callback: CallbackQuery) -> None:
    months = int(callback.data.split("_")[1])
    prices_map = {1: 150, 3: 420, 6: 800, 12: 1500}
    amount = prices_map.get(months, 150)

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=f"Подписка SWAG CLUB — {months} мес.",
        description="Ранний доступ к закрытому каталогу, бронь номеров и статусы в клубе.",
        payload=f"sub_{months}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{months} мес. подписки", amount=amount)],
    )
    await callback.answer()


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

    prices_map = {1: 150, 3: 420, 6: 800, 12: 1500}
    amount = prices_map.get(months, 150)

    try:
        link = await bot.create_invoice_link(
            title=f"Подписка SWAG CLUB — {months} мес.",
            description="Ранний доступ к закрытому каталогу, бронь номеров и статусы.",
            payload=f"sub_{months}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{months} мес. подписки", amount=amount)],
        )
    except Exception as e:
        log.error("Ошибка создания инвойса: %s", e)
        return _json_error("Не получилось создать счёт на оплату", status=500)

    return web.json_response({"ok": True, "link": link})


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def on_startup(app: web.Application) -> None:
    await db.init_db()
    await setup_bot_commands(bot)
    log.info("Установка Webhook на адрес: %s", WEBHOOK_URL)
    # Убрали жесткое ограничение allowed_updates, чтобы callback_query доходили до бота
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
    )


async def on_shutdown(app: web.Application) -> None:
    log.info("Завершение работы: закрываем сессию бота...")
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/api/status", api_status)
    app.router.add_post("/api/create-invoice-link", api_create_invoice_link)
    app.router.add_get("/auth.js", lambda request: web.FileResponse(Path(__file__).parent / "auth.js"))

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