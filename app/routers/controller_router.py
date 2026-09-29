import asyncio
from dotenv import load_dotenv

from aiogram import F
from aiogram.filters import Command
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

import app.utils.keyboards as kb
from app.db.db_requests import is_admin, get_user, get_blocked_users, get_non_fiot_users

from app.routers.admin_router import router as admin_router
from app.routers.registration_router import router as registration_router
from app.routers.profile_router import router as profile_router
from app.routers.faq_router import router as faq_router

load_dotenv()
router = Router()
router.include_routers(
    admin_router,
    registration_router,
    profile_router,
    faq_router,
)

EVENT_INFO = (
    "📅 <b>4 жовтня</b> о <b>14:00</b>\n"
    "📍 <b>Офлайн:</b> <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпус КПІ ім. Ігоря Сікорського</a>\n"
    "💻 <b>Онлайн:</b> <a href='https://www.youtube.com/@studentcouncilfice'>онлайн-трансляція на YouTube</a>\n\n"
    "💡 <a href='https://serv1.vlix.io/media/videos/h264/a9eef9bba69c7d4e8710.mp4'>Відео-анонс лекції</a>\n"
    "📢 <b>Канал новин:</b> <a href='https://t.me/fice_time'>FICE Time 🇺🇦</a>"
)

WELCOME_TEXT = (
    "Привіт! Запрошуємо тебе на лекцію <b>«Хто така Студрада ФІОТ» 💡</b>\n\n"
    "Хочеш долучитися до команди, що змінює факультет? <b>4 жовтня о 14:00</b> розкажемо про структуру СР ФІОТ, департаменти та можливості розвитку в нашому студентському самоврядуванні.\n\n"
    "Реєструйся та приходь у 18 корпус або доєднуйся до онлайн-трансляції на YouTube. "
    "Після лекції ми відкриємо набір до Студради, тож це нагода дізнатися більше про команду та обрати напрям, у якому хочеш спробувати себе!\n\n"
    "📅 <b>4 жовтня</b> о <b>14:00</b>\n"
    "📍 <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпус КПІ</a> або 💻 <a href='https://www.youtube.com/@studentcouncilfice'>онлайн-трансляція на YouTube</a>"
)


async def safe_reply(message: types.Message, text: str, reply_markup=None):
    try:
        return await message.edit_text(text=text, reply_markup=reply_markup,
                                       parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        return await message.answer(text=text, reply_markup=reply_markup, parse_mode="HTML",
                                    disable_web_page_preview=True)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    is_user_admin, existing_user = await asyncio.gather(
        is_admin(message.from_user.id),
        get_user(message.from_user.id)
    )

    if is_user_admin:
        blocked, non_fiot = await asyncio.gather(
            get_blocked_users(),
            get_non_fiot_users()
        )
        keyboard = kb.create_main_admin_keyboard(
            blocked_count=len(blocked),
            non_fiot_count=len(non_fiot)
        )
        text = WELCOME_TEXT + (
            "\n\n───────────────\n"
            "🔐 Ти маєш права <b>Адміна</b>\nОбери дію:"
        )
    elif existing_user:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        user_format = getattr(existing_user, "format", "Офлайн") or "Офлайн"
        format_badge = "📍 Офлайн (18 корпус)" if user_format == "Офлайн" else "💻 Онлайн (YouTube)"
        text = (
            f"👋 Привіт, <b>{existing_user.name.split()[1] if len(existing_user.name.split()) > 1 else existing_user.name}</b>!\n"
            f"Ти вже зареєстрований(а) на лекцію <b>«Хто така Студрада ФІОТ»</b> 🎉\n"
            f"Формат участі: <b>{format_badge}</b>\n\n"
            f"{EVENT_INFO}"
        )
    else:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = WELCOME_TEXT + "\n\n<i>Ти ще не зареєстрований(а), натисни кнопку нижче, щоб зареєструватися!</i>"

    await message.reply(
        text=text,
        reply_markup=keyboard.as_markup(),
        disable_web_page_preview=True
    )


@router.callback_query(F.data.in_(["controller_hub", "controller_hub_new"]))
async def cmd_back_hub(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.clear()

    is_user_admin, existing_user = await asyncio.gather(
        is_admin(callback.from_user.id),
        get_user(callback.from_user.id)
    )

    if is_user_admin:
        blocked, non_fiot = await asyncio.gather(
            get_blocked_users(),
            get_non_fiot_users()
        )
        keyboard = kb.create_main_admin_keyboard(
            blocked_count=len(blocked),
            non_fiot_count=len(non_fiot)
        )
        text = WELCOME_TEXT + (
            "\n\n───────────────\n"
            "🔐 Ти маєш права <b>Адміна</b>\nОбери дію:"
        )
    elif existing_user:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        user_format = getattr(existing_user, "format", "Офлайн") or "Офлайн"
        format_badge = "📍 Офлайн (18 корпус)" if user_format == "Офлайн" else "💻 Онлайн (YouTube)"
        text = (
            f"👋 Привіт, <b>{existing_user.name.split()[1] if len(existing_user.name.split()) > 1 else existing_user.name}</b>!\n"
            f"Ти вже зареєстрований(а) на лекцію <b>«Хто така Студрада ФІОТ»</b> 🎉\n"
            f"Формат участі: <b>{format_badge}</b>\n\n"
            f"{EVENT_INFO}"
        )
    else:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = WELCOME_TEXT + "\n\n<i>Ти ще не зареєстрований(а), натисни кнопку нижче, щоб зареєструватися!</i>"

    await safe_reply(
        message=callback.message,
        text=text,
        reply_markup=keyboard.as_markup()
    )
