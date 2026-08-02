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
    FSInputFile,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import db
from security import extract_tg_user

BOT_TOKEN = os.getenv("BOT_TOKEN", "8860971431:AAH3FMBFI_8SydrjDAOUapNdVnOrgSemDmM")
BASE_URL = os.getenv("BASE_URL", "https://swagclubea-bot.onrender.com").rstrip("/")
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://swagclubea-bot.onrender.com/WEB/index2.html"
)
ADMIN_WEBAPP_URL = os.getenv(
    "ADMIN_WEBAPP_URL", "https://swagclubea-bot.onrender.com/WEB/admin.html"
)

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "7240769536").split(",")
    if x.strip().isdigit()
]

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "300"))
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "150"))

STARS_PRICES = {1: 150, 3: 420, 6: 800, 12: 1500}
CARD_PRICES = {1: 300, 3: 800, 6: 1500, 12: 2800}

# Реквизиты для ручной оплаты картой / СБП — задаются переменными окружения
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_BANK = os.getenv("CARD_BANK", "Т-Банк")
CARD_HOLDER = os.getenv("CARD_HOLDER", "IVAN IVANOV")
SBP_PHONE = os.getenv("SBP_PHONE", "+7 900 000-00-00")

# Приветственное видео/анимация для /start (необязательно)
WELCOME_VIDEO_URL = os.getenv("WELCOME_VIDEO_URL", "")
WELCOME_VIDEO_PATH = os.getenv("WELCOME_VIDEO_PATH", "")

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
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="method_stars")],
            [InlineKeyboardButton(text="💳 Карта / СБП", callback_data="method_card")],
        ]
    )


def get_months_keyboard(method: str) -> InlineKeyboardMarkup:
    prices = STARS_PRICES if method == "stars" else CARD_PRICES
    unit = "⭐" if method == "stars" else "₽"
    labels = {1: "1 месяц", 3: "3 месяца", 6: "6 месяцев", 12: "12 месяцев"}
    rows = [
        [InlineKeyboardButton(
            text=f"{labels[m]} — {prices[m]} {unit}",
            callback_data=f"buy_{method}_{m}",
        )]
        for m in (1, 3, 6, 12)
    ]
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="method_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


WELCOME_LINES = [
    "🎬 <i>Добро пожаловать в закрытый мир...</i>",
    "👟 <b>SWAG CLUB</b> — это не просто дропы. Это культура.",
    "🔥 Ранний доступ к тому, чего не будет у других. Community, статусы, эксклюзивы.",
    "🎁 Открывай каталог, качай уровень, забирай дропы раньше всех.",
]


def _get_welcome_video():
    if WELCOME_VIDEO_PATH and Path(WELCOME_VIDEO_PATH).exists():
        return FSInputFile(WELCOME_VIDEO_PATH)
    if WELCOME_VIDEO_URL:
        return WELCOME_VIDEO_URL
    return None


