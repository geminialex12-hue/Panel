import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://your-mini-app.example",
)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class Registration(StatesGroup):
    nickname = State()
    game_id = State()


def terms_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Пользовательское соглашение",
                    url="https://example.com/terms",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Согласен",
                    callback_data="terms_accept",
                )
            ],
        ]
    )


def app_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть STANDKNIFE",
                    web_app={
                        "url": WEBAPP_URL
                    },
                )
            ]
        ]
    )


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 ИГРАТЬ",
                    web_app={"url": WEBAPP_URL},
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 НАПАРНИКИ",
                    web_app={"url": WEBAPP_URL},
                ),
                InlineKeyboardButton(
                    text="👤 ПРОФИЛЬ",
                    web_app={"url": WEBAPP_URL},
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 СТАТИСТИКА",
                    web_app={"url": WEBAPP_URL},
                ),
                InlineKeyboardButton(
                    text="🔎 ПОИСК",
                    web_app={"url": WEBAPP_URL},
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ НАСТРОЙКИ",
                    web_app={"url": WEBAPP_URL},
                ),
                InlineKeyboardButton(
                    text="👑 PREMIUM",
                    web_app={"url": WEBAPP_URL},
                ),
            ],
        ]
    )


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "🎮 <b>STANDKNIFE</b>\n\n"
        "Добро пожаловать!\n\n"
        "Перед использованием платформы "
        "необходимо принять пользовательское соглашение.",
        reply_markup=terms_keyboard(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "terms_accept")
async def accept_terms(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.set_state(
        Registration.nickname
    )

    await callback.message.edit_text(
        "✅ Соглашение принято.\n\n"
        "Введите ваш игровой ник <b>StandKnife</b>:",
        parse_mode="HTML",
    )

    await callback.answer()


@dp.message(Registration.nickname)
async def receive_nickname(
    message: Message,
    state: FSMContext,
):
    nickname = message.text.strip()

    if len(nickname) < 2:
        await message.answer(
            "❌ Ник слишком короткий."
        )
        return

    if len(nickname) > 32:
        await message.answer(
            "❌ Ник не должен превышать 32 символа."
        )
        return

    await state.update_data(
        nickname=nickname
    )

    await state.set_state(
        Registration.game_id
    )

    await message.answer(
        "🎮 Теперь введите ваш "
        "<b>StandKnife ID</b>:",
        parse_mode="HTML",
    )


@dp.message(Registration.game_id)
async def receive_game_id(
    message: Message,
    state: FSMContext,
):
    game_id = message.text.strip()

    if len(game_id) < 1:
        await message.answer(
            "❌ Введите корректный ID."
        )
        return

    if len(game_id) > 64:
        await message.answer(
            "❌ ID слишком длинный."
        )
        return

    data = await state.get_data()

    await state.clear()

    await message.answer(
        "🎉 <b>Регистрация завершена!</b>\n\n"
        f"🎮 Ник: <b>{data['nickname']}</b>\n"
        f"🆔 ID: <code>{game_id}</code>\n\n"
        "Теперь можно открыть STANDKNIFE.",
        reply_markup=app_keyboard(),
        parse_mode="HTML",
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not configured"
        )

    print("STANDKNIFE bot started")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
