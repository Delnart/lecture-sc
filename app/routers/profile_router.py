from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.db_requests import get_user, update_user_field, block_user
from app.utils.google_sheets import update_user_in_sheet
from app.utils.group_validator import validate_fiot_group

import asyncio
import re

router = Router()


class ProfileEditForm(StatesGroup):
    waiting_for_new_name = State()
    waiting_for_new_username = State()
    waiting_for_new_group = State()


@router.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    tg_id = callback.from_user.id

    user = await get_user(tg_id)
    if not user:
        await callback.message.answer("Профіль не знайдено. Спочатку зареєструйся.")
        await callback.answer()
        return

    user_format = getattr(user, "format", "Офлайн") or "Офлайн"
    format_icon = "📍" if user_format == "Офлайн" else "💻"
    location_desc = "18 корпус КПІ" if user_format == "Офлайн" else "YouTube трансляція"

    text = (
        f"<b>ТВІЙ ПРОФІЛЬ</b>\n"
        f"───────────────\n"
        f"👤 <b>ПІБ:</b> {user.name}\n"
        f"✈️ <b>Telegram:</b> {user.username}\n"
    )
    if user.group_name and user.group_name != "-":
        text += f"🎓 <b>Група:</b> {user.group_name}\n"

    text += f"{format_icon} <b>Формат участі:</b> {user_format} ({location_desc})\n"

    text += (
        f"───────────────\n"
        f"📅 <b>4 жовтня</b>, <b>час буде оголошено незабаром (о хх:00)</b>\n"
        f"📍 <b>Офлайн:</b> <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпус КПІ</a>\n"
        f"💻 <b>Онлайн:</b> <a href='https://www.youtube.com/@studentcouncilfice'>онлайн-трансляція на YouTube</a>\n\n"
        f"📢 Новини та анонси: <a href='https://t.me/fice_time'>FICE Time 🇺🇦</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Змінити дані", callback_data="prof_edit_menu")
    builder.button(text="🔄 Змінити формат (онлайн/офлайн)", callback_data="edit_prof_format")
    builder.button(text="🏠 Головне меню", callback_data="controller_hub_new")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)

    await callback.answer()


@router.callback_query(F.data == "prof_edit_menu")
async def edit_profile_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Помилка: юзера не знайдено.")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="👤 ПІБ", callback_data="edit_prof_name")
    builder.button(text="✈️ Telegram", callback_data="edit_prof_username")
    builder.button(text="🎓 Група", callback_data="edit_prof_group")
    builder.button(text="🔄 Формат участі", callback_data="edit_prof_format")
    builder.button(text="🔙 Назад до профілю", callback_data="profile")
    builder.adjust(2, 2, 1)

    await callback.message.edit_text(
        "<b>Що саме ти хочеш змінити?</b>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ==================== ЗМІНА ФОРМАТУ УЧАСТІ ====================

@router.callback_query(F.data == "edit_prof_format")
async def edit_attendance_format(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Помилка: користувача не знайдено.")
        return

    current_format = getattr(user, "format", "Офлайн") or "Офлайн"
    current_icon = "📍" if current_format == "Офлайн" else "💻"

    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Буду Офлайн (18 корпус)", callback_data="set_user_format_Офлайн")
    builder.button(text="💻 Буду Онлайн (YouTube)", callback_data="set_user_format_Онлайн")
    builder.button(text="🔙 Скасувати", callback_data="profile")
    builder.adjust(1)

    text = (
        "🔄 <b>Зміна формату участі в лекції</b>\n\n"
        f"Поточний формат: {current_icon} <b>{current_format}</b>\n\n"
        "Обери бажаний формат присутності:\n"
        "• 📍 <b>Офлайн</b> — у 18 корпусі КПІ ім. Ігоря Сікорського\n"
        "• 💻 <b>Онлайн</b> — трансляція на YouTube-каналі Студради ФІОТ"
    )

    await callback.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["set_user_format_Офлайн", "set_user_format_Онлайн"]))