async def send_animated_welcome(chat_id: int) -> None:
    """Отправляет эффектное приветствие: видео/GIF, если оно настроено
    (WELCOME_VIDEO_URL или WELCOME_VIDEO_PATH), иначе — текстовую анимацию
    со «сборкой» сообщения по кусочкам."""
    video = _get_welcome_video()
    if video is not None:
        try:
            await bot.send_chat_action(chat_id, "upload_video")
            await bot.send_video(
                chat_id,
                video=video,
                caption=(
                    "🎬 <b>SWAG CLUB</b> × ROLDOZZZER\n\n"
                    "Закрытый клуб. Ранний доступ. Только для своих."
                ),
                parse_mode="HTML",
            )
            return
        except Exception as e:
            log.warning("Не удалось отправить приветственное видео: %s", e)

    try:
        await bot.send_chat_action(chat_id, "typing")
        msg = await bot.send_message(chat_id, "🎬", parse_mode="HTML")
        text_so_far = ""
        for line in WELCOME_LINES:
            await asyncio.sleep(0.55)
            try:
                await bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            text_so_far = (text_so_far + "\n\n" + line).strip()
            try:
                await bot.edit_message_text(
                    text_so_far, chat_id=chat_id, message_id=msg.message_id, parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as e:
        log.warning("Не удалось выполнить текстовую анимацию приветствия: %s", e)


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    await send_animated_welcome(message.chat.id)

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
        "Используйте кнопки меню внизу или откройте каталог ниже:",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown",
    )

    await message.answer(
        "Нажмите кнопку, чтобы зайти в закрытый каталог:",
        reply_markup=webapp_kb,
    )


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛠 Открыть админку",
                    web_app=WebAppInfo(url=ADMIN_WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "Панель администратора SWAG CLUB — заказы и подтверждение оплат.",
        reply_markup=admin_kb,
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
        "💎 **Оформление подписки SWAG CLUB**\n\nКак хочешь оплатить?",
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


@dp.callback_query(F.data.in_({"method_stars", "method_card"}))
async def cb_method(callback: CallbackQuery) -> None:
    method = "stars" if callback.data == "method_stars" else "card"
    title = "⭐ Оплата Telegram Stars" if method == "stars" else "💳 Оплата картой / СБП"
    try:
        await callback.message.edit_text(
            f"💎 **{title}**\n\nВыбери срок подписки:",
            reply_markup=get_months_keyboard(method),
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data == "method_back")
async def cb_method_back(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_text(
            "💎 **Оформление подписки SWAG CLUB**\n\nКак хочешь оплатить?",
            reply_markup=get_subscribe_keyboard(),
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_stars_"))
async def cb_buy_stars(callback: CallbackQuery) -> None:
    months = int(callback.data.split("_")[2])
    amount = STARS_PRICES.get(months, 150)

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


@dp.callback_query(F.data.startswith("buy_card_"))
async def cb_buy_card(callback: CallbackQuery) -> None:
    months = int(callback.data.split("_")[2])
    amount = CARD_PRICES.get(months, CARD_PRICES[1])

    payment_id = await db.create_pending_payment(
        tg_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        months=months,
        amount=amount,
        method="card",
    )

    pay_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data=f"paid_{payment_id}")],
        ]
    )

    try:
        await callback.message.edit_text(
            f"💳 **Оплата картой / СБП**\n\n"
            f"Сумма: **{amount} ₽** ({months} мес. подписки)\n\n"
            f"Карта: `{CARD_NUMBER}`\n"
            f"Банк: {CARD_BANK}\n"
            f"Получатель: {CARD_HOLDER}\n"
            f"СБП: `{SBP_PHONE}`\n\n"
            f"В комментарии к переводу укажи код заказа: `#{payment_id}`\n\n"
            f"После перевода нажми кнопку ниже — заявка уйдёт администратору на подтверждение.",
            reply_markup=pay_kb,
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.answer()


async def _confirm_payment(payment_id: int) -> dict:
    payment = await db.get_pending_payment(payment_id)
    if not payment or payment.get("status") != "pending":
        return {"ok": False, "message": "Платёж не найден или уже обработан"}

    resolved = await db.resolve_pending_payment(payment_id, "confirmed")
    if not resolved:
        return {"ok": False, "message": "Не удалось обработать платёж"}

    status = await db.extend_subscription(
        tg_id=payment["tg_id"],
        months=payment["months"],
        amount=payment["amount"],
        currency="CARD",
        charge_id=f"card_{payment_id}",
        username=payment.get("username"),
        first_name=payment.get("first_name"),
    )

    try:
        await bot.send_message(
            payment["tg_id"],
            f"✅ **Оплата подтверждена!**\n\n{status_text(status)}",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Не удалось уведомить пользователя об оплате: %s", e)

    return {"ok": True, "status": status, "payment": payment}


async def _reject_payment(payment_id: int) -> dict:
    payment = await db.get_pending_payment(payment_id)
    if not payment or payment.get("status") != "pending":
        return {"ok": False, "message": "Платёж не найден или уже обработан"}

    await db.resolve_pending_payment(payment_id, "rejected")

    try:
        await bot.send_message(
            payment["tg_id"],
            "❌ Оплата не подтверждена администратором. "
            "Если ты уверен(а), что перевод прошёл — напиши в поддержку.",
        )
    except Exception as e:
        log.warning("Не удалось уведомить пользователя об отклонении оплаты: %s", e)

    return {"ok": True, "payment": payment}


@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(callback: CallbackQuery) -> None:
    payment_id = int(callback.data.split("_")[1])
    payment = await db.get_pending_payment(payment_id)

    if not payment or payment["tg_id"] != callback.from_user.id:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if payment["status"] != "pending":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"⏳ **Заявка отправлена на проверку**\n\n"
            f"Код заказа: `#{payment_id}`\n"
            f"Сумма: {payment['amount']} ₽\n\n"
            f"Администратор подтвердит оплату в ближайшее время, "
            f"подписка активируется автоматически.",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.answer()

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admconf_{payment_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admrej_{payment_id}"),
            ]
        ]
    )
    handle = f"@{payment['username']}" if payment.get("username") else f"id{payment['tg_id']}"
    admin_text = (
        f"💳 **Новая заявка на оплату #{payment_id}**\n\n"
        f"Пользователь: {handle}\n"
        f"Сумма: {payment['amount']} ₽\n"
        f"Срок: {payment['months']} мес."
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_kb, parse_mode="Markdown")
        except Exception as e:
            log.warning("Не удалось уведомить админа %s о новой заявке: %s", admin_id, e)


