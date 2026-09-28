import os
import asyncio
from dotenv import load_dotenv

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.keyboards import create_main_admin_keyboard
from app.utils.group_validator import detect_faculty
from app.db.db_requests import (
    is_admin,
    get_all_users,
    get_users_by_format,
    get_users_by_identifiers,
    get_non_fiot_users,
    get_blocked_users,
    unblock_user,
    cancel_users_registration,
)
from app.data.bot_state import global_state

load_dotenv()
SHEET_URL = os.getenv("SHEET_URL")
router = Router()


class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()         # Загальна розсилка всім: очікуємо повідомлення
    confirm_all = State()                 # Підтвердження розсилки всім
    waiting_for_recipients = State()      # Введення тегів або ID
    waiting_for_targeted_msg = State()    # Очікуємо повідомлення для цільових
    confirm_targeted = State()            # Підтвердження таргетованої розсилки


class AdminUnblock(StatesGroup):
    waiting_for_identifier = State()


class AdminCancelReg(StatesGroup):
    waiting_for_identifiers = State()


@router.callback_query(F.data == "admin_stop_registration")
async def toggle_registration(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    global_state["registration_open"] = not global_state["registration_open"]

    status = "✅ ВІДКРИТА" if global_state["registration_open"] else "❌ ЗАКРИТА"
    text = (
        f"🔐 <b>Панель адміністратора</b>\n\n"
        f"Статус реєстрації: {status}\n"
        f"Оберіть дію:"
    )

    blocked, non_fiot = await asyncio.gather(
        get_blocked_users(),
        get_non_fiot_users()
    )
    keyboard = create_main_admin_keyboard(
        blocked_count=len(blocked),
        non_fiot_count=len(non_fiot)
    )
    await callback.message.edit_text(text=text, reply_markup=keyboard.as_markup(), parse_mode="HTML")
    await callback.answer(f"Реєстрація тепер {status}")


# ==================== МЕНЮ ВИБОРУ РЕЖИМУ РОЗСИЛКИ ====================

@router.callback_query(F.data == "admin_write_participants")
async def choose_broadcast_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()

    users, non_fiot_users, offline_users, online_users = await asyncio.gather(
        get_all_users(),
        get_non_fiot_users(),
        get_users_by_format("Офлайн"),
        get_users_by_format("Онлайн"),
    )
    all_count = len(users)
    non_fiot_count = len(non_fiot_users)
    offline_count = len(offline_users)
    online_count = len(online_users)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"📢 Всім зареєстрованим ({all_count})", callback_data="bc_mode_all")
    builder.button(text=f"📍 Тільки Офлайн ({offline_count})", callback_data="bc_mode_offline")
    builder.button(text=f"💻 Тільки Онлайн ({online_count})", callback_data="bc_mode_online")
    builder.button(text="🎯 Конкретним людям (@тег / ID)", callback_data="bc_mode_targeted")
    builder.button(text=f"👥 Не з нашого факультету ({non_fiot_count})", callback_data="bc_mode_non_fiot")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    text = (
        "📨 <b>Оберіть режим розсилки:</b>\n\n"
        f"• <b>📢 Всім зареєстрованим ({all_count})</b> — розіслати всій базі учасників.\n"
        f"• <b>📍 Тільки Офлайн ({offline_count})</b> — учасникам, які прийдуть у 18 корпус.\n"
        f"• <b>💻 Тільки Онлайн ({online_count})</b> — учасникам трансляції на YouTube.\n"
        "• <b>🎯 Конкретним людям</b> — розіслати за списком @username або ID.\n"
        f"• <b>👥 Не з нашого факультету ({non_fiot_count})</b> — вибірка студентів не з ФІОТ."
    )

    await callback.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["bc_mode_offline", "bc_mode_online"]))
