import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    CallbackQuery,
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


def status_text(status: dict) -> str:
    if not status or not status.get("has_access"):
        return "❌ **Подписка не активна**\nСтатус: `ZERO ACCESS`\n\nОформи подписку, чтобы открыть каталог."

    return (
        f"✅ **Подписка активна**\n"
        f"Уровень: **{status.get('level_name', 'Member')}**\n"
        f"Стаж подписки: {status.get('tenure_months', 0)} мес.\n"
        f"Активна до: {str(status.get('active_until', ''))[:10]} ({status.get('days_left', 0)} дн. осталось)"
    )


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 Подписка"), KeyboardButton(text="📊 Мой статус")]
        ],
        resize_keyboard=True,
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


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    webapp_kb = InlineKeyboardMarkup(
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
        "Добро пожаловать в **SWAG CLUB**.\n\n"
        "Используйте кнопки меню внизу или откройте каталог ниже:",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown",
    )

    await message.answer(
        "Нажмите кнопку, чтобы зайти в закрытый каталог:",
        reply_markup=webapp_kb,
    )


@dp.message(Command("mystatus"), F.text.in_({"📊 Мой статус", "Мой статус"}))
@dp.message(F.text == "📊 Мой статус")
async def text_mystatus(message: Message) -> None:
    status = await db.get_status(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    await message.answer(status_text(status), parse_mode="Markdown")


@dp.message(Command("subscribe"), F.text.in_({"💎 Подписка"}))
@dp.message(F.text == "💎 Подписка")
async def text_subscribe(message: Message) -> None:
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

    code = await db.generate_access_code(
        months=months,
        note="testsub",
        created_by=message.from_user.id,
    )

    await message.answer(
        f"🎟 **Тестовый код доступа сгенерирован**\n\n"
        f"Код: `{code}`\n"
        f"Срок: {months} мес.\n\n"
        f"Передай этот код тестовому пользователю — он вводит его в приложении "
        f"(кнопка «у меня есть код доступа» на входе или «Ввести новый код подписки» в профиле). "
        f"Код одноразовый и привязывается к тому, кто его активирует.",
        parse_mode="Markdown",
    )


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

    streak_note = "" if status.get("streak_kept",
                                   True) else "\n_(стаж начат заново — подписка стояла дольше грейс-периода)_"
    await message.answer(
        f"Оплата прошла ✅\n\n{status_text(status)}{streak_note}",
        parse_mode="Markdown",
    )


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer(
        "Используйте кнопки меню ниже или команду /start для доступа к SWAG CLUB.",
        reply_markup=get_main_reply_keyboard()
    )


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


async def api_redeem_code(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    code = str(body.get("code", "")).strip()
    if not code:
        return _json_error("Введите код")

    result = await db.redeem_code(
        tg_user["id"], code, tg_user.get("username"), tg_user.get("first_name")
    )

    if result.get("ok"):
        try:
            await bot.send_message(
                tg_user["id"],
                f"✅ Код `{result.get('code')}` активирован.\n\n{status_text(result)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            log.warning("Не удалось отправить подтверждение кода: %s", e)

    return web.json_response(result)


async def api_create_order(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not tg_user:
        return _json_error("Не удалось подтвердить Telegram-аккаунт", status=401)

    required_fields = [
        "telegram_handle", "first_name", "last_name", "country",
        "city", "address", "has_pvz", "phone", "email",
    ]
    missing = [f for f in required_fields if not str(body.get(f, "")).strip()]
    if missing:
        return _json_error("Заполните все обязательные поля")

    if not body.get("agree"):
        return _json_error("Нужно подтвердить согласие с условиями")

    options = body.get("options") or {}
    order_row = {
        "tg_id": tg_user["id"],
        "username": tg_user.get("username"),
        "product": body.get("product", "—"),
        "price": body.get("price", 0),
        "options_json": json.dumps(options, ensure_ascii=False),
        "telegram_handle": body.get("telegram_handle"),
        "first_name": body.get("first_name"),
        "last_name": body.get("last_name"),
        "country": body.get("country"),
        "city": body.get("city"),
        "address": body.get("address"),
        "has_pvz": body.get("has_pvz"),
        "phone": body.get("phone"),
        "email": body.get("email"),
    }

    order_id = await db.create_order(order_row)

    options_lines = "\n".join(f"• {k}: {v}" for k, v in options.items()) or "—"
    admin_text = (
        f"🛍 **Новый заказ #{order_id}**\n\n"
        f"Товар: **{order_row['product']}**\n"
        f"Цена: {order_row['price']} ₽\n"
        f"Опции:\n{options_lines}\n\n"
        f"Telegram: {order_row['telegram_handle']} (id {tg_user['id']})\n"
        f"Имя: {order_row['first_name']} {order_row['last_name']}\n"
        f"Страна/город: {order_row['country']}, {order_row['city']}\n"
        f"Адрес: {order_row['address']}\n"
        f"ПВЗ Яндекс: {order_row['has_pvz']}\n"
        f"Телефон: {order_row['phone']}\n"
        f"Email: {order_row['email']}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode="Markdown")
        except Exception as e:
            log.warning("Не удалось уведомить админа %s о заказе: %s", admin_id, e)

    try:
        await bot.send_message(
            tg_user["id"],
            f"✅ Заказ #{order_id} принят!\n\nТовар: {order_row['product']}\n"
            f"Цена: {order_row['price']} ₽\n\nМы свяжемся с тобой в ближайшее время для подтверждения.",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Не удалось отправить подтверждение заказа пользователю: %s", e)

    return web.json_response({"ok": True, "order_id": order_id})


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "600"))  # 10 минут
KEEP_ALIVE_ENABLED = os.getenv("KEEP_ALIVE_ENABLED", "1") != "0"


async def _keep_alive_loop() -> None:
    """Периодически пингует собственный health-эндпоинт, чтобы Render
    не усыплял бесплатный веб-сервис из-за отсутствия входящих запросов."""
    await asyncio.sleep(30)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    BASE_URL + "/", timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    log.info("Keep-alive ping: %s", resp.status)
            except Exception as e:
                log.warning("Keep-alive ping не удался: %s", e)
            await asyncio.sleep(KEEP_ALIVE_INTERVAL)


async def on_startup(app: web.Application) -> None:
    await db.init_db()

    try:
        await bot.delete_my_commands()
    except Exception as e:
        log.warning("Не удалось очистить список команд бота: %s", e)

    log.info("Установка Webhook на адрес: %s", WEBHOOK_URL)
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
    )

    if KEEP_ALIVE_ENABLED:
        app["keep_alive_task"] = asyncio.create_task(_keep_alive_loop())


async def on_shutdown(app: web.Application) -> None:
    task = app.get("keep_alive_task")
    if task:
        task.cancel()
    log.info("Завершение работы: закрываем сессию бота...")
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/api/status", api_status)
    app.router.add_post("/api/create-invoice-link", api_create_invoice_link)
    app.router.add_post("/api/redeem-code", api_redeem_code)
    app.router.add_post("/api/create-order", api_create_order)
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