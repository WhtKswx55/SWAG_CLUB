import asyncio
import logging
import sqlite3
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    LabeledPrice,
    PreCheckoutQuery,
    BotCommand,
)
import db

BOT_TOKEN = "8860971431:AAH3FMBFI_8SydrjDAOUapNdVnOrgSemDmM"
WEBAPP_URL = "https://swagclubea-bot.onrender.com/WEB/index2.html"
ADMIN_IDS = [7240769536]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def status_text(status: dict) -> str:
    if not status or not status.get("has_access"):
        return "❌ **Подписка не активна**\nУровень: `ZERO ACCESS`"

    return (
        f"✅ **Подписка активна**\n"
        f"Уровень: `{status.get('level_name', 'Member')}`\n"
        f"Стаж: `{status.get('tenure_months', 0)}` мес.\n"
        f"Осталось дней: `{status.get('days_left', 0)}`"
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

    args = message.text.split()
    if len(args) > 1 and args[1] == "subscribe":
        await cmd_subscribe(message)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 Открыть SWAG CLUB",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Подписка",
                    callback_data="menu_subscribe",
                ),
                InlineKeyboardButton(
                    text="📊 Мой статус",
                    callback_data="menu_status",
                ),
            ],
        ]
    )
    await message.answer(
        "Добро пожаловать в **SWAG CLUB**.",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(Command("mystatus"))
async def cmd_mystatus(message: Message) -> None:
    status = await db.get_user_status(message.from_user.id)
    await message.answer(status_text(status), parse_mode="Markdown")


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    await message.answer(
        "💎 **Оформление подписки SWAG CLUB**\n\n"
        "Выберите срок подписки:",
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
        "💎 **Оформление подписки SWAG CLUB**\n\n"
        "Выберите срок подписки:",
        reply_markup=get_subscribe_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_status")
async def cb_menu_status(callback: CallbackQuery) -> None:
    status = await db.get_user_status(callback.from_user.id)
    await callback.message.answer(status_text(status), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy(callback: CallbackQuery) -> None:
    months = int(callback.data.split("_")[1])

    prices_map = {
        1: 150,
        3: 420,
        6: 800,
        12: 1500,
    }
    amount = prices_map.get(months, 150)

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=f"Подписка SWAG CLUB — {months} мес.",
        description="Ранний доступ к закрытому каталогу, бронь номеров и статусы в клубе.",
        payload=f"sub_{months}",
        provider_token="",  # Пустая строка для Telegram Stars (XTR)
        currency="XTR",
        prices=[LabeledPrice(label=f"{months} мес. подписки", amount=amount)],
    )
    await callback.answer()


@dp.pre_checkout_query()
async def on_pre_checkout_query(pre_checkout_query: PreCheckoutQuery) -> None:
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    payload = payment.invoice_payload
    months = int(payload.split("_")[1]) if payload.startswith("sub_") else 1

    status = await db.extend_subscription(
        tg_id=message.from_user.id,
        months=months,
        amount=payment.total_amount,
        currency=payment.currency,
        charge_id=payment.telegram_payment_charge_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    await message.answer(
        f"**Оплата успешно завершена!**\n\n{status_text(status)}",
        parse_mode="Markdown",
    )


async def main() -> None:
    await db.init_db()
    await setup_bot_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())