async def broadcast_format_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    fmt_name = "Офлайн" if callback.data == "bc_mode_offline" else "Онлайн"
    users = await get_users_by_format(fmt_name)
    if not users:
        await callback.answer(f"Немає жодного учасника у форматі {fmt_name}.", show_alert=True)
        return

    target_user_ids = [u.telegram_id for u in users]
    await state.update_data(target_user_ids=target_user_ids)

    icon = "📍" if fmt_name == "Офлайн" else "💻"
    lines = [f"{icon} <b>Розсилка для учасників ({fmt_name}): {len(users)} осіб</b>\n"]
    for u in users[:15]:
        uname = f" ({u.username})" if u.username else ""
        grp = f" [{u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")
    if len(users) > 15:
        lines.append(f"<i>...та ще {len(users) - 15} осіб</i>")

    lines.append("\n✏️ <b>Надішліть повідомлення, яке отримають ці користувачі:</b>")

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(BroadcastAdmin.waiting_for_targeted_msg)
    await callback.answer()


# ==================== РЕЖИМ 1: ВСІМ УЧАСНИКАМ ====================

@router.callback_query(F.data == "bc_mode_all")
async def broadcast_all_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text(
        "📢 <b>Режим розсилки: Всім зареєстрованим</b>\n\n"
        "Надішліть повідомлення, яке хочете розіслати (текст, фото, відео або документ):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    users = await get_all_users()
    if not users:
        await message.answer("У базі немає жодного зареєстрованого учасника.")
        await state.clear()
        return

    await state.update_data(
        broadcast_msg_id=message.message_id,
        broadcast_chat_id=message.chat.id
    )
    await state.set_state(BroadcastAdmin.confirm_all)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🚨 ТАК, надіслати ВСІМ ({len(users)} ос.)", callback_data="confirm_bc_all")
    builder.button(text="❌ Скасувати розсилку", callback_data="admin_write_participants")
    builder.adjust(1)

    await message.reply(
        f"⚠️ <b>УВАГА! Підтвердження ЗАГАЛЬНОЇ розсилки</b>\n\n"
        f"Ви збираєтесь надіслати повідомлення вище <b>ВСІМ {len(users)} зареєстрованим учасникам</b>.\n\n"
        f"Перевірте зміст повідомлення (текст, посилання, медіа). Якщо все вірно — натисніть червону кнопку нижче для запуску розсилки.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "confirm_bc_all", BroadcastAdmin.confirm_all)
async def confirm_broadcast_all_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    data = await state.get_data()
    msg_id = data.get("broadcast_msg_id")
    from_chat_id = data.get("broadcast_chat_id")
    await state.clear()

    if not msg_id or not from_chat_id:
        await callback.answer("Помилка: повідомлення для розсилки не знайдено.", show_alert=True)
        return

    users = await get_all_users()
    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    await callback.message.edit_text(
        f"⏳ <b>Загальну розсилку запущено у фоні</b> для {len(users)} учасників.\n"
        f"Ти можеш користуватись ботом, звіт надійде після завершення.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    asyncio.create_task(_run_broadcast(callback.bot, from_chat_id, msg_id, users, callback.from_user.id))
    await callback.answer()


async def _run_broadcast(bot: Bot, from_chat_id: int, message_id: int, users: list, admin_id: int):
    success_count = 0
    fail_count = 0
    for user in users:
        try:
            await bot.copy_message(chat_id=user.telegram_id, from_chat_id=from_chat_id, message_id=message_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Загальну розсилку завершено!</b>\n\n"
                f"• Доставлено: <b>{success_count}</b>\n"
                f"• Не доставлено: <b>{fail_count}</b>\n"
                f"• Всього учасників: <b>{len(users)}</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ==================== РЕЖИМ 2: КОНКРЕТНИМ ЛЮДЯМ (@ТЕГ / ID) ====================

@router.callback_query(F.data == "bc_mode_targeted")
async def broadcast_targeted_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text(
        "🎯 <b>Розсилка конкретним людям</b>\n\n"
        "Введіть список отримувачів через кому, пробіл або з нового рядка.\n"
        "Можна вказувати <b>@username</b> або числовий <b>Telegram ID</b>.\n\n"
        "<i>Приклад:</i>\n"
        "<code>@ivan_ivanov, @petrenko, 123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastAdmin.waiting_for_recipients)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_recipients)
async def process_recipients_input(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    raw_text = message.text or ""
    import re
    tokens = [t.strip() for t in re.split(r"[\s,;]+", raw_text) if t.strip()]

    if not tokens:
        await message.answer("❌ Будь ласка, введіть хоча б один @тег або Telegram ID.")
        return

    found_users, not_found = await get_users_by_identifiers(tokens)

    # Якщо введено ID, яких немає в базі, але це числа — дозволяємо пряме відправлення
    extra_direct_ids = []
    unresolved_tokens = []
    for nf in not_found:
        if nf.isdigit():
            extra_direct_ids.append(int(nf))
        else:
            unresolved_tokens.append(nf)

    target_user_ids = [u.telegram_id for u in found_users] + extra_direct_ids

    if not target_user_ids:
        builder = InlineKeyboardBuilder()
        builder.button(text="Спробувати ще раз", callback_data="bc_mode_targeted")
        builder.button(text="Скасувати", callback_data="admin_write_participants")
        builder.adjust(1)

        await message.answer(
            "❌ <b>Жодного отримувача не знайдено в базі!</b>\n\n"
            f"Перевірте введені дані: {', '.join(tokens)}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return

    await state.update_data(target_user_ids=target_user_ids)

    lines = [f"🎯 <b>Знайдено отримувачів: {len(target_user_ids)}</b>\n"]
    for u in found_users[:15]:
        uname = f" ({u.username})" if u.username else ""
        grp = f" [{u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")
    if len(found_users) > 15:
        lines.append(f"<i>...та ще {len(found_users) - 15} осіб</i>")

    for did in extra_direct_ids:
        lines.append(f"• Прямий ID: <code>{did}</code> (не в базі)")

    if unresolved_tokens:
        lines.append(f"\n⚠️ <b>Не знайдено в базі ({len(unresolved_tokens)}):</b> {', '.join(unresolved_tokens)}")

    lines.append("\n✏️ <b>Тепер надішліть повідомлення для розсилки</b> (текст, фото, відео тощо):")

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(BroadcastAdmin.waiting_for_targeted_msg)


# ==================== РЕЖИМ 3: НЕ З ФІОТ ====================

@router.callback_query(F.data == "bc_mode_non_fiot")
async def broadcast_non_fiot_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    non_fiot_users = await get_non_fiot_users()
    if not non_fiot_users:
        await callback.answer("У базі немає користувачів не з ФІОТ 🎉", show_alert=True)
        return

    target_user_ids = [u.telegram_id for u in non_fiot_users]
    await state.update_data(target_user_ids=target_user_ids)

    lines = [f"👥 <b>Отримувачі не з ФІОТ: {len(non_fiot_users)} осіб</b>\n"]
    for u in non_fiot_users[:15]:
        uname = f" ({u.username})" if u.username else ""
        grp = f" [група: {u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")
    if len(non_fiot_users) > 15:
        lines.append(f"<i>...та ще {len(non_fiot_users) - 15} осіб</i>")

    lines.append("\n✏️ <b>Надішліть повідомлення, яке отримають ці користувачі:</b>")

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(BroadcastAdmin.waiting_for_targeted_msg)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_targeted_msg)
async def process_targeted_broadcast_message(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    target_user_ids = data.get("target_user_ids", [])
    if not target_user_ids:
        await message.answer("❌ Список отримувачів порожній.")
        await state.clear()
        return

    await state.update_data(
        broadcast_msg_id=message.message_id,
        broadcast_chat_id=message.chat.id
    )
    await state.set_state(BroadcastAdmin.confirm_targeted)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Так, надіслати ({len(target_user_ids)} ос.)", callback_data="confirm_bc_targeted")
    builder.button(text="❌ Скасувати", callback_data="admin_write_participants")
    builder.adjust(1)

    recipients_desc = f"<b>{len(target_user_ids)}</b> особам" if len(target_user_ids) > 1 else "<b>1</b> особі (тільки вам/обраному отримувачу)"

    await message.reply(
        f"🎯 <b>Підтвердження розсилки</b>\n\n"
        f"Повідомлення вище буде надіслано: {recipients_desc}.\n"
        f"<i>Загальна база учасників НЕ отримає це повідомлення.</i>\n\n"
        f"Надіслати?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "confirm_bc_targeted", BroadcastAdmin.confirm_targeted)
async def confirm_broadcast_targeted_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    data = await state.get_data()
    msg_id = data.get("broadcast_msg_id")
    from_chat_id = data.get("broadcast_chat_id")
    target_user_ids = data.get("target_user_ids", [])
    await state.clear()

    if not msg_id or not from_chat_id or not target_user_ids:
        await callback.answer("Помилка: дані для розсилки не знайдено.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    await callback.message.edit_text(
        f"⏳ <b>Розсилку запущено у фоні</b> для {len(target_user_ids)} вибраних отримувачів.\n"
        f"Ти можеш користуватись ботом, звіт надійде після завершення.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    asyncio.create_task(_run_targeted_broadcast(callback.bot, from_chat_id, msg_id, target_user_ids, callback.from_user.id))
    await callback.answer()


async def _run_targeted_broadcast(bot: Bot, from_chat_id: int, message_id: int, target_ids: list[int], admin_id: int):
    success_count = 0
    fail_count = 0
    for uid in target_ids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=message_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Таргетовану розсилку завершено!</b>\n\n"
                f"• Успішно доставлено: <b>{success_count}</b>\n"
                f"• Не вдалося доставити: <b>{fail_count}</b> (можливо, користувач заблокував бота)\n"
                f"• Всього отримувачів: <b>{len(target_ids)}</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ==================== УПРАВЛІННЯ ЗАБЛОКОВАНИМИ ====================

@router.callback_query(F.data == "admin_view_blocked")
async def view_blocked_users(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()
    blocked = await get_blocked_users()

    builder = InlineKeyboardBuilder()

    if not blocked:
        builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
        await callback.message.edit_text(
            "🚫 <b>Список заблокованих порожній</b>\n\n"
            "Наразі немає користувачів, заблокованих за спробу реєстрації з іншого факультету.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    lines = [f"🚫 <b>Заблоковані користувачі ({len(blocked)} осіб):</b>\n"]
    for i, b in enumerate(blocked[:15], 1):
        uname = f" (@{b.username.lstrip('@')})" if b.username else ""
        grp = f" | Група: <b>{b.attempted_group}</b>" if b.attempted_group else ""
        lines.append(f"{i}. <b>{b.name}</b>{uname}\n   ID: <code>{b.telegram_id}</code>{grp}\n   Причина: <i>{b.reason}</i>")

    if len(blocked) > 15:
        lines.append(f"\n<i>...та ще {len(blocked) - 15} осіб</i>")

    # Якщо заблокованих небагато (до 6) — даємо кнопки швидкого розблокування
    if len(blocked) <= 6:
        for b in blocked:
            label = f"🔓 {b.name[:18]}"
            builder.button(text=label, callback_data=f"admin_quick_unblock_{b.telegram_id}")

    builder.button(text="🔓 Розблокувати за @тегом чи ID", callback_data="admin_unblock_prompt")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    await callback.message.edit_text("\n\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_quick_unblock_"))
async def quick_unblock_user_handler(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    tg_id_str = callback.data.replace("admin_quick_unblock_", "")
    success, msg, unblocked_id = await unblock_user(tg_id_str)

    if success and unblocked_id:
        try:
            await callback.bot.send_message(
                chat_id=unblocked_id,
                text=(
                    "🎉 <b>Твій акаунт розблоковано адміністратором!</b>\n\n"
                    "Тепер ти можеш зареєструватися на захід. "
                    "Будь ласка, вказуй правильну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "Натисни /start або перейди в головне меню для реєстрації."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 До списку заблокованих", callback_data="admin_view_blocked")
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")
    builder.adjust(1)

    await callback.message.edit_text(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer("Розблоковано!")


@router.callback_query(F.data == "admin_unblock_prompt")
async def unblock_prompt_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_view_blocked")

    await callback.message.edit_text(
        "🔓 <b>Розблокування користувача</b>\n\n"
        "Введіть <b>@username</b> або числовий <b>Telegram ID</b> користувача, якого потрібно розблокувати:\n\n"
        "<i>Приклад:</i>\n"
        "<code>@shevchenko</code> або <code>123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AdminUnblock.waiting_for_identifier)
    await callback.answer()


@router.message(AdminUnblock.waiting_for_identifier)
async def process_unblock_identifier(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    identifier = (message.text or "").strip()
    if not identifier:
        await message.answer("❌ Будь ласка, введіть @username або Telegram ID.")
        return

    success, reply_msg, unblocked_id = await unblock_user(identifier)

    if success and unblocked_id:
        try:
            await message.bot.send_message(
                chat_id=unblocked_id,
                text=(
                    "🎉 <b>Твій акаунт розблоковано адміністратором!</b>\n\n"
                    "Тепер ти можеш зареєструватися на захід. "
                    "Будь ласка, вказуй правильну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "Натисни /start або перейди в головне меню для реєстрації."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 До списку заблокованих", callback_data="admin_view_blocked")
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")
    builder.adjust(1)

    await message.answer(reply_msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()


# ==================== СКАСУВАННЯ РЕЄСТРАЦІЇ (БЕЗ БЛОКУВАННЯ) ====================

@router.callback_query(F.data == "admin_cancel_reg_menu")
async def cancel_reg_menu_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()
    non_fiot = await get_non_fiot_users()
    non_fiot_count = len(non_fiot)

    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Конкретній людині (@тег / ID)", callback_data="cancel_reg_targeted")
    builder.button(text=f"👥 Усім не з ФІОТ ({non_fiot_count})", callback_data="cancel_reg_non_fiot")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    text = (
        "❌ <b>Скасування реєстрації учасників</b>\n\n"
        "Оберіть режим:\n"
        "• <b>🎯 Конкретній людині</b> — скасувати реєстрацію за списком @username або числових Telegram ID.\n"
        f"• <b>👥 Усім не з ФІОТ</b> — масове скасування для студентів інших факультетів (знайдено: {non_fiot_count} осіб).\n\n"
        "<i>Користувачі отримають повідомлення «Ваша реєстрація скасована». "
        "Вони НЕ блокуються і зможуть зареєструватись знову, якщо вкажуть правильну групу ФІОТ.</i>"
    )

    await callback.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cancel_reg_targeted")
async def cancel_reg_targeted_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_cancel_reg_menu")

    await callback.message.edit_text(
        "🎯 <b>Скасування реєстрації окремим користувачам</b>\n\n"
        "Введіть <b>@username</b> або числовий <b>Telegram ID</b> користувачів (через кому, пробіл або з нового рядка):\n\n"
        "<i>Приклад:</i>\n"
        "<code>@petrenko, @ivanov, 123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AdminCancelReg.waiting_for_identifiers)
    await callback.answer()


@router.message(AdminCancelReg.waiting_for_identifiers)
async def process_cancel_reg_input(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    raw_text = message.text or ""
    import re
    tokens = [t.strip() for t in re.split(r"[\s,;]+", raw_text) if t.strip()]

    if not tokens:
        await message.answer("❌ Будь ласка, введіть хоча б один @тег або Telegram ID.")
        return

    found_users, not_found = await get_users_by_identifiers(tokens)

    if not found_users:
        builder = InlineKeyboardBuilder()
        builder.button(text="Спробувати ще раз", callback_data="cancel_reg_targeted")
        builder.button(text="Скасувати", callback_data="admin_cancel_reg_menu")
        builder.adjust(1)
        await message.answer(
            f"❌ <b>Жодного користувача не знайдено в базі зареєстрованих!</b>\n\nВведено: {', '.join(tokens)}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return

    cancelled_ids = await cancel_users_registration(found_users)

    notify_success = 0
    for u in found_users:
        try:
            await message.bot.send_message(
                chat_id=u.telegram_id,
                text=(
                    "⚠️ <b>Твою реєстрацію на лекцію «Хто така Студрада ФІОТ» скасовано адміністратором.</b>\n\n"
                    "Якщо ти студент ФІОТ і сталася помилка, або ти хочеш змінити дані чи формат участі — "
                    "ти можеш зареєструватися повторно у боті (натисни /start або відкрий головне меню), "
                    "вказавши свою правильну академічну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "<i>Чекаємо тебе на лекції!</i>"
                ),
                parse_mode="HTML"
            )
            notify_success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    lines = [f"✅ <b>Скасовано реєстрацію для {len(cancelled_ids)} осіб!</b>\n"]
    for u in found_users:
        uname = f" (@{u.username.lstrip('@')})" if u.username else ""
        grp = f" [{u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")

    lines.append(f"\n📨 Сповіщень доставлено: {notify_success} з {len(found_users)}")

    if not_found:
        lines.append(f"\n⚠️ Не знайдено в базі ({len(not_found)}): {', '.join(not_found)}")

    lines.append("\n<i>Користувачі НЕ заблоковані і можуть зареєструватися знову за бажанням.</i>")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")

    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "cancel_reg_non_fiot")
async def cancel_reg_non_fiot_prompt(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    non_fiot = await get_non_fiot_users()
    if not non_fiot:
        await callback.answer("У базі немає користувачів не з ФІОТ 🎉", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Так, скасувати ({len(non_fiot)} осіб)", callback_data="confirm_cancel_non_fiot")
    builder.button(text="❌ Ні, повернутися", callback_data="admin_cancel_reg_menu")
    builder.adjust(1)

    lines = [f"⚠️ <b>Підтвердження скасування реєстрації для {len(non_fiot)} осіб не з ФІОТ:</b>\n"]
    for u in non_fiot[:10]:
        uname = f" (@{u.username.lstrip('@')})" if u.username else ""
        lines.append(f"• {u.name}{uname} [група: {u.group_name}]")
    if len(non_fiot) > 10:
        lines.append(f"<i>...та ще {len(non_fiot) - 10} осіб</i>")

    lines.append("\nКористувачам буде надіслано повідомлення: «Ваша реєстрація скасована». Вони НЕ будуть заблоковані.")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel_non_fiot")
async def confirm_cancel_non_fiot_handler(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    non_fiot = await get_non_fiot_users()
    if not non_fiot:
        await callback.answer("Уже немає користувачів не з ФІОТ.", show_alert=True)
        return

    cancelled_ids = await cancel_users_registration(non_fiot)

    notify_success = 0
    for u in non_fiot:
        try:
            await callback.bot.send_message(
                chat_id=u.telegram_id,
                text=(
                    "⚠️ <b>Твою реєстрацію на лекцію «Хто така Студрада ФІОТ» скасовано адміністратором.</b>\n\n"
                    "Якщо ти студент ФІОТ і сталася помилка, або ти хочеш змінити дані чи формат участі — "
                    "ти можеш зареєструватися повторно у боті (натисни /start або відкрий головне меню), "
                    "вказавши свою правильну академічну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "<i>Чекаємо тебе на лекції!</i>"
                ),
                parse_mode="HTML"
            )
            notify_success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")

    await callback.message.edit_text(
        f"✅ <b>Скасовано реєстрацію для {len(cancelled_ids)} осіб не з ФІОТ!</b>\n\n"
        f"• Записів видалено: {len(cancelled_ids)}\n"
        f"• Сповіщень доставлено: {notify_success}\n\n"
        f"Користувачі не заблоковані і можуть зареєструватися заново за бажанням.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer("Реєстрації скасовано!")


# ==================== ПЕРЕГЛЯД РЕЄСТРАЦІЙ НЕ З ФІОТ ====================

@router.callback_query(F.data == "admin_view_non_fiot")
async def view_non_fiot_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()
    non_fiot = await get_non_fiot_users()

    builder = InlineKeyboardBuilder()
    if not non_fiot:
        builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")
        await callback.message.edit_text(
            "🎉 <b>Усі зареєстровані учасники — з ФІОТ!</b>\n\n"
            "Немає жодної активної реєстрації з інших факультетів або з некоректним шифром групи.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    builder.button(text=f"📨 Написати їм усім ({len(non_fiot)})", callback_data="bc_mode_non_fiot")
    builder.button(text=f"❌ Скасувати їм реєстрацію ({len(non_fiot)})", callback_data="cancel_reg_non_fiot")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    lines = [
        f"👥 <b>Зареєстровані учасники не з ФІОТ ({len(non_fiot)} осіб):</b>\n",
        "<i>Ці користувачі вказали групу іншого факультету або нестандартний шифр:</i>\n"
    ]

    for idx, u in enumerate(non_fiot[:25], 1):
        uname = f" (@{u.username.lstrip('@')})" if u.username else ""
        faculty = detect_faculty(u.group_name)
        lines.append(
            f"<b>{idx}.</b> {u.name}{uname}\n"
            f"   • Група: <code>{u.group_name}</code> ({faculty})\n"
            f"   • ID: <code>{u.telegram_id}</code>"
        )

    if len(non_fiot) > 25:
        lines.append(f"\n<i>...та ще {len(non_fiot) - 25} осіб.</i>")

    lines.append("\nОберіть потрібну дію:")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()