async def process_set_format(callback: types.CallbackQuery):
    new_format = "Офлайн" if callback.data == "set_user_format_Офлайн" else "Онлайн"
    user_id = callback.from_user.id

    await update_user_field(user_id, "format", new_format)

    asyncio.create_task(update_user_in_sheet(
        tg_id=user_id,
        field="format",
        new_value=new_format
    ))

    builder = InlineKeyboardBuilder()
    builder.button(text="🪪 Повернутися в профіль", callback_data="profile")
    builder.button(text="🏠 Головне меню", callback_data="controller_hub_new")
    builder.adjust(1)

    if new_format == "Офлайн":
        format_msg = (
            "📍 <b>Формат оновлено на ОФЛАЙН!</b>\n\n"
            "Чекаємо тебе <b>4 жовтня</b> у <a href='https://maps.app.goo.gl/Xf2p69hudhib6iSz7?g_st=ic'>18 корпусі КПІ</a>!"
        )
    else:
        format_msg = (
            "💻 <b>Формат оновлено на ОНЛАЙН!</b>\n\n"
            "Чекаємо тебе <b>4 жовтня</b> на <a href='https://www.youtube.com/@studentcouncilfice'>онлайн-трансляції на YouTube</a>!"
        )

    await callback.message.edit_text(
        text=f"✅ {format_msg}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer("Формат успішно змінено!")


# ==================== ЗМІНА ТЕКСТОВИХ ПОЛІВ ====================

@router.callback_query(F.data.startswith("edit_prof_"))
async def start_edit_text_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_prof_", "")

    prompts = {
        "name":     "Введи нове ПІБ:\nПриклад: Шевченко Тарас Григорович",
        "username": "Введи новий юзернейм у Telegram:\nПриклад: @username",
        "group":    "Введи нову групу:\nПриклад: ІП-55",
    }

    states = {
        "name":     ProfileEditForm.waiting_for_new_name,
        "username": ProfileEditForm.waiting_for_new_username,
        "group":    ProfileEditForm.waiting_for_new_group,
    }

    prompt = prompts.get(field)
    target_state = states.get(field)

    if not prompt or not target_state:
        await callback.answer("Невідоме поле.")
        return

    await state.set_state(target_state)

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="prof_edit_menu")
    builder.adjust(1)

    new_msg = await callback.message.edit_text(prompt, reply_markup=builder.as_markup())
    await state.update_data(main_message_id=new_msg.message_id)
    await callback.answer()


@router.message(ProfileEditForm.waiting_for_new_name, F.text)
@router.message(ProfileEditForm.waiting_for_new_username, F.text)
@router.message(ProfileEditForm.waiting_for_new_group, F.text)
async def save_text_field(message: types.Message, state: FSMContext):
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

    current_state = await state.get_state()

    state_to_field = {
        ProfileEditForm.waiting_for_new_name.state:     "name",
        ProfileEditForm.waiting_for_new_username.state: "username",
        ProfileEditForm.waiting_for_new_group.state:    "group_name",
    }
    field_to_update = state_to_field.get(current_state)
    input_text = message.text.strip()

    if field_to_update == "name":
        if len(input_text.split()) > 3:
            err_msg = await message.answer("❌ Будь ласка, введи ПІБ (не більше 3 слів).\nПриклад: Шевченко Тарас Григорович")
            await state.update_data(error_msg_id=err_msg.message_id)
            return

    # Нормалізуємо юзернейм
    if field_to_update == "username":
        if input_text.lower() != "немає" and not input_text.startswith("@"):
            input_text = f"@{input_text}"

    if field_to_update == "group_name":
        is_valid, is_other_fac, norm_group, err_text = validate_fiot_group(input_text)
        if is_other_fac:
            user = await get_user(message.from_user.id)
            name = user.name if user else None
            username = user.username if user else (f"@{message.from_user.username}" if message.from_user.username else None)

            await block_user(
                tg_id=message.from_user.id,
                username=username,
                name=name,
                attempted_group=norm_group,
                reason=f"Зміна групи на чужий факультет ({norm_group})"
            )

            builder = InlineKeyboardBuilder()
            builder.button(text="Головне меню", callback_data="controller_hub")
            await message.answer(err_text, reply_markup=builder.as_markup(), parse_mode="HTML")
            await state.clear()
            return

        if not is_valid:
            err_msg = await message.answer(err_text, parse_mode="HTML")
            await state.update_data(error_msg_id=err_msg.message_id)
            return
        input_text = norm_group

    await update_user_field(message.from_user.id, field_to_update, input_text)

    asyncio.create_task(update_user_in_sheet(
        tg_id=message.from_user.id,
        field=field_to_update,
        new_value=input_text
    ))

    data = await state.get_data()

    builder = InlineKeyboardBuilder()
    builder.button(text="🪪 Повернутися в профіль", callback_data="profile")

    main_message_id = data.get("main_message_id")
    if main_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_message_id,
                text="✅ Дані успішно оновлено!",
                reply_markup=builder.as_markup()
            )
        except Exception:
            await message.answer("✅ Дані успішно оновлено!", reply_markup=builder.as_markup())
    else:
        await message.answer("✅ Дані успішно оновлено!", reply_markup=builder.as_markup())

    await state.clear()
