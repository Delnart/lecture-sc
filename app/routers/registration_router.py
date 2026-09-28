from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.data.bot_state import global_state
from app.utils.google_sheets import add_user_to_sheet
from app.db.db_requests import add_user, get_user, is_user_blocked, block_user
from app.utils.group_validator import validate_fiot_group
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()
router = Router()

RULES_TEXT = (
    "📜 <b>Правила заходу</b>\n\n"
    "<b>Загальні правила:</b>\n"
    "1) Поважати спікерів та інших учасників лекції\n"
    "2) Уникати неетичної поведінки, образ чи спаму в чаті трансляції\n"
    "3) Для офлайн-учасників: дбайливо ставитися до майна 18 корпусу КПІ\n\n"
    "<b>Безпека:</b>\n"
    "⚠️ У разі оголошення повітряної тривоги в Києві офлайн-частина заходу негайно призупиняється, "
    "а всі присутні прямують до найближчого укриття.\n\n"
    "Ти погоджуєшся з цими правилами?"
)


class RegisterForm(StatesGroup):
    entering_name = State()
    entering_username = State()
    entering_group = State()
    choosing_format = State()
    agreeing_to_rules = State()
    waiting_confirmation = State()


@router.callback_query(F.data == "registration")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if not global_state.get("registration_open", True):
        await callback.answer("На жаль, реєстрація вже закрита ❌", show_alert=True)
        return

    if await is_user_blocked(callback.from_user.id):
        builder = InlineKeyboardBuilder()
        builder.button(text="Головне меню", callback_data="controller_hub")
        await callback.message.edit_text(
            "❌ <b>Твій акаунт заблоковано для реєстрації на цей захід!</b>\n\n"
            "Причина: спроба вказати академічну групу іншого факультету.\n\n"
            "<i>Якщо сталася помилка і ти студент ФІОТ — звернись до організаторів для розблокування.</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer("Реєстрацію заблоковано", show_alert=True)
        return

    existing_user = await get_user(callback.from_user.id)

    if existing_user:
        builder = InlineKeyboardBuilder()
        builder.button(text="🪪 Перейти в профіль", callback_data="profile")
        builder.button(text="🏠 Головне меню", callback_data="controller_hub")
        builder.adjust(1)

        await callback.message.edit_text(
            "❌ <b>Ти вже зареєстрований(а) на цю лекцію!</b>\n\n"
            "Якщо ти хочеш змінити свої дані або обрати інший формат присутності (онлайн/офлайн), перейди у свій Профіль.",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    text = (
        "💡 <b>Реєстрація на лекцію «Хто така Студрада ФІОТ»</b>\n\n"
        "Введи своє ПІБ:\n"
        "Приклад: Шевченко Тарас Григорович\n\n"
        "<i>*після реєстрації всі дані та формат участі можна буде змінити в особистому профілі</i>"
    )

    try:
        new_msg = await callback.message.edit_text(text, disable_web_page_preview=True)
    except Exception:
        new_msg = await callback.message.answer(text, disable_web_page_preview=True)

    await state.update_data(main_message_id=new_msg.message_id)
    await state.set_state(RegisterForm.entering_name)
    await callback.answer()


# ==================== КРОК 1: ПІБ ====================

@router.message(RegisterForm.entering_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    err_msg_id = data.get("error_msg_id")
    if err_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, err_msg_id)
            await state.update_data(error_msg_id=None)
        except Exception:
            pass

    try:
        await message.delete()
    except Exception:
        pass

    name_text = message.text.strip()
    words = name_text.split()

    if len(words) > 3:
        err_msg = await message.answer("❌ Будь ласка, введи ПІБ (не більше 3 слів).\nПриклад: Шевченко Тарас Григорович")
        await state.update_data(error_msg_id=err_msg.message_id)
        return

    await state.update_data(name=name_text)
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    if message.from_user.username:
        # Юзернейм є в Telegram — переходимо одразу до вводу групи
        await state.update_data(tg_username=f"@{message.from_user.username}")

        text = "Введи свою академічну групу:\nПриклад: <b>ІП-55</b>"

        if main_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text,
                    parse_mode="HTML"
                )
            except Exception:
                new_msg = await message.answer(text, parse_mode="HTML")
                await state.update_data(main_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(text, parse_mode="HTML")
            await state.update_data(main_message_id=new_msg.message_id)

        await state.set_state(RegisterForm.entering_group)

    else:
        # Юзернейму немає — запитуємо контактні дані
        text = (
            "Введи свій юзернейм (або телефон/інстаграм) для зв'язку\n"
            "Приклад: @username\n\n"
            "<i>(Оскільки у тебе не встановлений юзернейм в налаштуваннях Telegram, ми запитуємо контактні дані вручну. "
            "Якщо не хочеш нічого вказувати — введи «немає».)</i>"
        )

        if main_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text,
                    parse_mode="HTML"
                )
            except Exception:
                new_msg = await message.answer(text, parse_mode="HTML")
                await state.update_data(main_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(text, parse_mode="HTML")
            await state.update_data(main_message_id=new_msg.message_id)

        await state.set_state(RegisterForm.entering_username)


# ==================== КРОК 2: ЮЗЕРНЕЙМ ====================

@router.message(RegisterForm.entering_username, F.text)
async def process_username_input(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if raw.lower() == "немає":
        tg_username = "немає"
    elif raw.startswith("@"):
        tg_username = raw
    else:
        tg_username = f"@{raw}"

    await state.update_data(tg_username=tg_username)
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    try:
        await message.delete()
    except Exception:
        pass

    text = "Введи свою академічну групу:\nПриклад: <b>ІП-55</b>"

    if main_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_msg_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception:
            new_msg = await message.answer(text, parse_mode="HTML")
            await state.update_data(main_message_id=new_msg.message_id)
    else:
        new_msg = await message.answer(text, parse_mode="HTML")
        await state.update_data(main_message_id=new_msg.message_id)

    await state.set_state(RegisterForm.entering_group)


# ==================== КРОК 3: ГРУПА ====================

@router.message(RegisterForm.entering_group, F.text)
async def process_group(message: types.Message, state: FSMContext):
    data = await state.get_data()
    err_msg_id = data.get("error_msg_id")
    if err_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, err_msg_id)
            await state.update_data(error_msg_id=None)
        except Exception:
            pass

    try:
        await message.delete()
    except Exception:
        pass

    is_valid, is_other_fac, norm_group, err_text = validate_fiot_group(message.text)
    if is_other_fac:
        # Автоматичне блокування за спробу реєстрації з іншого факультету
        name = data.get("name")
        username = data.get("tg_username") or (f"@{message.from_user.username}" if message.from_user.username else None)

        await block_user(
            tg_id=message.from_user.id,
            username=username,
            name=name,
            attempted_group=norm_group,
            reason=f"Вказано групу іншого факультету ({norm_group})"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="Головне меню", callback_data="controller_hub")
        main_msg_id = data.get("main_message_id")
        if main_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=err_text,
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
            except Exception:
                await message.answer(err_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(err_text, reply_markup=builder.as_markup(), parse_mode="HTML")

        await state.clear()
        return

    if not is_valid:
        err_msg = await message.answer(err_text, parse_mode="HTML")
        await state.update_data(error_msg_id=err_msg.message_id)
        return

    await state.update_data(
        group=norm_group,
        university="КПІ ім. Ігоря Сікорського",
        faculty="ФІОТ"
    )
    await ask_for_format(message, state)


# ==================== КРОК 4: ВИБІР ФОРМАТУ ПРИСУТНОСТІ ====================

async def ask_for_format(event: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")
    bot = event.bot
    chat_id = event.message.chat.id if isinstance(event, types.CallbackQuery) else event.chat.id

    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Буду Офлайн (18 корпус)", callback_data="format_choice_offline")
    builder.button(text="💻 Буду Онлайн (YouTube)", callback_data="format_choice_online")
    builder.adjust(1)

    text = (
        "👥 <b>Обери формат участі в лекції:</b>\n\n"
        "• 📍 <b>Офлайн</b> — наживо у <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпусі КПІ</a>.\n"
        "• 💻 <b>Онлайн</b> — трансляція на нашому <a href='https://www.youtube.com/@studentcouncilfice'>YouTube-каналі</a>.\n\n"
        "<i>(Ти зможеш будь-коли змінити свій вибір у розділі «Мій профіль»)</i>"
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    else:
        if main_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=main_msg_id,
                    text=text,
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                new_msg = await event.answer(text=text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
                await state.update_data(main_message_id=new_msg.message_id)
        else:
            new_msg = await event.answer(text=text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
            await state.update_data(main_message_id=new_msg.message_id)

    await state.set_state(RegisterForm.choosing_format)


@router.callback_query(RegisterForm.choosing_format, F.data.in_(["format_choice_offline", "format_choice_online"]))
async def process_format_choice(callback: types.CallbackQuery, state: FSMContext):
    chosen_format = "Офлайн" if callback.data == "format_choice_offline" else "Онлайн"
    await state.update_data(format=chosen_format)
    await callback.answer(f"Обрано: {chosen_format}")
    await ask_for_rules(callback, state)


# ==================== КРОК 5: ПРАВИЛА ЗАХОДУ ====================

async def ask_for_rules(event: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")
    bot = event.bot
    chat_id = event.message.chat.id if isinstance(event, types.CallbackQuery) else event.chat.id

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Погоджуюсь з правилами", callback_data="agree_rules")

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(
            text=RULES_TEXT,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    else:
        if main_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=main_msg_id,
                    text=RULES_TEXT,
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
            except Exception:
                new_msg = await event.answer(text=RULES_TEXT, reply_markup=builder.as_markup(), parse_mode="HTML")
                await state.update_data(main_message_id=new_msg.message_id)

    await state.set_state(RegisterForm.agreeing_to_rules)


@router.callback_query(RegisterForm.agreeing_to_rules, F.data == "agree_rules")
async def process_agree_rules(callback: types.CallbackQuery, state: FSMContext):
    await show_confirmation_screen(callback, state)
    await callback.answer()


# ==================== КРОК 6: ЕКРАН ПІДТВЕРДЖЕННЯ ====================

async def show_confirmation_screen(event: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get('name')
    tg_username = data.get('tg_username')
    group = data.get('group')
    user_format = data.get('format', 'Офлайн')
    format_icon = "📍" if user_format == "Офлайн" else "💻"
    location_desc = "18 корпус КПІ" if user_format == "Офлайн" else "YouTube трансляція"

    confirmation_text = (
        f"<b>Перевір свої дані перед підтвердженням:</b>\n\n"
        f"<b>ПІБ:</b> {name}\n"
        f"<b>Telegram:</b> {tg_username}\n"
        f"<b>Група:</b> {group}\n"
        f"<b>Формат участі:</b> {format_icon} <b>{user_format}</b> ({location_desc})\n\n"
        f"Усе правильно? Натисни підтвердити або скасуй реєстрацію."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Підтвердити реєстрацію", callback_data="confirm_registration")
    builder.button(text="❌ Скасувати", callback_data="cancel_registration")
    builder.adjust(1)

    await event.message.edit_text(text=confirmation_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(RegisterForm.waiting_confirmation)


@router.callback_query(RegisterForm.waiting_confirmation, F.data == "confirm_registration")
async def confirm_registration(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get('name')
    tg_username = data.get('tg_username')
    university = data.get('university') or "КПІ ім. Ігоря Сікорського"
    faculty = data.get('faculty') or "ФІОТ"
    group = data.get('group')
    user_format = data.get('format', 'Офлайн')

    real_username = callback.from_user.username
    stored_username = tg_username if tg_username else (f"@{real_username}" if real_username else "немає")

    try:
        await add_user(
            tg_id=callback.from_user.id,
            username=stored_username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group,
            format=user_format,
        )

        asyncio.create_task(add_user_to_sheet(
            tg_id=callback.from_user.id,
            username=stored_username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group,
            format=user_format,
        ))

        builder = InlineKeyboardBuilder()
        builder.button(text="🪪 Мій профіль", callback_data="profile")
        builder.button(text="🏠 Головне меню", callback_data="controller_hub")
        builder.adjust(1)

        if user_format == "Офлайн":
            location_details = (
                "📍 <b>Формат:</b> Офлайн\n"
                "🏢 <b>Локація:</b> <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпус КПІ ім. Ігоря Сікорського</a>"
            )
        else:
            location_details = (
                "💻 <b>Формат:</b> Онлайн\n"
                "📺 <b>Локація:</b> <a href='https://www.youtube.com/@studentcouncilfice'>YouTube-трансляція Студради ФІОТ</a>"
            )

        success_text = (
            "🎉 <b>Реєстрацію успішно підтверджено!</b>\n\n"
            "Твої дані збережено. Чекаємо тебе на лекції <b>«Хто така Студрада ФІОТ»</b>!\n\n"
            "📅 <b>Коли:</b> 4 жовтня (час буде повідомлено незабаром, о хх:00)\n"
            f"{location_details}\n\n"
            "Після лекції ми відкриємо набір до Студради, тож це нагода дізнатися більше про команду та обрати напрям, у якому хочеш спробувати себе! 🚀\n\n"
            "Слідкуй за всіма новинами на каналі <a href='https://t.me/fice_time'>FICE Time 🇺🇦</a>"
        )

        await callback.message.edit_text(
            text=success_text,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
            parse_mode="HTML"
        )
        await state.clear()

    except Exception as e:
        logging.error(f"\033[31mПомилка БД під час реєстрації: {e}\033[0m")
        builder = InlineKeyboardBuilder()
        builder.button(text="Спробувати ще раз", callback_data="registration")

        await callback.message.edit_text(
            text="⚠️ Виникла помилка під час збереження даних. Спробуй ще раз.",
            reply_markup=builder.as_markup()
        )
        await state.clear()

    await callback.answer()


@router.callback_query(RegisterForm.waiting_confirmation, F.data == "cancel_registration")
async def cancel_registration(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в меню", callback_data="controller_hub")

    await callback.message.edit_text(
        text="❌ <b>Реєстрацію скасовано.</b> Твої дані не було збережено в системі.",
        reply_markup=builder.as_markup()
    )
    await state.clear()
    await callback.answer()