@dp.callback_query(F.data.startswith("admconf_"))
async def cb_admin_confirm(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    payment_id = int(callback.data.split("_")[1])
    result = await _confirm_payment(payment_id)

    if result.get("ok"):
        try:
            await callback.message.edit_text(callback.message.text + "\n\n✅ Подтверждено")
        except Exception:
            pass
        await callback.answer("Подтверждено")
    else:
        await callback.answer(result.get("message", "Ошибка"), show_alert=True)


@dp.callback_query(F.data.startswith("admrej_"))
async def cb_admin_reject(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    payment_id = int(callback.data.split("_")[1])
    result = await _reject_payment(payment_id)

    if result.get("ok"):
        try:
            await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено")
        except Exception:
            pass
        await callback.answer("Отклонено")
    else:
        await callback.answer(result.get("message", "Ошибка"), show_alert=True)


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

    prices_map = STARS_PRICES
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


def _require_admin(tg_user: dict) -> bool:
    return bool(tg_user) and tg_user.get("id") in ADMIN_IDS


async def api_admin_orders(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not _require_admin(tg_user):
        return _json_error("Доступ только для администраторов", status=403)

    status_filter = body.get("status") or None
    orders = await db.list_orders(status=status_filter, limit=200)
    return web.json_response({"ok": True, "orders": orders})


async def api_admin_order_status(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not _require_admin(tg_user):
        return _json_error("Доступ только для администраторов", status=403)

    order_id = body.get("order_id")
    new_status = str(body.get("status", "")).strip()
    allowed = {"new", "processing", "shipped", "done", "cancelled"}
    if not order_id or new_status not in allowed:
        return _json_error("Некорректные параметры")

    ok = await db.update_order_status(int(order_id), new_status)
    return web.json_response({"ok": ok})


async def api_admin_payments(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not _require_admin(tg_user):
        return _json_error("Доступ только для администраторов", status=403)

    status_filter = body.get("status", "pending")
    payments = await db.list_pending_payments(status=status_filter, limit=200)
    return web.json_response({"ok": True, "payments": payments})


async def api_admin_payment_action(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_error("Некорректный запрос")

    tg_user = extract_tg_user(body.get("initData", ""), BOT_TOKEN)
    if not _require_admin(tg_user):
        return _json_error("Доступ только для администраторов", status=403)

    payment_id = body.get("payment_id")
    action = body.get("action")
    if not payment_id or action not in ("confirm", "reject"):
        return _json_error("Некорректные параметры")

    if action == "confirm":
        result = await _confirm_payment(int(payment_id))
    else:
        result = await _reject_payment(int(payment_id))

    return web.json_response(result)


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
    app.router.add_post("/api/admin/orders", api_admin_orders)
    app.router.add_post("/api/admin/order-status", api_admin_order_status)
    app.router.add_post("/api/admin/payments", api_admin_payments)
    app.router.add_post("/api/admin/payment-action", api_admin_payment_action)
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